from __future__ import annotations

import json

import pytest

import web.bot_controller as bc


class _ImmediateThread:
    def __init__(self, target=None, daemon=None, args=(), kwargs=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


def test_get_state_initial(controller):
    assert controller.get_state() == {"state": "IDLE", "active_target": None}


def test_get_config_defaults(tmp_config, controller):
    config = controller.get_config()
    assert config["routines"] == ["team_trials"]
    assert config["repeat"] == 1
    assert config["check_interval"] == 0.5


def test_set_config_clamps_and_applies_check_interval(
    tmp_config, controller, fake_screen_bot
):
    controller.set_config(check_interval=99)
    assert controller.get_config()["check_interval"] == 10.0
    assert fake_screen_bot.check_interval == 10.0

    controller.set_config(check_interval=0.001)
    assert controller.get_config()["check_interval"] == 0.05


def test_set_config_repeat_ignores_invalid(tmp_config, controller):
    controller.set_config(repeat=3)
    assert controller.get_config()["repeat"] == 3
    controller.set_config(repeat="nonsense")
    assert controller.get_config()["repeat"] == 3
    controller.set_config(repeat=0)
    assert controller.get_config()["repeat"] == 3


def test_set_config_routines_accepts_string_and_list(tmp_config, controller):
    controller.set_config(routines="solo")
    assert controller.get_config()["routines"] == ["solo"]
    controller.set_config(routines=["a", "b"])
    assert controller.get_config()["routines"] == ["a", "b"]


def test_get_config_clamps_stored_values(tmp_config, controller):
    with open(bc.CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"check_interval": 500, "repeat": 0}, f)
    config = controller.get_config()
    assert config["check_interval"] == 10.0
    assert config["repeat"] == 1


def test_validate_routines_filters_unknown(monkeypatch, controller, fake_logger):
    monkeypatch.setattr(bc, "ROUTINES", {"a": object()})
    assert controller._validate_routines(["a", "b", 1]) == ["a"]
    assert any("Unknown routine" in msg for msg in fake_logger.messages("ERR"))


def test_validate_routines_edge_inputs(monkeypatch, controller):
    monkeypatch.setattr(bc, "ROUTINES", {"a": object()})
    assert controller._validate_routines("a") == ["a"]
    assert controller._validate_routines(None) == []
    assert controller._validate_routines(123) == []


def test_preview_api(controller, fake_screen_bot):
    assert controller.get_preview() == {"enabled": False, "mode": "snapshot"}
    assert controller.set_preview(True) is True
    assert fake_screen_bot.preview is True
    assert controller.set_preview_mode("live") is True
    assert fake_screen_bot.preview_mode == "live"
    assert controller.set_preview_mode("bogus") is False


def test_step_event_is_broadcast(controller):
    received = []
    controller.on_step_event(received.append)
    controller._on_step({"routine": "x", "step_index": 3, "step_label": "s"})
    assert len(received) == 1
    assert received[0]["type"] == "step"
    assert received[0]["routine"] == "x"
    assert received[0]["step_index"] == 3


def test_preview_unavailable_without_screen_bot(
    fake_logger, fake_game_launcher, fake_focus_watcher
):
    from core.state_manager import StateManager

    controller = bc.BotController(
        fake_logger, StateManager(), fake_game_launcher, fake_focus_watcher, None
    )
    assert controller.set_preview(True) is False
    assert controller.get_preview() == {"enabled": False, "mode": "snapshot"}


def test_start_when_already_active_warns(controller, fake_logger, monkeypatch):
    from core.state_manager import BotState

    dispatched = []
    monkeypatch.setattr(controller, "_build_and_start", lambda *a, **k: dispatched.append(a))
    controller.state_manager.state = BotState.RUNNING
    controller.start()
    assert controller.state_manager.state == BotState.RUNNING
    assert dispatched == []
    assert any("already running" in msg for msg in fake_logger.messages("WARN"))


def test_start_with_empty_chain_warns(tmp_config, controller, fake_logger, monkeypatch):
    from core.state_manager import BotState

    with open(bc.CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"routines": []}, f)
    dispatched = []
    monkeypatch.setattr(controller, "_build_and_start", lambda *a, **k: dispatched.append(a))
    controller.start()
    assert controller.state_manager.state != BotState.RUNNING
    assert dispatched == []
    assert any("No routines" in msg for msg in fake_logger.messages("WARN"))


def test_chain_advances_then_repeats_then_cleans_up(monkeypatch, controller):
    monkeypatch.setattr(bc.threading, "Thread", _ImmediateThread)
    calls = []
    cleaned = []
    monkeypatch.setattr(
        controller, "_build_and_start", lambda name, is_first=False: calls.append(name)
    )
    monkeypatch.setattr(controller, "_cleanup", lambda: cleaned.append(True))
    controller._chain = ["a", "b"]
    controller._chain_idx = 0
    controller._repeat = 2
    controller._play_count = 0

    controller._on_routine_done("a")
    assert calls == ["b"]
    controller._on_routine_done("b")
    assert calls == ["b", "a"]
    controller._on_routine_done("a")
    assert calls == ["b", "a", "b"]
    controller._on_routine_done("b")
    assert cleaned == [True]


def test_routine_abort_triggers_cleanup(monkeypatch, controller):
    from core.state_manager import BotState

    monkeypatch.setattr(bc.threading, "Thread", _ImmediateThread)
    cleaned = []
    monkeypatch.setattr(controller, "_cleanup", lambda: cleaned.append(True))
    restarted = []
    monkeypatch.setattr(controller, "_build_and_start", lambda *a, **k: restarted.append(a))
    controller._chain = ["a", "b"]
    controller._chain_idx = 0
    controller._on_routine_abort("a")
    assert controller.state_manager.state == BotState.STOPPED
    assert cleaned == [True]
    assert restarted == []


def test_cleanup_resets_to_idle(controller):
    from core.state_manager import BotState

    controller.state_manager.state = BotState.RUNNING
    controller._cleanup()
    assert controller.state_manager.state is BotState.IDLE


def test_browse_root_returns_drives(controller):
    result = controller.browse("")
    assert result["parent"] is None
    assert set(result) == {"dirs", "exes", "images", "parent"}


def test_browse_directory_classifies_entries(tmp_path, controller):
    (tmp_path / "sub").mkdir()
    (tmp_path / "app.exe").write_text("x", encoding="utf-8")
    (tmp_path / "img.PNG").write_text("x", encoding="utf-8")
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    result = controller.browse(str(tmp_path))
    assert result["dirs"] == ["sub"]
    assert result["exes"] == ["app.exe"]
    assert result["images"] == ["img.PNG"]
    assert result["parent"] == str(tmp_path.parent)


def test_autofill_writes_tab_name(tmp_plans, controller):
    import routines.plan_loader as pl

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


def test_autofill_skips_when_tab_name_present(tmp_plans, controller):
    import routines.plan_loader as pl

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


def test_get_routines_shape(tmp_plans, tmp_config, controller):
    data = controller.get_routines()
    assert {"routines", "labels", "current", "chain", "repeat"} <= set(data)
    assert data["labels"] == {}


def test_get_config_legacy_routine_key(tmp_config, controller):
    with open(bc.CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"routine": "legacy_plan"}, f)
    assert controller.get_config()["routines"] == ["legacy_plan"]


class FakeRecorder:
    def __init__(self, *, on_toggle=None, on_crop_request=None, on_next_step=None, focus_watcher=None):
        self.state = "IDLE"
        self.steps = []
        self.current_targets = []
        self._name = None
        self._toggle_cb = on_toggle
        self._crop_cb = on_crop_request
        self._next_cb = on_next_step
        self._focus_watcher = focus_watcher
        self._last_region = None

    def start(self, name=None):
        if self.state != "IDLE":
            return False
        self.state = "RECORDING"
        self._name = name
        self.steps = []
        self.current_targets = []
        return True

    def stop(self):
        self.next_step()
        if self.state == "IDLE":
            return None
        self.state = "IDLE"
        if not self.steps:
            return None
        return {"name": self._name or "recorded", "steps": list(self.steps)}

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
        if not self.current_targets:
            return None
        step = {"label": f"step {len(self.steps) + 1}", "targets": list(self.current_targets)}
        self.steps.append(step)
        self.current_targets = []
        return step

    def status(self):
        return {
            "state": self.state,
            "step_count": len(self.steps),
            "target_count": len(self.current_targets),
            "step_index": len(self.steps) + 1,
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


@pytest.fixture
def patched_controller(monkeypatch, tmp_config, fake_logger, fake_game_launcher, fake_focus_watcher, fake_screen_bot):
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


def test_start_recording_refused_while_bot_active(patched_controller):
    from core.state_manager import BotState

    patched_controller.state_manager.state = BotState.RUNNING
    result = patched_controller.start_recording()
    assert result["ok"] is False


def test_start_stop_recording_saves_plan(tmp_plans, tmp_config, patched_controller, fake_logger):
    with open(bc.CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"tab_name": "Game", "game_path": "C:/game.exe"}, f)

    result = patched_controller.start_recording(name="my flow")
    assert result["ok"] is True
    assert patched_controller._recorder.state == "RECORDING"
    assert patched_controller._overlay.calls == ["start", ("show_bar", 1, 0)]

    patched_controller._recorder.accept_target(["crop"], "left_click")
    stop_result = patched_controller.stop_recording()
    assert stop_result["ok"] is True
    assert stop_result["name"] == "my flow"
    assert "hide_crop" in patched_controller._overlay.calls
    assert "hide_bar" in patched_controller._overlay.calls
    saved = bc.get_plan("my flow")
    assert saved["config"]["tab_name"] is None
    assert saved["config"]["game_path"] is None


def test_stop_recording_with_no_steps_returns_error(patched_controller):
    patched_controller.start_recording()
    result = patched_controller.stop_recording()
    assert result["ok"] is False


def test_begin_crop_delegates(patched_controller):
    patched_controller.start_recording()
    result = patched_controller.begin_crop()
    assert result["ok"] is True
    assert patched_controller._overlay.calls[-1][0] == "show_crop"


def test_crop_confirm_forwards_offset(patched_controller):
    patched_controller.start_recording()
    patched_controller._on_crop_confirm(["crop"], "left_click", None, None, (5, -3))
    assert patched_controller._recorder.current_targets[-1]["offset"] == (5, -3)
    assert patched_controller._overlay.calls[-1] == ("set_counts", 1, 1)


def test_request_crop_delegates(patched_controller):
    patched_controller.start_recording()
    result = patched_controller.request_crop()
    assert result["ok"] is True
    assert patched_controller._overlay.calls[-1] == "request_crop"


def test_next_step_delegates(patched_controller):
    patched_controller.start_recording()
    patched_controller._recorder.accept_target(["crop"], "left_click")
    result = patched_controller.next_step()
    assert result["ok"] is True
    assert patched_controller._recorder.status()["step_count"] == 1
    assert patched_controller._overlay.calls[-1] == ("set_counts", 2, 0)


def test_next_step_without_targets_fails(patched_controller):
    patched_controller.start_recording()
    result = patched_controller.next_step()
    assert result["ok"] is False


def test_bot_start_stops_recording(monkeypatch, tmp_plans, patched_controller):
    monkeypatch.setattr(bc, "ROUTINES", {})
    patched_controller.start_recording()
    patched_controller._recorder.accept_target(["crop"], "left_click")
    patched_controller.start()
    assert patched_controller._recorder.state == "IDLE"
    assert bc.get_plan("recorded") is not None


def test_unique_plan_name_collision(tmp_plans, patched_controller):
    import routines.plan_loader as pl

    pl.save_plan("x", {"name": "X", "steps": [{"type": "click", "targets": [{"template": "a.png"}]}]})
    assert patched_controller._unique_plan_name("x") == "x (2)"
    pl.save_plan("x (2)", {"name": "X2", "steps": [{"type": "click", "targets": [{"template": "a.png"}]}]})
    assert patched_controller._unique_plan_name("x") == "x (3)"
