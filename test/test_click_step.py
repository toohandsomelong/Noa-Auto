from __future__ import annotations

import pytest

from core.match_result import MatchResult
from core.screen_bot import set_capture_origin, set_capture_scale
from routines.base import WAIT, RECOVER
from routines.click_action import ClickAction
from routines.click_step import ClickStep
from routines.target import Target


@pytest.fixture(autouse=True)
def _isolate_capture_globals():
    set_capture_origin(0, 0)
    set_capture_scale(1.0, 1.0)
    yield
    set_capture_origin(0, 0)
    set_capture_scale(1.0, 1.0)


def _step(rules, **kwargs) -> ClickStep:
    step = ClickStep(rules, **kwargs)
    step.index = 0
    step.logger = None
    step.delay = 0.0
    step.max_step_retry = 5
    return step


def test_continue_action_advances_without_click(fake_screen, fake_logger):
    step = _step([Target("templates/x/A.png", action=ClickAction.CONTINUE)])
    step.logger = fake_logger
    fake_screen.visible = {"A.png"}
    assert step.tick("screen") == 1
    assert fake_screen.clicks == []


def test_click_then_confirm_honors_goto(fake_screen):
    step = _step([Target("templates/x/A.png", goto=7)])
    fake_screen.visible = {"A.png"}
    assert step.tick("screen") == WAIT
    assert len(fake_screen.clicks) == 1
    fake_screen.visible = set()
    assert step.tick("screen") == 7


def test_ready_delay_gates_click(fake_screen):
    step = _step([Target("templates/x/A.png")], ready_delay=1.0)
    step.reset()
    fake_screen.visible = {"A.png"}
    assert step.tick("screen") == WAIT
    assert fake_screen.clicks == []
    fake_screen.clock.now = 1.5
    assert step.tick("screen") == WAIT
    assert len(fake_screen.clicks) == 1


def test_max_step_retry_returns_recover(fake_screen):
    step = _step([Target("templates/x/A.png")])
    step.max_step_retry = 2
    fake_screen.visible = {"A.png"}
    assert step.tick("screen") == WAIT
    assert step.tick("screen") == WAIT
    assert step.tick("screen") == RECOVER


def test_target_point_center_and_offsets():
    match = MatchResult((10, 10), (20, 10), 0.9)
    assert ClickStep._target_point(match, Target("a.png")) == (20, 15)
    assert ClickStep._target_point(match, Target("a.png", offset_x=5)) == (25, 15)
    assert ClickStep._target_point(match, Target("a.png", offset_y=3)) == (20, 18)


def test_callbacks_fire_on_click_and_confirm(fake_screen):
    hits = []
    target = Target(
        "templates/x/A.png",
        on_match=lambda: hits.append("match"),
        on_confirm=lambda: hits.append("confirm"),
    )
    step = _step([target])
    fake_screen.visible = {"A.png"}
    step.tick("screen")
    fake_screen.visible = set()
    step.tick("screen")
    assert hits == ["match", "confirm"]


def test_raising_callback_is_swallowed(fake_screen):
    def boom():
        raise RuntimeError("boom")

    step = _step([Target("templates/x/A.png", on_match=boom)])
    fake_screen.visible = {"A.png"}
    assert step.tick("screen") == WAIT


def test_and_target_requires_all_templates(fake_screen):
    step = _step([Target(["templates/x/A1.png", "templates/x/A2.png"])])
    fake_screen.visible = {"A1.png"}
    step.tick("screen")
    assert fake_screen.clicks == []
    fake_screen.visible = {"A1.png", "A2.png"}
    step.tick("screen")
    assert len(fake_screen.clicks) == 1


def test_scroll_until_match_scrolls_while_not_found(fake_screen):
    set_capture_origin(5, 5)
    target = Target("templates/x/A.png", scroll_point=(10, 20), scrollValue=-5)
    step = _step([target])
    fake_screen.visible = set()
    assert step.tick("screen") == WAIT
    assert len(fake_screen.clicks) == 1
    assert fake_screen.clicks[0] == ("A.png", 15, 25)
    fake_screen.clicks.clear()
    assert step.tick("screen") == WAIT
    assert len(fake_screen.clicks) == 1


def test_scroll_until_match_then_clicks_without_post_scroll(fake_screen):
    set_capture_origin(0, 0)
    target = Target("templates/x/A.png", scroll_point=(10, 20), scrollValue=-5)
    step = _step([target])
    fake_screen.visible = {"A.png"}
    assert step.tick("screen") == WAIT
    assert len(fake_screen.clicks) == 1
    _, x, y = fake_screen.clicks[0]
    assert (x, y) == (15, 15)

