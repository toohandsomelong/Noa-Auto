from __future__ import annotations

import json

import pytest

import web.bot_controller as bc


class _ImmediateThread:
    """Run the thread target synchronously so chain logic can be tested inline."""

    def __init__(self, target=None, daemon=None, args=(), kwargs=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


class TestChainAndLifecycle:
    """Suite: controller state, config clamping, plan-chain progression, and dispatch."""

    @pytest.mark.positive
    def test_get_state_initial(self, controller):
        """A fresh controller reports IDLE with no active target."""
        assert controller.get_state() == {"state": "IDLE", "active_target": None}

    @pytest.mark.positive
    def test_get_config_defaults(self, tmp_config, controller):
        """Missing config falls back to the default chain/repeat/interval."""
        config = controller.get_config()
        assert config["plans"] == ["team_trials"]
        assert config["repeat"] == 1
        assert config["check_interval"] == 0.5

    @pytest.mark.edge
    def test_set_config_clamps_and_applies_check_interval(self, tmp_config, controller, fake_screen_bot):
        """check_interval is clamped to [0.05, 10.0] and pushed to the screen bot."""
        controller.set_config(check_interval=99)
        assert controller.get_config()["check_interval"] == 10.0
        assert fake_screen_bot.check_interval == 10.0

        controller.set_config(check_interval=0.001)
        assert controller.get_config()["check_interval"] == 0.05

    @pytest.mark.negative
    def test_set_config_repeat_ignores_invalid(self, tmp_config, controller):
        """Invalid or non-positive repeat values are ignored."""
        controller.set_config(repeat=3)
        assert controller.get_config()["repeat"] == 3
        controller.set_config(repeat="nonsense")
        assert controller.get_config()["repeat"] == 3
        controller.set_config(repeat=0)
        assert controller.get_config()["repeat"] == 3

    @pytest.mark.edge
    def test_set_config_runners_accepts_string_and_list(self, tmp_config, controller):
        """The chain accepts a bare string or a list."""
        controller.set_config(plans="solo")
        assert controller.get_config()["plans"] == ["solo"]
        controller.set_config(plans=["a", "b"])
        assert controller.get_config()["plans"] == ["a", "b"]

    @pytest.mark.edge
    def test_get_config_clamps_stored_values(self, tmp_config, controller):
        """Out-of-range stored values are clamped on read."""
        with open(bc.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"check_interval": 500, "repeat": 0}, f)
        config = controller.get_config()
        assert config["check_interval"] == 10.0
        assert config["repeat"] == 1

    @pytest.mark.negative
    def test_validate_plans_filters_unknown(self, monkeypatch, controller, fake_logger):
        """Unknown plan names are dropped and logged."""
        monkeypatch.setattr(bc, "PLANS", {"a": object()})
        assert controller._validate_plans(["a", "b", 1]) == ["a"]
        assert any("Unknown plan" in msg for msg in fake_logger.messages("ERR"))

    @pytest.mark.edge
    def test_validate_plans_edge_inputs(self, monkeypatch, controller):
        """String/None/non-list chain inputs are handled without raising."""
        monkeypatch.setattr(bc, "PLANS", {"a": object()})
        assert controller._validate_plans("a") == ["a"]
        assert controller._validate_plans(None) == []
        assert controller._validate_plans(123) == []

    @pytest.mark.positive
    def test_preview_api(self, controller, fake_screen_bot):
        """Preview toggle/mode validate and mutate the screen bot."""
        assert controller.get_preview() == {"enabled": False, "mode": "snapshot"}
        assert controller.set_preview(True) is True
        assert fake_screen_bot.preview is True
        assert controller.set_preview_mode("live") is True
        assert fake_screen_bot.preview_mode == "live"
        assert controller.set_preview_mode("bogus") is False

    @pytest.mark.positive
    def test_step_event_is_broadcast(self, controller):
        """Step events are forwarded to registered listeners."""
        received = []
        controller.on_step_event(received.append)
        controller._on_step({"plan": "x", "step_index": 3, "step_label": "s"})
        assert len(received) == 1
        assert received[0]["type"] == "step"
        assert received[0]["plan"] == "x"
        assert received[0]["step_index"] == 3

    @pytest.mark.negative
    def test_preview_unavailable_without_screen_bot(self, fake_logger, fake_game_launcher, fake_focus_watcher):
        """With no screen bot, preview operations report unavailable."""
        from core.state_manager import StateManager

        controller = bc.BotController(fake_logger, StateManager(), fake_game_launcher, fake_focus_watcher, None)
        assert controller.set_preview(True) is False
        assert controller.get_preview() == {"enabled": False, "mode": "snapshot"}

    @pytest.mark.edge
    def test_start_when_already_active_warns(self, controller, fake_logger, monkeypatch):
        """Starting while already active warns and dispatches nothing."""
        from core.state_manager import BotState

        dispatched = []
        monkeypatch.setattr(controller, "_build_and_start", lambda *a, **k: dispatched.append(a))
        controller.state_manager.state = BotState.RUNNING
        controller.start()
        assert controller.state_manager.state == BotState.RUNNING
        assert dispatched == []
        assert any("already running" in msg for msg in fake_logger.messages("WARN"))

    @pytest.mark.negative
    def test_start_with_empty_chain_warns(self, tmp_config, controller, fake_logger, monkeypatch):
        """An empty plan chain warns and does not start."""
        from core.state_manager import BotState

        with open(bc.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"plans": []}, f)
        dispatched = []
        monkeypatch.setattr(controller, "_build_and_start", lambda *a, **k: dispatched.append(a))
        controller.start()
        assert controller.state_manager.state != BotState.RUNNING
        assert dispatched == []
        assert any("No plans" in msg for msg in fake_logger.messages("WARN"))

    @pytest.mark.positive
    def test_chain_advances_then_repeats_then_cleans_up(self, monkeypatch, controller):
        """The chain walks its plans, repeats, then cleans up."""
        monkeypatch.setattr(bc.threading, "Thread", _ImmediateThread)
        calls = []
        cleaned = []
        monkeypatch.setattr(controller, "_build_and_start", lambda name, is_first=False: calls.append(name))
        monkeypatch.setattr(controller, "_cleanup", lambda: cleaned.append(True))
        controller._chain = ["a", "b"]
        controller._chain_idx = 0
        controller._repeat = 2
        controller._play_count = 0

        controller._on_plan_done("a")
        assert calls == ["b"]
        controller._on_plan_done("b")
        assert calls == ["b", "a"]
        controller._on_plan_done("a")
        assert calls == ["b", "a", "b"]
        controller._on_plan_done("b")
        assert cleaned == [True]

    @pytest.mark.edge
    def test_plan_done_with_empty_chain_cleans_up(self, monkeypatch, controller):
        """Completing a plan with no chain entries cleans up immediately."""
        monkeypatch.setattr(bc.threading, "Thread", _ImmediateThread)
        cleaned = []
        monkeypatch.setattr(controller, "_cleanup", lambda: cleaned.append(True))
        controller._chain = []
        controller._chain_idx = 0
        controller._repeat = 1
        controller._play_count = 0
        controller._on_plan_done("a")
        assert cleaned == [True]

    @pytest.mark.positive
    def test_build_failure_logs_and_continues(self, monkeypatch, tmp_config, controller, fake_logger):
        """A plan builder that raises is logged without crashing the controller."""
        def boom(_logger):
            raise RuntimeError("nope")

        monkeypatch.setattr(bc, "PLANS", {"bad": boom})
        controller._build_and_start("bad")
        assert any("bad" in msg for msg in fake_logger.messages("ERR"))

    @pytest.mark.edge
    def test_abort_plumbing_removed(self, controller):
        """The on_plan_abort handler/dispatch has been removed from the controller."""
        assert not hasattr(controller, "_on_plan_abort")
        assert not hasattr(controller.screen_bot, "on_plan_abort")

    @pytest.mark.positive
    def test_cleanup_resets_to_idle(self, controller):
        """Cleanup returns the controller to IDLE."""
        from core.state_manager import BotState

        controller.state_manager.state = BotState.RUNNING
        controller._cleanup()
        assert controller.state_manager.state is BotState.IDLE

    @pytest.mark.positive
    def test_browse_root_returns_drives(self, controller):
        """Browsing the root returns available drives."""
        result = controller.browse("")
        assert result["parent"] is None
        assert set(result) == {"dirs", "exes", "images", "parent"}

    @pytest.mark.positive
    def test_browse_directory_classifies_entries(self, tmp_path, controller):
        """Browsing a directory splits dirs, exes, and images."""
        (tmp_path / "sub").mkdir()
        (tmp_path / "app.exe").write_text("x", encoding="utf-8")
        (tmp_path / "img.PNG").write_text("x", encoding="utf-8")
        (tmp_path / "note.txt").write_text("x", encoding="utf-8")
        result = controller.browse(str(tmp_path))
        assert result["dirs"] == ["sub"]
        assert result["exes"] == ["app.exe"]
        assert result["images"] == ["img.PNG"]
        assert result["parent"] == str(tmp_path.parent)

    @pytest.mark.positive
    def test_autofill_writes_tab_name(self, tmp_plans, controller):
        """Autofill writes a detected window title into a plan's config."""
        import engine.plan_loader as pl

        pl.save_plan(
            "p",
            {
                "name": "P",
                "steps": [{"type": "click", "targets": [{"template": "templates/x/A.png"}]}],
                "config": {},
            },
        )
        controller._autofill_tab_name("p", "My Title")
        assert pl.get_plan("p")["config"]["tab_name"] == "My Title"

    @pytest.mark.edge
    def test_autofill_skips_when_tab_name_present(self, tmp_plans, controller):
        """Autofill does not overwrite an existing tab_name."""
        import engine.plan_loader as pl

        pl.save_plan(
            "p2",
            {
                "name": "P2",
                "steps": [{"type": "click", "targets": [{"template": "templates/x/A.png"}]}],
                "config": {"tab_name": "Existing"},
            },
        )
        controller._autofill_tab_name("p2", "New")
        assert pl.get_plan("p2")["config"]["tab_name"] == "Existing"

    @pytest.mark.positive
    def test_get_plans_shape(self, tmp_plans, tmp_config, controller):
        """get_plans returns the registry/labels/chain shape."""
        data = controller.get_plans()
        assert {"plans", "labels", "current", "chain", "repeat"} <= set(data)
        assert data["labels"] == {}

    @pytest.mark.edge
    def test_get_config_reads_legacy_keys(self, tmp_config, controller):
        """Legacy routine/routines keys are still honored."""
        with open(bc.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"routine": "legacy_plan"}, f)
        assert controller.get_config()["plans"] == ["legacy_plan"]

        with open(bc.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"routines": ["old_chain"]}, f)
        assert controller.get_config()["plans"] == ["old_chain"]

        with open(bc.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"plans": ["new_chain"]}, f)
        assert controller.get_config()["plans"] == ["new_chain"]

    @pytest.mark.positive
    def test_set_config_writes_new_plans_key(self, tmp_config, controller):
        """Saving always writes the new plans key, never the legacy routines key."""
        controller.set_config(plans=["a", "b"])
        with open(bc.CONFIG_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["plans"] == ["a", "b"]
        assert "routines" not in saved


class FakeRecorder:
    def __init__(self, *, on_toggle=None, on_crop_request=None, on_next_step=None, on_prev_step=None, on_remove_target=None, focus_watcher=None):
        self.state = "IDLE"
        self.steps = []
        self.current_targets = []
        self._edit_index = 0
        self._name = None
        self._plan_name = None
        self._editing = False
        self._toggle_cb = on_toggle
        self._crop_cb = on_crop_request
        self._next_cb = on_next_step
        self._prev_cb = on_prev_step
        self._remove_cb = on_remove_target
        self._focus_watcher = focus_watcher
        self._last_region = None

    def start(self, name=None):
        if self.state != "IDLE":
            return False
        self.state = "RECORDING"
        self._name = name
        self._plan_name = None
        self._editing = False
        self.steps = []
        self.current_targets = []
        self._edit_index = 0
        return True

    def start_edit(self, name, plan):
        if self.state != "IDLE":
            return False
        self.state = "RECORDING"
        self._name = plan.get("name") or name
        self._plan_name = name
        self._editing = True
        self.steps = [dict(s) for s in plan.get("steps", [])]
        self._edit_index = max(0, len(self.steps) - 1)
        self.current_targets = self.steps[self._edit_index]["targets"] if self.steps else []
        return True

    def stop(self):
        if self.state == "IDLE":
            return None
        if self._edit_index >= len(self.steps) and self.current_targets:
            self._commit_pending()
        self.state = "IDLE"
        steps = [step for step in self.steps if step["targets"]]
        if not steps:
            return None
        result = {"name": self._name or "recorded", "steps": steps}
        if self._editing:
            result["editing"] = True
            result["plan_name"] = self._plan_name
        self._editing = False
        self._plan_name = None
        return result

    def begin_crop(self):
        return ("frame", {"left": 0, "top": 0, "width": 10, "height": 10})

    def accept_target(self, crops, action, *, scroll_dir=None, scroll_anchor=None, offset=None):
        target = {
            "template": "templates/recorded/x.png",
            "action": action,
            "crops": len(crops),
            "offset": offset,
        }
        self.current_targets.append(target)
        return target

    def next_step(self):
        if self.state != "RECORDING":
            return None
        if self._edit_index >= len(self.steps):
            if not self.current_targets:
                return None
            self._commit_pending()
        if self._edit_index + 1 < len(self.steps):
            self._edit_index += 1
            step = self.steps[self._edit_index]
            self.current_targets = step["targets"]
            return step
        self._edit_index = len(self.steps)
        self.current_targets = []
        return self.steps[-1]

    def previous_step(self):
        if self.state != "RECORDING" or self._edit_index == 0:
            return None
        if self._edit_index >= len(self.steps) and self.current_targets:
            self._commit_pending()
        self._edit_index -= 1
        step = self.steps[self._edit_index]
        self.current_targets = step["targets"]
        return step

    def _commit_pending(self):
        step = {"label": f"step {self._edit_index + 1}", "targets": list(self.current_targets)}
        self.steps.append(step)
        self._edit_index = len(self.steps) - 1
        self.current_targets = step["targets"]
        return step

    def remove_target(self, index):
        if self.state != "RECORDING" or not self.current_targets:
            return None
        if index < 0:
            index = len(self.current_targets) + index
        if index < 0 or index >= len(self.current_targets):
            return None
        return self.current_targets.pop(index)

    def status(self):
        return {
            "state": self.state,
            "step_count": len(self.steps),
            "target_count": len(self.current_targets),
            "step_index": self._edit_index + 1,
            "current_targets": list(self.current_targets),
        }

    def last_region(self):
        return self._last_region


class FakeOverlay:
    def __init__(self, **kwargs):
        self.calls = []

    def start(self):
        self.calls.append("start")
        return True

    def stop(self):
        self.calls.append("stop")

    def show_bar(self, step=1, targets=0):
        self.calls.append(("show_bar", step, targets))

    def hide_bar(self):
        self.calls.append("hide_bar")

    def request_crop(self):
        self.calls.append("request_crop")

    def show_crop(self, frame, region):
        self.calls.append(("show_crop", region))

    def hide_crop(self):
        self.calls.append("hide_crop")

    def set_counts(self, step, targets):
        self.calls.append(("set_counts", step, targets))

    def set_targets(self, step, targets):
        self.calls.append(("set_targets", step, len(targets)))


@pytest.fixture
def patched_controller(monkeypatch, tmp_config, fake_logger, fake_game_launcher, fake_focus_watcher, fake_screen_bot):
    """A controller whose recorder/overlay are replaced with call-recording fakes."""
    from core.state_manager import StateManager

    monkeypatch.setattr(bc, "Recorder", FakeRecorder)
    monkeypatch.setattr(bc, "RecorderOverlay", FakeOverlay)
    return bc.BotController(
        fake_logger,
        StateManager(),
        fake_game_launcher,
        fake_focus_watcher,
        fake_screen_bot,
    )


class TestRecordingSession:
    """Suite: record -> crop -> next-step -> save flow and its guards."""

    @pytest.mark.negative
    def test_start_recording_refused_while_bot_active(self, patched_controller):
        """Recording is refused while the bot is running."""
        from core.state_manager import BotState

        patched_controller.state_manager.state = BotState.RUNNING
        result = patched_controller.start_recording()
        assert result["ok"] is False

    @pytest.mark.positive
    def test_start_stop_recording_saves_plan(self, tmp_plans, tmp_config, patched_controller, fake_logger):
        """Stopping a recording saves a plan with the recorded steps."""
        with open(bc.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"tab_name": "Game", "game_path": "C:/game.exe"}, f)

        result = patched_controller.start_recording(name="my flow")
        assert result["ok"] is True
        assert patched_controller._recorder.state == "RECORDING"
        assert patched_controller._overlay.calls[:2] == ["start", ("show_bar", 1, 0)]

        patched_controller._recorder.accept_target(["crop"], "left_click")
        stop_result = patched_controller.stop_recording()
        assert stop_result["ok"] is True
        assert stop_result["name"] == "my flow"
        assert "hide_crop" in patched_controller._overlay.calls
        assert "hide_bar" in patched_controller._overlay.calls
        saved = bc.get_plan("my flow")
        assert saved["config"]["tab_name"] is None
        assert saved["config"]["game_path"] is None

    @pytest.mark.negative
    def test_stop_recording_with_no_steps_returns_error(self, patched_controller):
        """Stopping with no recorded steps reports an error."""
        patched_controller.start_recording()
        result = patched_controller.stop_recording()
        assert result["ok"] is False

    @pytest.mark.positive
    def test_begin_crop_delegates(self, patched_controller):
        """begin_crop shows the crop overlay via the recorder region."""
        patched_controller.start_recording()
        result = patched_controller.begin_crop()
        assert result["ok"] is True
        assert patched_controller._overlay.calls[-1][0] == "show_crop"

    @pytest.mark.positive
    def test_crop_confirm_forwards_offset(self, patched_controller):
        """A confirmed crop forwards its offset to the recorder and updates counts."""
        patched_controller.start_recording()
        patched_controller._on_crop_confirm(["crop"], "left_click", None, None, (5, -3))
        assert patched_controller._recorder.current_targets[-1]["offset"] == (5, -3)
        assert ("set_counts", 1, 1) in patched_controller._overlay.calls
        assert ("set_targets", 1, 1) in patched_controller._overlay.calls

    @pytest.mark.positive
    def test_request_crop_delegates(self, patched_controller):
        """request_crop asks the overlay to request a crop."""
        patched_controller.start_recording()
        result = patched_controller.request_crop()
        assert result["ok"] is True
        assert patched_controller._overlay.calls[-1] == "request_crop"

    @pytest.mark.positive
    def test_next_step_delegates(self, patched_controller):
        """next_step commits the current targets and updates the overlay bar."""
        patched_controller.start_recording()
        patched_controller._recorder.accept_target(["crop"], "left_click")
        result = patched_controller.next_step()
        assert result["ok"] is True
        assert patched_controller._recorder.status()["step_count"] == 1
        assert patched_controller._overlay.calls[-2:] == [
            ("set_counts", 2, 0),
            ("set_targets", 2, 0),
        ]

    @pytest.mark.negative
    def test_next_step_without_targets_fails(self, patched_controller):
        """next_step with no targets reports an error."""
        patched_controller.start_recording()
        result = patched_controller.next_step()
        assert result["ok"] is False

    @pytest.mark.positive
    def test_previous_step_saves_current_then_rewinds(self, patched_controller):
        """previous_step saves uncommitted targets, then reopens the previous step."""
        patched_controller.start_recording()
        patched_controller._recorder.accept_target(["crop"], "left_click")
        patched_controller.next_step()
        patched_controller._recorder.accept_target(["crop2"], "left_click")
        result = patched_controller.previous_step()
        assert result["ok"] is True
        status = patched_controller._recorder.status()
        assert status["step_count"] == 2
        assert status["target_count"] == 1
        assert patched_controller._overlay.calls[-2:] == [
            ("set_counts", 1, 1),
            ("set_targets", 1, 1),
        ]

    @pytest.mark.positive
    def test_previous_step_with_empty_current_reopens_last(self, patched_controller):
        """previous_step reopens the last step when no current targets exist."""
        patched_controller.start_recording()
        patched_controller._recorder.accept_target(["crop"], "left_click")
        patched_controller.next_step()
        result = patched_controller.previous_step()
        assert result["ok"] is True
        status = patched_controller._recorder.status()
        assert status["step_count"] == 1
        assert status["target_count"] == 1
        assert patched_controller._overlay.calls[-2:] == [
            ("set_counts", 1, 1),
            ("set_targets", 1, 1),
        ]

    @pytest.mark.edge
    def test_previous_at_first_step_keeps_next_working(self, patched_controller):
        """Prev on step 1 is a no-op and does not clear the step for the next Next."""
        patched_controller.start_recording()
        patched_controller._recorder.accept_target(["a"], "left_click")
        patched_controller.next_step()
        patched_controller._recorder.accept_target(["b"], "left_click")
        patched_controller.previous_step()
        assert patched_controller._recorder.status()["step_index"] == 1

        blocked = patched_controller.previous_step()
        assert blocked["ok"] is False
        assert patched_controller._recorder.status()["target_count"] == 1

        forward = patched_controller.next_step()
        assert forward["ok"] is True
        assert patched_controller._recorder.status()["step_index"] == 2

    @pytest.mark.positive
    def test_next_step_after_previous_navigates_forward(self, patched_controller):
        """next_step moves forward to the next saved step after going back."""
        patched_controller.start_recording()
        patched_controller._recorder.accept_target(["a"], "left_click")
        patched_controller.next_step()
        patched_controller._recorder.accept_target(["b"], "left_click")
        patched_controller.next_step()
        patched_controller._recorder.accept_target(["c"], "left_click")
        patched_controller.previous_step()  # now editing step 2
        result = patched_controller.next_step()
        assert result["ok"] is True
        status = patched_controller._recorder.status()
        assert status["step_count"] == 3
        assert status["step_index"] == 3
        assert status["target_count"] == 1
        assert patched_controller._overlay.calls[-2:] == [
            ("set_counts", 3, 1),
            ("set_targets", 3, 1),
        ]

    @pytest.mark.positive
    def test_remove_target_delegates(self, patched_controller):
        """remove_target removes the indexed target and refreshes the bar."""
        patched_controller.start_recording()
        patched_controller._recorder.accept_target(["a"], "left_click")
        patched_controller._recorder.accept_target(["b"], "left_click")
        result = patched_controller.remove_target(-1)
        assert result["ok"] is True
        status = patched_controller._recorder.status()
        assert status["target_count"] == 1
        assert patched_controller._overlay.calls[-2:] == [
            ("set_counts", 1, 1),
            ("set_targets", 1, 1),
        ]

    @pytest.mark.negative
    def test_remove_target_with_no_targets_fails(self, patched_controller):
        """remove_target with no targets reports an error."""
        patched_controller.start_recording()
        result = patched_controller.remove_target(0)
        assert result["ok"] is False

    @pytest.mark.positive
    def test_bot_start_stops_recording(self, monkeypatch, tmp_plans, patched_controller):
        """Starting the bot while recording stops and saves the recording first."""
        monkeypatch.setattr(bc, "PLANS", {})
        patched_controller.start_recording()
        patched_controller._recorder.accept_target(["crop"], "left_click")
        patched_controller.start()
        assert patched_controller._recorder.state == "IDLE"
        assert bc.get_plan("recorded") is not None

    @pytest.mark.edge
    def test_unique_plan_name_collision(self, tmp_plans, patched_controller):
        """Colliding plan names get a numeric suffix."""
        import engine.plan_loader as pl

        pl.save_plan("x", {"name": "X", "steps": [{"type": "click", "targets": [{"template": "a.png"}]}]})
        assert patched_controller._unique_plan_name("x") == "x (2)"
        pl.save_plan("x (2)", {"name": "X2", "steps": [{"type": "click", "targets": [{"template": "a.png"}]}]})
        assert patched_controller._unique_plan_name("x") == "x (3)"

    @pytest.mark.positive
    def test_start_edit_recording_loads_existing_plan(self, tmp_plans, patched_controller):
        """start_recording with plan_name seeds the recorder with the existing plan."""
        import engine.plan_loader as pl

        pl.save_plan(
            "existing",
            {
                "name": "Existing Plan",
                "steps": [
                    {"type": "click", "targets": [{"template": "a.png", "action": "left_click"}]},
                    {"type": "click", "targets": [{"template": "b.png", "action": "right_click"}]},
                ],
                "config": {"tab_name": "Game", "delay": 1.0},
            },
        )
        result = patched_controller.start_recording(plan_name="existing")
        assert result["ok"] is True
        assert patched_controller._recorder._editing is True
        assert patched_controller._recorder._plan_name == "existing"
        assert patched_controller._editing_plan_name == "existing"

    @pytest.mark.positive
    def test_stop_edit_recording_overwrites_original_plan(self, tmp_plans, patched_controller):
        """Stopping an edit without save_as overwrites the original plan file."""
        import engine.plan_loader as pl

        pl.save_plan(
            "existing",
            {
                "name": "Existing Plan",
                "steps": [
                    {"type": "click", "targets": [{"template": "a.png", "action": "left_click"}]},
                ],
                "config": {"tab_name": "Game", "delay": 1.0},
            },
        )
        patched_controller.start_recording(plan_name="existing")
        patched_controller._recorder.accept_target(["crop"], "left_click")
        stop_result = patched_controller.stop_recording()
        assert stop_result["ok"] is True
        assert stop_result["name"] == "existing"
        saved = pl.get_plan("existing")
        assert saved["name"] == "Existing Plan"
        assert saved["config"]["tab_name"] == "Game"
        assert saved["config"]["delay"] == 1.0
        assert len(saved["steps"]) == 1
        assert saved["steps"][0]["targets"][-1]["template"] == "templates/recorded/x.png"

    @pytest.mark.positive
    def test_stop_edit_recording_save_as_creates_copy(self, tmp_plans, patched_controller):
        """Stopping an edit with save_as saves to a new plan instead of overwriting."""
        import engine.plan_loader as pl

        pl.save_plan(
            "existing",
            {
                "name": "Existing Plan",
                "steps": [
                    {"type": "click", "targets": [{"template": "a.png", "action": "left_click"}]},
                ],
            },
        )
        patched_controller.start_recording(plan_name="existing")
        patched_controller._recorder.accept_target(["crop"], "left_click")
        stop_result = patched_controller.stop_recording(save_as="existing copy")
        assert stop_result["ok"] is True
        assert stop_result["name"] == "existing copy"
        assert pl.get_plan("existing") is not None
        assert pl.get_plan("existing copy") is not None

    @pytest.mark.negative
    def test_start_edit_recording_missing_plan_returns_error(self, patched_controller):
        """start_recording with an unknown plan_name reports a clear error."""
        result = patched_controller.start_recording(plan_name="missing")
        assert result["ok"] is False
        assert "not found" in result["error"]
