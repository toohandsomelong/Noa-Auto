from __future__ import annotations

import pytest

from core.match_result import MatchResult
from engine.click_action import ClickAction
from engine.click_step import ClickStep
from engine.target import Target


class TestTargetNormalization:
    """Suite: Target template/scroll normalization, defaults, and validation."""

    @pytest.mark.positive
    def test_string_template_normalizes_to_list(self):
        """A string template becomes a one-element list; label defaults to the file name."""
        target = Target("templates/x/A.png")
        assert target.templates == ["templates/x/A.png"]
        assert target.template == "templates/x/A.png"
        assert target.label == "A.png"

    @pytest.mark.positive
    def test_list_template_keeps_order_and_uses_first_as_primary(self):
        """A list template keeps order; the first entry is the primary/click target."""
        target = Target(["templates/x/A.png", "templates/x/B.png"])
        assert target.templates == ["templates/x/A.png", "templates/x/B.png"]
        assert target.template == "templates/x/A.png"
        assert target.label == "A.png"

    @pytest.mark.positive
    def test_label_override_wins(self):
        """An explicit label overrides the file-name default."""
        assert Target("templates/x/A.png", label="Custom").label == "Custom"

    @pytest.mark.positive
    def test_defaults_produce_centered_left_click_without_scroll(self):
        """Defaults: centered left click, no scroll, inherit step threshold."""
        target = Target("templates/x/A.png")
        match = MatchResult(location=(10, 10), size=(20, 10), confidence=0.9)
        assert ClickStep._target_point(match, target) == (20, 15)
        assert target.action is ClickAction.LEFT_CLICK
        assert target.scrollValue == 0
        assert target.threshold is None
        assert target.grayscale is True
        assert target.click_count == 0

    @pytest.mark.edge
    def test_terminal_defaults_false(self):
        """terminal starts False; only the runner marks terminal targets."""
        assert Target("templates/x/A.png").terminal is False

    @pytest.mark.edge
    def test_scroll_point_accepts_tuple_and_list(self):
        """A scroll anchor normalizes to a tuple from tuple or list input."""
        assert Target("templates/x/A.png", scroll_point=(10, 20)).scroll_point == (10, 20)
        assert Target("templates/x/A.png", scroll_point=[30, 40]).scroll_point == (30, 40)

    @pytest.mark.negative
    @pytest.mark.parametrize("bad", [(1,), (1, 2, 3), ("a", "b"), [1.5, 2]])
    def test_scroll_point_rejects_bad_shapes(self, bad):
        """A malformed scroll anchor raises ValueError."""
        with pytest.raises(ValueError):
            Target("templates/x/A.png", scroll_point=bad)

    @pytest.mark.negative
    @pytest.mark.parametrize(
        "bad",
        ["", [], ["templates/x/A.png", ""], [1, 2], 123, None, {"a": 1}],
    )
    def test_invalid_template_raises(self, bad):
        """An empty/invalid template raises ValueError."""
        with pytest.raises(ValueError):
            Target(bad)

    @pytest.mark.edge
    def test_reset_clears_click_count(self):
        """reset() zeroes the click counter."""
        target = Target("templates/x/A.png")
        target.click_count = 4
        target.reset()
        assert target.click_count == 0
