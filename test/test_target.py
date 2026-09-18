from __future__ import annotations

import pytest

from routines.click_action import ClickAction
from routines.target import Target


def test_string_template_normalizes_to_list():
    target = Target("templates/x/A.png")
    assert target.templates == ["templates/x/A.png"]
    assert target.template == "templates/x/A.png"
    assert target.label == "A.png"


def test_list_template_keeps_order_and_uses_first_as_primary():
    target = Target(["templates/x/A.png", "templates/x/B.png"])
    assert target.templates == ["templates/x/A.png", "templates/x/B.png"]
    assert target.template == "templates/x/A.png"
    assert target.label == "A.png"


def test_label_override_wins():
    assert Target("templates/x/A.png", label="Custom").label == "Custom"


def test_defaults():
    target = Target("templates/x/A.png")
    assert target.action is ClickAction.LEFT_CLICK
    assert target.scrollValue == 0
    assert target.offset_x == 0
    assert target.offset_y == 0
    assert target.goto is None
    assert target.stay_on_confirm is False
    assert target.threshold is None
    assert target.grayscale is True
    assert target.click_count == 0


@pytest.mark.parametrize(
    "bad",
    ["", [], ["templates/x/A.png", ""], [1, 2], 123, None, {"a": 1}],
)
def test_invalid_template_raises(bad):
    with pytest.raises(ValueError):
        Target(bad)


def test_reset_clears_click_count():
    target = Target("templates/x/A.png")
    target.click_count = 4
    target.reset()
    assert target.click_count == 0
