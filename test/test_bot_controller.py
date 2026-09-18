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


def test_preview_unavailable_without_screen_bot(
    fake_logger, fake_game_launcher, fake_focus_watcher
):
    from core.state_manager import StateManager

    controller = bc.BotController(
        fake_logger, StateManager(), fake_game_launcher, fake_focus_watcher, None
    )
    assert controller.set_preview(True) is False
    assert controller.get_preview() == {"enabled": False, "mode": "snapshot"}


def test_start_when_already_active_warns(controller, fake_logger):
    from core.state_manager import BotState

    controller.state_manager.state = BotState.RUNNING
    controller.start()
    assert any("already running" in msg for msg in fake_logger.messages("WARN"))


def test_start_with_empty_chain_warns(tmp_config, controller, fake_logger):
    with open(bc.CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"routines": []}, f)
    controller.start()
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
    monkeypatch.setattr(bc.threading, "Thread", _ImmediateThread)
    cleaned = []
    monkeypatch.setattr(controller, "_cleanup", lambda: cleaned.append(True))
    controller._on_routine_abort("x")
    assert cleaned == [True]


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


def test_get_routines_shape(tmp_config, controller):
    data = controller.get_routines()
    assert {"routines", "labels", "current", "chain", "repeat"} <= set(data)


def test_get_config_legacy_routine_key(tmp_config, controller):
    with open(bc.CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"routine": "legacy_plan"}, f)
    assert controller.get_config()["routines"] == ["legacy_plan"]
