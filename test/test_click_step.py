from __future__ import annotations

import pytest

from core.match_result import MatchResult
from core.screen_bot import set_capture_origin, set_capture_scale
from engine.base import WAIT, DONE
from engine.click_action import ClickAction
from engine.click_step import ClickStep
from engine.target import Target


@pytest.fixture(autouse=True)
def _isolate_capture_globals():
    """Keep capture origin/scale deterministic across ClickStep point math tests."""
    set_capture_origin(0, 0)
    set_capture_scale(1.0, 1.0)
    yield
    set_capture_origin(0, 0)
    set_capture_scale(1.0, 1.0)


def _step(rules, **kwargs) -> ClickStep:
    """Build a bare step with no logger/delay for isolated rule testing."""
    step = ClickStep(rules, **kwargs)
    step.index = 0
    step.logger = None
    step.delay = 0.0
    return step


class TestClickStepRuleLifecycle:
    """Suite: how one step resolves rules — clicks, positive advances, non-advancing disappearance, terminal finish."""

    # --- Positive: a rule produces a decisive, advancing result -----------------

    @pytest.mark.positive
    def test_continue_action_advances_without_click(self, fake_screen, fake_logger):
        """A CONTINUE match advances immediately without clicking."""
        step = _step([Target("templates/x/A.png", action=ClickAction.CONTINUE)])
        step.logger = fake_logger
        fake_screen.visible = {"A.png"}
        assert step.tick("screen") == 1
        assert fake_screen.clicks == []

    @pytest.mark.positive
    def test_continue_honors_goto(self, fake_screen):
        """A CONTINUE match follows its explicit goto index."""
        step = _step([Target("templates/x/A.png", action=ClickAction.CONTINUE, goto=4)])
        fake_screen.visible = {"A.png"}
        assert step.tick("screen") == 4

    @pytest.mark.positive
    def test_scroll_action_advances_after_match(self, fake_screen):
        """A SCROLL match advances once the target is found."""
        step = _step([Target("templates/x/A.png", action=ClickAction.SCROLL, scrollValue=5)])
        fake_screen.visible = {"A.png"}
        assert step.tick("screen") == 1

    @pytest.mark.positive
    def test_click_then_gone_sets_lost(self, fake_screen):
        """An ordinary click waits; when the target later disappears the step reports lost."""
        step = _step([Target("templates/x/A.png")])
        fake_screen.visible = {"A.png"}
        assert step.tick("screen") == WAIT
        assert len(fake_screen.clicks) == 1
        fake_screen.visible = set()
        assert step.tick("screen") == WAIT
        assert step.lost is True

    @pytest.mark.positive
    def test_terminal_target_gone_returns_done(self, fake_screen):
        """A terminal target disappearing finishes the plan (DONE)."""
        target = Target("templates/x/A.png")
        target.terminal = True
        step = _step([target])
        fake_screen.visible = {"A.png"}
        assert step.tick("screen") == WAIT
        fake_screen.visible = set()
        assert step.tick("screen") == DONE

    @pytest.mark.positive
    def test_goto_step_if_not_found_returned_when_nothing_matched(self, fake_screen):
        """With no rule acting, goto_step_if_not_found supplies the jump index."""
        step = _step([Target("templates/x/A.png")], goto_step_if_not_found=5)
        step.index = 1
        assert step.tick("screen") == 5

    @pytest.mark.positive
    def test_stay_on_confirm_resets_blocker_without_advance(self, fake_screen):
        """A stay_on_confirm blocker is reset and dismissed without advancing."""
        target = Target("templates/x/A.png", stay_on_confirm=True)
        step = _step([target])
        fake_screen.visible = {"A.png"}
        step.tick("screen")
        assert target.click_count == 1
        fake_screen.visible = set()
        assert step.tick("screen") == WAIT
        assert target.click_count == 0

    @pytest.mark.positive
    def test_ready_delay_gates_click(self, fake_screen):
        """ready_delay blocks clicking until the clock passes the deadline."""
        step = _step([Target("templates/x/A.png")], ready_delay=1.0)
        step.reset()
        fake_screen.visible = {"A.png"}
        assert step.tick("screen") == WAIT
        assert fake_screen.clicks == []
        fake_screen.clock.now = 1.5
        assert step.tick("screen") == WAIT
        assert len(fake_screen.clicks) == 1

    @pytest.mark.positive
    def test_target_reappear_resets_lost_and_reclicks(self, fake_screen):
        """A reappearing target clears lost and is clicked again."""
        step = _step([Target("templates/x/A.png")])
        fake_screen.visible = {"A.png"}
        step.tick("screen")
        fake_screen.visible = set()
        step.tick("screen")
        assert step.lost is True
        fake_screen.visible = {"A.png"}
        step.tick("screen")
        assert step.lost is False
        assert len(fake_screen.clicks) == 2

    @pytest.mark.positive
    def test_callbacks_fire_on_click_and_confirm(self, fake_screen):
        """on_match fires on click; on_confirm fires on terminal disappearance."""
        hits = []
        target = Target(
            "templates/x/A.png",
            on_match=lambda: hits.append("match"),
            on_confirm=lambda: hits.append("confirm"),
        )
        target.terminal = True
        step = _step([target])
        fake_screen.visible = {"A.png"}
        step.tick("screen")
        fake_screen.visible = set()
        step.tick("screen")
        assert hits == ["match", "confirm"]

    @pytest.mark.positive
    def test_target_point_center_and_offsets(self):
        """Click point is the match center plus per-target offset."""
        match = MatchResult((10, 10), (20, 10), 0.9)
        assert ClickStep._target_point(match, Target("a.png")) == (20, 15)
        assert ClickStep._target_point(match, Target("a.png", offset_x=5)) == (25, 15)
        assert ClickStep._target_point(match, Target("a.png", offset_y=3)) == (20, 18)

    # --- Negative: rules that must NOT act or must swallow errors ----------------

    @pytest.mark.negative
    def test_absent_target_never_advances_and_stays_lost(self, fake_screen):
        """A target that never appears keeps returning WAIT and stays lost (no blind advance)."""
        step = _step([Target("templates/x/A.png")])
        step.index = 1
        fake_screen.visible = set()
        for _ in range(5):
            assert step.tick("screen") == WAIT
        assert step.lost is True

    @pytest.mark.negative
    def test_and_target_requires_all_templates(self, fake_screen):
        """An AND target does not click until every template is present."""
        step = _step([Target(["templates/x/A1.png", "templates/x/A2.png"])])
        fake_screen.visible = {"A1.png"}
        step.tick("screen")
        assert fake_screen.clicks == []
        fake_screen.visible = {"A1.png", "A2.png"}
        step.tick("screen")
        assert len(fake_screen.clicks) == 1

    @pytest.mark.negative
    def test_raising_callback_is_swallowed(self, fake_screen):
        """A raising on_match callback must not break the tick."""
        def boom():
            raise RuntimeError("boom")

        step = _step([Target("templates/x/A.png", on_match=boom)])
        fake_screen.visible = {"A.png"}
        assert step.tick("screen") == WAIT

    @pytest.mark.negative
    def test_failed_click_still_counts(self, fake_screen):
        """A click whose do_click returns False is still counted (documents current behavior)."""
        step = _step([Target("templates/x/A.png")])
        fake_screen.visible = {"A.png"}
        fake_screen.fail_next_click = True
        assert step.tick("screen") == WAIT
        assert len(fake_screen.clicks) == 1
        assert step._rules[0].click_count == 1

    # --- Edge: ordering, ready_delay state, scroll-until-match -------------------

    @pytest.mark.edge
    def test_ready_delay_wait_does_not_mark_lost(self, fake_screen):
        """Waiting for ready_delay is a deliberate WAIT, not a lost step."""
        step = _step([Target("templates/x/A.png")], ready_delay=1.0)
        step.reset()
        fake_screen.visible = {"A.png"}
        assert step.tick("screen") == WAIT
        assert step.lost is False

    @pytest.mark.edge
    def test_first_matching_rule_wins(self, fake_screen):
        """Rules are evaluated in order; the first match ends the tick."""
        first = Target("templates/x/A.png")
        second = Target("templates/x/B.png")
        step = _step([first, second])
        fake_screen.visible = {"A.png", "B.png"}
        step.tick("screen")
        assert fake_screen.clicks[0][0] == "A.png"
        assert second.click_count == 0

    @pytest.mark.edge
    def test_inconclusive_rule_falls_through_to_next(self, fake_screen):
        """An inconclusive rule lets a later rule act."""
        step = _step([Target("templates/x/A.png"), Target("templates/x/B.png")])
        fake_screen.visible = {"B.png"}
        step.tick("screen")
        assert fake_screen.clicks[0][0] == "B.png"

    @pytest.mark.edge
    def test_and_target_click_uses_first_template_point(self, fake_screen):
        """AND target clicks at the first template's match point plus offsets."""
        target = Target(["templates/x/A1.png", "templates/x/A2.png"], offset_x=100, offset_y=50)
        step = _step([target])
        fake_screen.visible = {"A1.png", "A2.png"}
        step.tick("screen")
        _, x, y = fake_screen.clicks[0]
        assert (x, y) == (115, 65)

    @pytest.mark.edge
    def test_scroll_until_match_scrolls_while_not_found(self, fake_screen):
        """With a scroll anchor, the step scrolls while the target is missing."""
        set_capture_origin(5, 5)
        target = Target("templates/x/A.png", scroll_point=(10, 20), scrollValue=-5)
        step = _step([target])
        fake_screen.visible = set()
        assert step.tick("screen") == WAIT
        assert fake_screen.clicks[0] == ("A.png", 15, 25)
        fake_screen.clicks.clear()
        assert step.tick("screen") == WAIT
        assert len(fake_screen.clicks) == 1

    @pytest.mark.edge
    def test_scroll_until_match_then_clicks_without_post_scroll(self, fake_screen):
        """Once the scroll target matches, it clicks without a post-scroll."""
        set_capture_origin(0, 0)
        target = Target("templates/x/A.png", scroll_point=(10, 20), scrollValue=-5)
        step = _step([target])
        fake_screen.visible = {"A.png"}
        assert step.tick("screen") == WAIT
        _, x, y = fake_screen.clicks[0]
        assert (x, y) == (15, 15)
