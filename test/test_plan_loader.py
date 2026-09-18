from __future__ import annotations

import json

import pytest

from routines import ROUTINES, refresh_routines
from routines import plan_loader as pl
from routines.click_action import ClickAction


def _step(template: str = "templates/x/A.png") -> dict:
    return {"type": "click", "targets": [{"template": template}]}


def _plan(name: str = "P", **extra) -> dict:
    plan = {"name": name, "steps": [_step()]}
    plan.update(extra)
    return plan


def test_plan_path_valid_name():
    path = pl._plan_path("my plan")
    assert path.replace("\\", "/").endswith("plans/my plan.json")


@pytest.mark.parametrize("bad", ["", "a/b", "a\\b", ".", "..", "a\x00b", None, 5])
def test_plan_path_rejects_invalid(bad):
    with pytest.raises(ValueError):
        pl._plan_path(bad)


def test_save_then_get_roundtrip(tmp_plans):
    pl.save_plan("rt", _plan("RT", config={"delay": 0.5}))
    assert (tmp_plans / "rt.json").exists()
    data = pl.get_plan("rt")
    assert data["name"] == "RT"
    assert data["steps"][0]["type"] == "click"
    assert data["config"]["delay"] == 0.5


def test_saved_file_is_indented_json(tmp_plans):
    pl.save_plan("fmt", _plan())
    text = (tmp_plans / "fmt.json").read_text(encoding="utf-8")
    assert "\n  " in text


def test_get_missing_plan_returns_none(tmp_plans):
    assert pl.get_plan("does_not_exist") is None


def test_save_requires_non_empty_steps(tmp_plans):
    with pytest.raises(ValueError):
        pl.save_plan("a", {"steps": []})
    with pytest.raises(ValueError):
        pl.save_plan("b", {})


def test_save_rejects_unknown_step_type(tmp_plans):
    with pytest.raises(ValueError):
        pl.save_plan("bad", {"steps": [{"type": "wat", "targets": []}]})


def test_save_rejects_invalid_target(tmp_plans):
    with pytest.raises(ValueError):
        pl.save_plan("bad2", {"steps": [{"type": "click", "targets": [{"template": ""}]}]})


def test_save_rejects_invalid_interrupt_step(tmp_plans):
    with pytest.raises(ValueError):
        pl.save_plan(
            "bad3",
            {"steps": [_step()], "interrupt_steps": [{"type": "nope"}]},
        )


def test_save_preserves_interrupt_steps(tmp_plans):
    pl.save_plan(
        "with_int",
        {"name": "WI", "steps": [_step()], "interrupt_steps": [_step("templates/x/H.png")]},
    )
    assert len(pl.get_plan("with_int")["interrupt_steps"]) == 1


def test_delete_plan(tmp_plans):
    pl.save_plan("d", _plan())
    assert pl.delete_plan("d") is True
    assert pl.delete_plan("d") is False


def test_list_plan_names_sorted(tmp_plans):
    pl.save_plan("b", _plan())
    pl.save_plan("a", _plan())
    assert pl.list_plan_names() == ["a", "b"]


def test_list_plan_labels_fallback_and_corrupt(tmp_plans):
    pl.save_plan("a", _plan("Alpha"))
    (tmp_plans / "corrupt.json").write_text("{not valid json", encoding="utf-8")
    (tmp_plans / "noname.json").write_text(json.dumps({"steps": []}), encoding="utf-8")
    labels = pl.list_plan_labels()
    assert labels["a"] == "Alpha"
    assert "corrupt" not in labels
    assert labels["noname"] == "plan"


def test_build_config_filters_keys_and_strips_paths():
    cfg = pl._build_config(
        {
            "delay": 0.2,
            "game_path": "  C:/game.exe  ",
            "tab_name": "  Game  ",
            "unknown": 1,
            "timeout": None,
        }
    )
    assert cfg.delay == 0.2
    assert cfg.game_path == "C:/game.exe"
    assert cfg.tab_name == "Game"
    assert cfg.timeout is None


def test_build_config_blank_string_becomes_none():
    cfg = pl._build_config({"game_path": "   ", "tab_name": ""})
    assert cfg.game_path is None
    assert cfg.tab_name is None


def test_build_step_unknown_type_raises():
    with pytest.raises(ValueError):
        pl._build_step({"type": "nope"})


def test_target_kwargs_maps_all_fields():
    kwargs = pl._target_kwargs(
        {
            "template": ["templates/x/A.png", "templates/x/B.png"],
            "action": "right_click",
            "scrollValue": -100,
            "goto": 3,
            "offset_x": 1,
            "offset_y": 2,
            "stay_on_confirm": True,
            "threshold": 0.9,
            "grayscale": False,
            "label": "L",
        }
    )
    assert kwargs["template"] == ["templates/x/A.png", "templates/x/B.png"]
    assert kwargs["action"] is ClickAction.RIGHT_CLICK
    assert kwargs["scrollValue"] == -100
    assert kwargs["goto"] == 3
    assert kwargs["offset_x"] == 1
    assert kwargs["offset_y"] == 2
    assert kwargs["stay_on_confirm"] is True
    assert kwargs["threshold"] == 0.9
    assert kwargs["grayscale"] is False
    assert kwargs["label"] == "L"


def test_target_kwargs_drops_none_values():
    kwargs = pl._target_kwargs({"template": "a.png", "goto": None, "offset_x": None})
    assert "goto" not in kwargs
    assert "offset_x" not in kwargs


@pytest.mark.parametrize("bad", [None, "", [], ["a.png", ""], [1, 2], 5])
def test_target_kwargs_invalid_template_raises(bad):
    with pytest.raises(ValueError):
        pl._target_kwargs({"template": bad})


def test_build_routine_from_missing_plan_logs_and_returns_none(tmp_plans, fake_logger):
    # refresh so the registry reflects the empty tmp dir
    refresh_routines()
    assert pl.build_routine_from_plan("ghost", fake_logger) is None
    assert any("ghost" in msg for msg in fake_logger.messages("ERR"))


def test_build_routine_from_plan_builds_steps_and_interrupts(tmp_plans):
    pl.save_plan(
        "full",
        {
            "name": "Full",
            "steps": [_step()],
            "interrupt_steps": [_step("templates/x/H.png")],
            "config": {"delay": 0.1},
        },
    )
    routine = pl.build_routine_from_plan("full", None)
    assert routine is not None
    assert routine.name == "Full"
    assert len(routine.steps) == 1
    assert len(routine._interrupt_steps) == 1
    assert routine.config.delay == 0.1


def test_refresh_routines_registry(tmp_plans):
    pl.save_plan("reg", _plan())
    refresh_routines()
    assert "reg" in ROUTINES
    assert callable(ROUTINES["reg"])
