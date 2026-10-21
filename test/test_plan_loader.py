from __future__ import annotations

import json

import pytest

from engine import PLANS, refresh_plans
from engine import plan_loader as pl
from engine.click_action import ClickAction


def _step(template: str = "templates/x/A.png") -> dict:
    """A minimal click step JSON descriptor."""
    return {"type": "click", "targets": [{"template": template}]}


def _plan(name: str = "P", **extra) -> dict:
    """A minimal plan JSON descriptor with optional extra top-level keys."""
    plan = {"name": name, "steps": [_step()]}
    plan.update(extra)
    return plan


class TestPlanJSONLoading:
    """Suite: tolerant plan JSON loading, strict saving, and path-safety rules."""

    @pytest.mark.positive
    def test_plan_path_valid_name(self):
        """A plain name resolves to plans/<name>.json."""
        path = pl._plan_path("my plan")
        assert path.replace("\\", "/").endswith("plans/my plan.json")

    @pytest.mark.negative
    @pytest.mark.parametrize("bad", ["", "a/b", "a\\b", ".", "..", "a\x00b", None, 5])
    def test_plan_path_rejects_invalid(self, bad):
        """Traversal, separators, dot names, NUL, and non-strings are rejected."""
        with pytest.raises(ValueError):
            pl._plan_path(bad)

    @pytest.mark.positive
    def test_save_then_get_roundtrip(self, tmp_plans):
        """Saving then loading preserves name, steps, and config."""
        pl.save_plan("rt", _plan("RT", config={"delay": 0.5}))
        assert (tmp_plans / "rt.json").exists()
        data = pl.get_plan("rt")
        assert data["name"] == "RT"
        assert data["steps"][0]["type"] == "click"
        assert data["config"]["delay"] == 0.5

    @pytest.mark.edge
    def test_saved_file_is_indented_json(self, tmp_plans):
        """Saved plans are written as indented JSON for manual editing."""
        pl.save_plan("fmt", _plan())
        text = (tmp_plans / "fmt.json").read_text(encoding="utf-8")
        assert "\n  " in text

    @pytest.mark.negative
    def test_get_missing_plan_returns_none(self, tmp_plans):
        """A missing plan returns None rather than raising."""
        assert pl.get_plan("does_not_exist") is None

    @pytest.mark.negative
    def test_save_requires_non_empty_steps(self, tmp_plans):
        """Saving a plan with no steps raises ValueError."""
        with pytest.raises(ValueError):
            pl.save_plan("a", {"steps": []})
        with pytest.raises(ValueError):
            pl.save_plan("b", {})

    @pytest.mark.negative
    def test_save_rejects_unknown_step_type(self, tmp_plans):
        """An unknown step type is rejected at save time."""
        with pytest.raises(ValueError):
            pl.save_plan("bad", {"steps": [{"type": "wat", "targets": []}]})

    @pytest.mark.negative
    def test_save_rejects_invalid_target(self, tmp_plans):
        """An invalid target (empty template) is rejected at save time."""
        with pytest.raises(ValueError):
            pl.save_plan("bad2", {"steps": [{"type": "click", "targets": [{"template": ""}]}]})

    @pytest.mark.negative
    def test_save_rejects_invalid_interrupt_step(self, tmp_plans):
        """An invalid interrupt step is rejected at save time."""
        with pytest.raises(ValueError):
            pl.save_plan(
                "bad3",
                {"steps": [_step()], "interrupt_steps": [{"type": "nope"}]},
            )

    @pytest.mark.positive
    def test_save_preserves_interrupt_steps(self, tmp_plans):
        """Valid interrupt steps survive the save/load roundtrip."""
        pl.save_plan(
            "with_int",
            {"name": "WI", "steps": [_step()], "interrupt_steps": [_step("templates/x/H.png")]},
        )
        assert len(pl.get_plan("with_int")["interrupt_steps"]) == 1

    @pytest.mark.positive
    def test_delete_plan(self, tmp_plans):
        """Deleting returns True once, then False when already gone."""
        pl.save_plan("d", _plan())
        assert pl.delete_plan("d") is True
        assert pl.delete_plan("d") is False

    @pytest.mark.positive
    def test_list_plan_names_sorted(self, tmp_plans):
        """Discovered plan names are sorted."""
        pl.save_plan("b", _plan())
        pl.save_plan("a", _plan())
        assert pl.list_plan_names() == ["a", "b"]

    @pytest.mark.edge
    def test_list_plan_labels_fallback_and_corrupt(self, tmp_plans):
        """Labels use the plan name; corrupt files are skipped, missing names fall back."""
        pl.save_plan("a", _plan("Alpha"))
        (tmp_plans / "corrupt.json").write_text("{not valid json", encoding="utf-8")
        (tmp_plans / "noname.json").write_text(json.dumps({"steps": []}), encoding="utf-8")
        labels = pl.list_plan_labels()
        assert labels["a"] == "Alpha"
        assert "corrupt" not in labels
        assert labels["noname"] == "plan"

    @pytest.mark.positive
    def test_build_config_filters_keys_and_strips_paths(self):
        """Only known keys are used; paths are stripped; legacy knobs are ignored."""
        cfg = pl._build_config(
            {
                "delay": 0.2,
                "game_path": "  C:/game.exe  ",
                "tab_name": "  Game  ",
                "unknown": 1,
                "timeout": None,
                "max_step_retry": None,
                "resync_timeout": None,
            }
        )
        assert cfg.delay == 0.2
        assert cfg.game_path == "C:/game.exe"
        assert cfg.tab_name == "Game"

    @pytest.mark.edge
    def test_build_config_blank_string_becomes_none(self):
        """Blank game_path/tab_name become None (disabling attach/launch)."""
        cfg = pl._build_config({"game_path": "   ", "tab_name": ""})
        assert cfg.game_path is None
        assert cfg.tab_name is None

    @pytest.mark.negative
    def test_build_step_unknown_type_raises(self):
        """Unknown step types raise during step construction."""
        with pytest.raises(ValueError):
            pl._build_step({"type": "nope"})

    @pytest.mark.positive
    def test_target_kwargs_maps_all_fields(self):
        """All supported target fields map into Target kwargs."""
        kwargs = pl._target_kwargs(
            {
                "template": ["templates/x/A.png", "templates/x/B.png"],
                "action": "right_click",
                "scrollValue": -100,
                "scroll_point": [10, 20],
                "goto": 3,
                "offset_x": 1,
                "offset_y": 2,
                "stay_on_confirm": True,
                "threshold": 0.9,
                "grayscale": False,
                "label": "L",
            }
        )
        assert kwargs == {
            "template": ["templates/x/A.png", "templates/x/B.png"],
            "action": ClickAction.RIGHT_CLICK,
            "scrollValue": -100,
            "scroll_point": [10, 20],
            "goto": 3,
            "offset_x": 1,
            "offset_y": 2,
            "stay_on_confirm": True,
            "threshold": 0.9,
            "grayscale": False,
            "label": "L",
        }

    @pytest.mark.edge
    def test_target_kwargs_drops_none_values(self):
        """None-valued target fields are omitted from kwargs."""
        kwargs = pl._target_kwargs({"template": "a.png", "goto": None, "offset_x": None})
        assert "goto" not in kwargs
        assert "offset_x" not in kwargs

    @pytest.mark.negative
    @pytest.mark.parametrize("bad", [None, "", [], ["a.png", ""], [1, 2], 5])
    def test_target_kwargs_invalid_template_raises(self, bad):
        """An empty/invalid template raises during kwarg mapping."""
        with pytest.raises(ValueError):
            pl._target_kwargs({"template": bad})

    @pytest.mark.negative
    def test_build_runner_from_missing_plan_logs_and_returns_none(self, tmp_plans, fake_logger):
        """A missing plan logs an error and yields no runner."""
        refresh_plans()
        assert pl.build_plan_runner("ghost", fake_logger) is None
        assert any("ghost" in msg for msg in fake_logger.messages("ERR"))

    @pytest.mark.positive
    def test_build_plan_runner_builds_steps_and_interrupts(self, tmp_plans):
        """A full plan builds steps, interrupts, and config."""
        pl.save_plan(
            "full",
            {
                "name": "Full",
                "steps": [_step()],
                "interrupt_steps": [_step("templates/x/H.png")],
                "config": {"delay": 0.1},
            },
        )
        plan = pl.build_plan_runner("full", None)
        assert plan is not None
        assert plan.name == "Full"
        assert plan.plan_key == "full"
        assert len(plan.steps) == 1
        assert len(plan._interrupt_steps) == 1
        assert plan.config.delay == 0.1

    @pytest.mark.positive
    def test_build_runner_marks_terminal_targets(self, tmp_plans):
        """The loader-built runner marks the final step's target terminal."""
        pl.save_plan("term", {"name": "T", "steps": [_step("templates/x/A.png"), _step("templates/x/B.png")]})
        plan = pl.build_plan_runner("term", None)
        assert plan.steps[0]._rules[0].terminal is False
        assert plan.steps[1]._rules[0].terminal is True

    @pytest.mark.edge
    def test_non_dict_config_is_dropped(self, tmp_plans):
        """A falsy/non-dict config is silently dropped on save."""
        pl.save_plan("weird", {"name": "W", "steps": [_step()], "config": []})
        assert "config" not in pl.get_plan("weird")

    @pytest.mark.edge
    def test_non_list_interrupt_steps_ignored(self, tmp_plans):
        """A non-list interrupt_steps value skips validation but is preserved verbatim."""
        pl.save_plan("noint", {"name": "N", "steps": [_step()], "interrupt_steps": "nope"})
        assert pl.get_plan("noint")["interrupt_steps"] == "nope"

    @pytest.mark.positive
    def test_refresh_plans_registry(self, tmp_plans):
        """refresh_plans repopulates the registry with builder callables."""
        pl.save_plan("reg", _plan())
        refresh_plans()
        assert "reg" in PLANS
        assert callable(PLANS["reg"])
