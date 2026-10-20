from __future__ import annotations

import numpy as np
import pytest

from engine.click_action import ClickAction
from engine.click_step import ClickStep
from engine.config import PlanConfig
from engine.plan_runner import (
    BACKWARD_PENALTY,
    FORWARD_BONUS,
    SEARCH_DELAY,
    W_DIST,
    PlanRunner,
    anchor_score,
)
from engine.target import Target


def _runner(steps, interrupts=None, *, logger=None, delay=0.0):
    """Build a plan runner with deterministic config for runner-level tests."""
    return PlanRunner(
        "test",
        steps,
        logger=logger,
        config=PlanConfig(delay=delay),
        interrupt_steps=interrupts,
    )


def _tick(runner, screen, times=1):
    """Drive the runner for a fixed number of frames."""
    for _ in range(times):
        runner.tick(screen)


def _expire_search_delay(fake_screen):
    """Advance the fake clock past SEARCH_DELAY so the general scan is allowed."""
    fake_screen.clock.now += SEARCH_DELAY + 0.1


def _frame(value: int = 0):
    """A uniform frame for real stability-gate tests (matches are driven separately)."""
    return np.full((45, 80, 3), value, dtype=np.uint8)


def _tick_frames(runner, frames):
    for frame in frames:
        runner.tick(frame)


class TestPlanRunnerConstruction:
    """Suite: PlanRunner init wiring, terminal-target marking, and done/current_step bookkeeping."""

    @pytest.mark.positive
    def test_steps_get_index_logger_delay(self, fake_logger):
        """Every step receives its index, the runner logger, and the plan delay."""
        steps = [ClickStep([Target("templates/x/A.png")]), ClickStep([Target("templates/x/B.png")])]
        _runner(steps, logger=fake_logger, delay=0.3)
        assert [s.index for s in steps] == [0, 1]
        assert all(s.logger is fake_logger for s in steps)
        assert all(s.delay == 0.3 for s in steps)

    @pytest.mark.positive
    def test_interrupts_get_index_logger_delay(self, fake_logger):
        """Interrupt steps receive the same index/logger/delay wiring."""
        interrupt = ClickStep([Target("templates/x/H.png")])
        _runner([ClickStep([Target("templates/x/A.png")])], interrupts=[interrupt], logger=fake_logger, delay=0.2)
        assert interrupt.index == 0
        assert interrupt.logger is fake_logger
        assert interrupt.delay == 0.2

    @pytest.mark.positive
    def test_terminal_marked_for_last_natural_step(self, fake_screen):
        """The final step's natural successor is out of range, so its target is terminal."""
        steps = [ClickStep([Target("templates/x/A.png")]), ClickStep([Target("templates/x/B.png")])]
        _runner(steps)
        assert steps[0]._rules[0].terminal is False
        assert steps[1]._rules[0].terminal is True

    @pytest.mark.edge
    def test_terminal_marked_for_explicit_goto_beyond_end(self, fake_screen):
        """An explicit goto past the last step also marks the target terminal."""
        steps = [ClickStep([Target("templates/x/A.png", goto=5)]), ClickStep([Target("templates/x/B.png")])]
        _runner(steps)
        assert steps[0]._rules[0].terminal is True

    @pytest.mark.edge
    def test_goto_within_range_is_not_terminal(self):
        """A goto that lands on a real step is not terminal."""
        steps = [
            ClickStep([Target("templates/x/A.png", goto=2)]),
            ClickStep([Target("templates/x/B.png")]),
            ClickStep([Target("templates/x/C.png")]),
        ]
        _runner(steps)
        assert steps[0]._rules[0].terminal is False

    @pytest.mark.edge
    def test_goto_step_if_not_found_is_not_terminal(self):
        """goto_step_if_not_found never makes a target terminal."""
        steps = [
            ClickStep([Target("templates/x/A.png")], goto_step_if_not_found=9),
            ClickStep([Target("templates/x/B.png")]),
        ]
        _runner(steps)
        assert steps[0]._rules[0].terminal is False

    @pytest.mark.edge
    def test_empty_plan_is_done_on_first_tick(self):
        """A plan with zero steps finishes on its first tick."""
        runner = _runner([])
        runner.tick("screen")
        assert runner.done is True

    @pytest.mark.edge
    def test_current_step_none_after_done(self, fake_screen):
        """current_step() returns None once the plan is done."""
        runner = _runner([ClickStep([Target("templates/x/A.png")])])
        fake_screen.visible = {"A.png"}
        runner.tick("screen")
        fake_screen.visible = set()
        runner.tick("screen")
        assert runner.done is True
        assert runner.current_step() is None

    @pytest.mark.edge
    def test_targets_desc_uses_labels(self):
        """The step description falls back to labels (or templates) in rule order."""
        step = ClickStep([Target("templates/x/A.png", label="Alpha"), Target("templates/x/B.png")])
        runner = _runner([step])
        assert runner._targets_desc(step) == "Alpha, B.png"


class TestInterruptBlockers:
    """Suite: global interrupt steps tick before the plan and never move the step index."""

    @pytest.mark.positive
    def test_interrupt_short_circuits_and_does_not_advance_plan(self, fake_screen):
        """A visible blocker is clicked while the current step is not touched."""
        interrupt = ClickStep([Target("templates/x/HALT.png")], label="halt")
        runner = _runner([ClickStep([Target("templates/x/A.png")])], interrupts=[interrupt])
        fake_screen.visible = {"HALT.png", "A.png"}
        runner.tick("screen")
        assert fake_screen.clicks == [("HALT.png", 15, 15)]
        assert runner._index == 0
        assert runner.steps[0]._rules[0].click_count == 0

    @pytest.mark.positive
    def test_interrupt_priority_is_list_order(self, fake_screen):
        """The first visible interrupt in list order wins."""
        first = ClickStep([Target("templates/x/one.png")], label="one")
        second = ClickStep([Target("templates/x/two.png")], label="two")
        runner = _runner([ClickStep([Target("templates/x/A.png")])], interrupts=[first, second])
        fake_screen.visible = {"one.png", "two.png"}
        runner.tick("screen")
        assert fake_screen.clicks[0][0] == "one.png"
        assert second._rules[0].click_count == 0

    @pytest.mark.positive
    def test_interrupt_goto_ignored(self, fake_screen):
        """A blocker's goto/advance result is ignored; the index never changes."""
        interrupt = ClickStep([Target("templates/x/HALT.png", goto=5)])
        runner = _runner([ClickStep([Target("templates/x/A.png")])], interrupts=[interrupt])
        fake_screen.visible = {"HALT.png"}
        runner.tick("screen")
        assert runner._index == 0

    @pytest.mark.edge
    def test_interrupt_overlap_guard_single(self, fake_screen):
        """An interrupt sharing a template with the current step is skipped."""
        interrupt = ClickStep([Target("templates/x/A.png")], label="guard")
        runner = _runner([ClickStep([Target("templates/x/A.png")])], interrupts=[interrupt])
        fake_screen.visible = {"A.png"}
        runner.tick("screen")
        assert runner.steps[0]._rules[0].click_count == 1
        assert interrupt._rules[0].click_count == 0

    @pytest.mark.edge
    def test_interrupt_overlap_guard_multi(self, fake_screen):
        """A multi-template interrupt sharing any template is skipped."""
        interrupt = ClickStep([Target(["templates/x/A.png", "templates/x/Z.png"])], label="guard")
        runner = _runner([ClickStep([Target("templates/x/A.png")])], interrupts=[interrupt])
        fake_screen.visible = {"A.png", "Z.png"}
        runner.tick("screen")
        assert runner.steps[0]._rules[0].click_count == 1
        assert interrupt._rules[0].click_count == 0

    @pytest.mark.edge
    def test_interrupt_click_state_reset_after_clear(self, fake_screen):
        """On the blocked->clear transition the interrupt's click counters are reset."""
        interrupt = ClickStep([Target("templates/x/HALT.png")], label="halt")
        runner = _runner([ClickStep([Target("templates/x/A.png")])], interrupts=[interrupt])
        fake_screen.visible = {"HALT.png", "A.png"}
        runner.tick("screen")
        assert interrupt._rules[0].click_count == 1
        fake_screen.visible = {"A.png"}
        runner.tick("screen")
        assert interrupt._rules[0].click_count == 0


class TestSelfAnchoring:
    """Suite: the runner re-locates itself from positive screen evidence when the current step is lost."""

    @pytest.mark.positive
    def test_anchor_to_next_step_after_two_frames(self, fake_screen):
        """The next step visible for two consecutive frames re-anchors the runner."""
        steps = [ClickStep([Target("templates/x/A.png")]), ClickStep([Target("templates/x/B.png")])]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick("screen")
        assert fake_screen.clicks == [("A.png", 15, 15)]

        fake_screen.visible = {"B.png"}
        _tick(runner, "screen", 2)
        assert runner._index == 1
        runner.tick("screen")
        assert steps[1]._rules[0].click_count == 1

    @pytest.mark.positive
    def test_previous_step_re_anchor(self, fake_screen):
        """A screen showing an earlier step re-anchors the runner back to it."""
        steps = [ClickStep([Target("templates/x/A.png")]), ClickStep([Target("templates/x/B.png")])]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick("screen")
        fake_screen.visible = {"B.png"}
        _tick(runner, "screen", 2)
        assert runner._index == 1

        # Recovering to an earlier step is a general scan: wait out SEARCH_DELAY first.
        fake_screen.visible = {"A.png"}
        _tick(runner, "screen", 2)
        assert runner._index == 1
        _expire_search_delay(fake_screen)
        _tick(runner, "screen", 2)
        assert runner._index == 0
        assert steps[0]._rules[0].click_count == 0  # reset on re-enter

    @pytest.mark.positive
    def test_loading_waits_then_anchors(self, fake_screen):
        """With nothing known on screen the runner waits; it anchors once the next step appears."""
        steps = [ClickStep([Target("templates/x/A.png")]), ClickStep([Target("templates/x/B.png")])]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick("screen")

        fake_screen.visible = set()
        _tick(runner, "screen", 5)
        assert runner._index == 0

        fake_screen.visible = {"B.png"}
        _tick(runner, "screen", 2)
        assert runner._index == 1

    @pytest.mark.negative
    def test_single_frame_flicker_does_not_anchor(self, fake_screen):
        """A one-frame sighting of another step is below the debounce and must not commit."""
        steps = [ClickStep([Target("templates/x/A.png")]), ClickStep([Target("templates/x/B.png")])]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick("screen")

        fake_screen.visible = set()
        runner.tick("screen")
        assert runner._index == 0
        assert steps[0].lost is True

        fake_screen.visible = {"B.png"}
        runner.tick("screen")
        assert runner._index == 0

        fake_screen.visible = set()
        runner.tick("screen")
        assert runner._index == 0

    @pytest.mark.negative
    def test_anchor_only_runs_when_current_step_is_lost(self, fake_screen):
        """While the current step can act, another visible step never steals the anchor."""
        steps = [
            ClickStep([Target("templates/x/A.png")]),
            ClickStep([Target("templates/x/B.png")]),
        ]
        runner = _runner(steps)
        fake_screen.visible = {"A.png", "B.png"}
        _tick(runner, "screen", 3)
        assert runner._index == 0
        assert steps[1]._rules[0].click_count == 0

    @pytest.mark.edge
    def test_candidate_change_resets_debounce(self, fake_screen):
        """Switching which candidate is visible restarts the two-frame debounce."""
        steps = [
            ClickStep([Target("templates/x/A.png")]),
            ClickStep([Target("templates/x/B.png")]),
            ClickStep([Target("templates/x/C.png")]),
        ]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick("screen")

        fake_screen.visible = {"B.png"}
        runner.tick("screen")  # candidate 1, 1/2
        fake_screen.visible = {"C.png"}
        runner.tick("screen")  # candidate 2, 1/2 (reset)
        assert runner._index == 0
        fake_screen.visible = {"B.png"}
        runner.tick("screen")  # candidate 1, 1/2 again
        assert runner._index == 0
        runner.tick("screen")  # candidate 1, 2/2 -> commit
        assert runner._index == 1

    @pytest.mark.edge
    def test_nothing_visible_resets_debounce(self, fake_screen):
        """A frame with no candidate visible resets the debounce counter."""
        steps = [ClickStep([Target("templates/x/A.png")]), ClickStep([Target("templates/x/B.png")])]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick("screen")

        fake_screen.visible = {"B.png"}
        runner.tick("screen")  # 1/2
        fake_screen.visible = set()
        runner.tick("screen")  # reset
        fake_screen.visible = {"B.png"}
        runner.tick("screen")  # 1/2 again
        assert runner._index == 0

    @pytest.mark.edge
    def test_goto_priority_used_by_anchor(self, fake_screen):
        """An explicit goto successor is preferred by the anchor scan."""
        steps = [
            ClickStep([Target("templates/x/A.png", goto=2)]),
            ClickStep([Target("templates/x/B.png")]),
            ClickStep([Target("templates/x/C.png")]),
        ]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick("screen")

        fake_screen.visible = {"C.png"}
        _tick(runner, "screen", 2)
        assert runner._index == 2

    @pytest.mark.edge
    def test_anchor_score_forward_beats_backward(self):
        """At equal distance a forward candidate scores below a backward one."""
        assert anchor_score(3, 4) < anchor_score(3, 2)
        assert anchor_score(3, 4) == anchor_score(3, 3) + W_DIST + FORWARD_BONUS

    @pytest.mark.edge
    def test_anchor_score_backward_costs_extra(self):
        """A backward candidate adds BACKWARD_PENALTY on top of its distance."""
        assert anchor_score(3, 2) == 1 + BACKWARD_PENALTY

    @pytest.mark.edge
    def test_anchor_score_confidence_and_evidence_disabled(self):
        """With W_CONF/W_EV at 0 the match strength terms do not change the score."""
        assert anchor_score(0, 2, confidence=1.0, matched_targets=5) == anchor_score(0, 2)

    @pytest.mark.edge
    def test_match_cache_dedupes_within_tick_and_clears(self, fake_screen):
        """A template shared by two interrupts is matched once per tick, then re-matched next tick."""
        interrupt_a = ClickStep([Target("templates/x/S.png")])
        interrupt_b = ClickStep([Target("templates/x/S.png")])
        runner = _runner(
            [ClickStep([Target("templates/x/A.png")])],
            interrupts=[interrupt_a, interrupt_b],
        )
        fake_screen.visible = set()
        fake_screen.match_calls.clear()
        runner.tick("screen")
        runner.tick("screen")
        s_calls = [c for c in fake_screen.match_calls if c[0] == "templates/x/S.png"]
        assert len(s_calls) == 2  # one per tick, not two per tick

class TestMultiTargetContinuation:
    """Suite: a multi-target step keeps acting on its remaining targets instead of
    going lost and waiting for the anchor hunt."""

    @pytest.mark.positive
    def test_later_target_acts_without_search_delay(self, fake_screen):
        """After the clicked target disappears, a later visible target is clicked immediately."""
        steps = [
            ClickStep([Target("templates/x/A.png"), Target("templates/x/B.png")]),
            ClickStep([Target("templates/x/C.png")]),
        ]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick("screen")  # click A
        assert fake_screen.clicks == [("A.png", 15, 15)]

        fake_screen.visible = {"B.png"}
        fake_screen.clock.now += 0.1  # far less than SEARCH_DELAY
        runner.tick("screen")
        assert fake_screen.clicks[-1][0] == "B.png"
        assert runner._index == 0

    @pytest.mark.positive
    def test_multi_target_then_advances_to_expected_next_step(self, fake_screen):
        """After the later target is clicked, the runner advances to the natural next step."""
        steps = [
            ClickStep([Target("templates/x/A.png"), Target("templates/x/B.png")]),
            ClickStep([Target("templates/x/C.png")]),
        ]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick("screen")
        fake_screen.visible = {"B.png"}
        runner.tick("screen")  # click B
        fake_screen.visible = {"C.png"}
        _tick(runner, "screen", 2)  # B gone, C visible for two frames
        assert runner._index == 1


class TestExpectedStepFallback:
    """Suite: an expected next step that is not visible can fall back via its
    goto_step_if_not_found immediately, without waiting SEARCH_DELAY."""

    @pytest.mark.positive
    def test_expected_step_missing_uses_goto_step_if_not_found(self, fake_screen):
        """After a click, if the expected next step is absent, use its fallback."""
        steps = [
            ClickStep([Target("templates/x/A.png")]),
            ClickStep([Target("templates/x/B.png")], goto_step_if_not_found=3),
            ClickStep([Target("templates/x/C.png")]),
            ClickStep([Target("templates/x/D.png")]),
        ]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick("screen")  # click A

        fake_screen.visible = set()  # B (expected next) is absent
        fake_screen.clock.now += 0.1  # far less than SEARCH_DELAY
        runner.tick("screen")
        assert runner._index == 3

    @pytest.mark.positive
    def test_expected_step_visible_does_not_use_fallback(self, fake_screen):
        """When the expected next step is visible, it anchors normally."""
        steps = [
            ClickStep([Target("templates/x/A.png")]),
            ClickStep([Target("templates/x/B.png")], goto_step_if_not_found=3),
            ClickStep([Target("templates/x/C.png")]),
            ClickStep([Target("templates/x/D.png")]),
        ]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick("screen")

        fake_screen.visible = {"B.png"}
        runner.tick("screen")  # candidate B, 1/2
        assert runner._index == 0
        runner.tick("screen")  # candidate B, 2/2 -> anchor
        assert runner._index == 1

    @pytest.mark.negative
    def test_fallback_without_click_does_not_jump(self, fake_screen):
        """A step lost without a click must not use the next step's fallback."""
        steps = [
            ClickStep([Target("templates/x/A.png")]),
            ClickStep([Target("templates/x/B.png")], goto_step_if_not_found=2),
            ClickStep([Target("templates/x/C.png")]),
        ]
        runner = _runner(steps)
        fake_screen.visible = set()
        fake_screen.clock.now += 0.1
        runner.tick("screen")
        assert runner._index == 0

    @pytest.mark.edge
    def test_fallback_out_of_range_is_ignored(self, fake_screen):
        """An invalid goto_step_if_not_found falls through to the normal wait."""
        steps = [
            ClickStep([Target("templates/x/A.png")]),
            ClickStep([Target("templates/x/B.png")], goto_step_if_not_found=99),
            ClickStep([Target("templates/x/C.png")]),
        ]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick("screen")

        fake_screen.visible = set()
        fake_screen.clock.now += 0.1
        runner.tick("screen")
        assert runner._index == 0


class TestTerminalAnchors:
    """Suite: terminal steps and anchor restrictions."""

    @pytest.mark.positive
    def test_terminal_step_is_not_a_seek_anchor(self, fake_screen):
        """A visible terminal step (e.g. a persistent Home button) never anchors a lost step."""
        steps = [
            ClickStep([Target("templates/x/A.png")]),
            ClickStep([Target("templates/x/B.png")]),
            ClickStep([Target("templates/x/home.png")]),
        ]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick("screen")  # click A

        fake_screen.visible = {"home.png"}  # only the terminal step matches
        _tick(runner, "screen", 5)
        assert runner._index == 0

    @pytest.mark.positive
    def test_nearest_matching_step_wins(self, fake_screen):
        """After SEARCH_DELAY, the general scan picks the nearest matching step."""
        steps = [ClickStep([Target(f"templates/x/{n}.png")]) for n in "ABCDEFG"]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick("screen")  # click A at step 0

        fake_screen.visible = {"C.png", "E.png"}  # steps 2 and 4 (neither terminal)
        _tick(runner, "screen", 3)
        assert runner._index == 0  # held back while waiting for the next step

        _expire_search_delay(fake_screen)
        _tick(runner, "screen", 2)
        assert runner._index == 2

    @pytest.mark.positive
    def test_confirming_anchors_to_expected_next_with_shared_template(self, fake_screen):
        """The expected next step can anchor even when it shares a template with a later step."""
        steps = [
            ClickStep([Target("templates/x/A.png")]),
            ClickStep([Target("templates/x/shared.png")]),
            ClickStep([Target("templates/x/shared.png"), Target("templates/x/C.png")]),
        ]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick("screen")  # click A

        fake_screen.visible = {"shared.png"}
        _tick(runner, "screen", 2)
        assert runner._index == 1

    @pytest.mark.positive
    def test_forward_match_beats_backward_recovery(self, fake_screen):
        """When both a forward and a backward step match, the forward one wins."""
        steps = [
            ClickStep([Target("templates/x/shared.png")]),  # 0 (earlier)
            ClickStep([Target("templates/x/A.png")]),  # 1 (origin)
            ClickStep([Target(["templates/x/shared.png", "templates/x/B.png"])]),  # 2
            ClickStep([Target("templates/x/C.png")]),  # 3 (forward, non-terminal)
            ClickStep([Target("templates/x/D.png")]),  # 4
            ClickStep([Target("templates/x/E.png")]),  # 5
        ]
        runner = _runner(steps)
        runner._advance_to(1)  # start at step 1
        fake_screen.visible = {"A.png"}
        runner.tick("screen")  # click A at step 1

        fake_screen.visible = {"shared.png", "C.png"}  # step 0 (shared) and step 3
        _tick(runner, "screen", 2)  # lost_since set; still waiting
        assert runner._index == 1
        _expire_search_delay(fake_screen)
        _tick(runner, "screen", 2)
        assert runner._index == 3

    @pytest.mark.positive
    def test_backward_recovery_when_only_earlier_matches(self, fake_screen):
        """A lost runner still recovers to an earlier step when it is the only match."""
        steps = [
            ClickStep([Target("templates/x/A.png")]),
            ClickStep([Target("templates/x/B.png")]),
            ClickStep([Target("templates/x/C.png")]),
        ]
        runner = _runner(steps)
        runner._advance_to(2)
        fake_screen.visible = {"A.png"}  # only step 0 matches
        _tick(runner, "screen", 2)  # lost_since set; still waiting
        assert runner._index == 2
        _expire_search_delay(fake_screen)
        _tick(runner, "screen", 2)
        assert runner._index == 0

    @pytest.mark.edge
    def test_expected_candidates_follow_clicked_target(self):
        """The expected destination is the clicked target's goto, else the natural next step."""
        steps = [
            ClickStep([
                Target("templates/x/A.png", goto=3),
                Target("templates/x/B.png"),
            ]),
            ClickStep([Target("templates/x/C.png")]),
            ClickStep([Target("templates/x/D.png")]),
            ClickStep([Target("templates/x/E.png")]),
        ]
        runner = _runner(steps)
        clicked_a = runner.steps[0]._rules[0]
        clicked_b = runner.steps[0]._rules[1]
        assert runner._expected_candidates(0, clicked_target=clicked_a) == {3}
        assert runner._expected_candidates(0, clicked_target=clicked_b) == {1}

    @pytest.mark.edge
    def test_forward_tie_prefers_forward(self, fake_screen):
        """At equal distance a forward candidate wins the tie."""
        steps = [ClickStep([Target(f"templates/x/{n}.png")]) for n in "ABCDEF"]
        runner = _runner(steps)
        runner._index = 3
        fake_screen.visible = {"C.png", "E.png"}  # step 2 (back) and step 4 (forward)
        assert runner._select_anchor("screen", searching=True) == 4

    @pytest.mark.positive
    def test_confirming_uses_clicked_target_goto_only(self, fake_screen):
        """When the clicked target has no goto, another target's goto is not considered."""
        steps = [
            ClickStep([
                Target("templates/x/end.png", goto=3, action=ClickAction.RIGHT_CLICK, label="end"),
                Target("templates/x/select.png", label="select"),
            ]),
            ClickStep([Target("templates/x/next.png")]),
            ClickStep([Target("templates/x/mid.png")]),
            ClickStep([Target("templates/x/home.png")]),
        ]
        runner = _runner(steps)
        fake_screen.visible = {"select.png"}
        runner.tick("screen")  # click select

        fake_screen.visible = set()  # select disappears
        runner.tick("screen")  # enter confirming

        fake_screen.visible = {"home.png"}  # would be step 3, but not expected
        _tick(runner, "screen", 5)
        assert runner._index == 0

        fake_screen.visible = {"next.png"}  # expected next step
        _tick(runner, "screen", 2)
        assert runner._index == 1

    @pytest.mark.positive
    def test_confirming_anchors_to_clicked_target_goto(self, fake_screen):
        """When the clicked target has an explicit goto, confirming waits for that step."""
        steps = [
            ClickStep([
                Target("templates/x/end.png", goto=3, action=ClickAction.RIGHT_CLICK, label="end"),
                Target("templates/x/select.png", label="select"),
            ]),
            ClickStep([Target("templates/x/next.png")]),
            ClickStep([Target("templates/x/mid.png")]),
            ClickStep([Target("templates/x/home.png")]),
        ]
        runner = _runner(steps)
        fake_screen.visible = {"end.png"}
        runner.tick("screen")  # click end

        fake_screen.visible = set()
        runner.tick("screen")  # enter confirming

        fake_screen.visible = {"home.png"}
        _tick(runner, "screen", 2)
        assert runner._index == 3

    @pytest.mark.positive
    def test_expected_step_advances_without_settling(self, fake_screen):
        """The expected next step advances on a still-changing screen (no settle wait)."""
        steps = [ClickStep([Target("templates/x/A.png")]), ClickStep([Target("templates/x/B.png")])]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick(_frame(0))  # click A

        fake_screen.visible = {"B.png"}  # expected origin+1
        _tick_frames(runner, [_frame(40), _frame(80), _frame(120)])
        assert runner._index == 1

    @pytest.mark.positive
    def test_terminal_completion_deferred_while_unstable(self, fake_screen):
        """The plan does not finish on a still-changing screen even if the target is gone."""
        runner = _runner([ClickStep([Target("templates/x/A.png")])])
        fake_screen.visible = {"A.png"}
        runner.tick(_frame(0))  # click A

        fake_screen.visible = set()
        _tick_frames(runner, [_frame(30), _frame(60), _frame(90), _frame(120)])
        assert runner.done is False

        _tick_frames(runner, [_frame(150)] * 3)
        assert runner.done is True

    @pytest.mark.edge
    def test_advance_resets_stability(self, fake_screen):
        """Entering a new step (goto or natural advance) clears the settled-screen history."""
        runner = _runner(
            [ClickStep([Target("templates/x/A.png")]), ClickStep([Target("templates/x/B.png")])]
        )
        runner.tick(_frame(0))
        runner.tick(_frame(0))
        assert runner._stable_frames >= 1
        runner._advance_to(1)
        assert runner._stable_frames == 0
        assert runner._prev_frame is None

    @pytest.mark.positive
    def test_expected_next_step_advances_within_search_delay(self, fake_screen):
        """The expected next step still advances immediately, without waiting out the delay."""
        steps = [ClickStep([Target("templates/x/A.png")]), ClickStep([Target("templates/x/B.png")])]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick("screen")  # click A
        fake_screen.visible = {"B.png"}  # expected origin+1
        _tick(runner, "screen", 2)
        assert runner._index == 1
        assert runner._lost_since is None

    @pytest.mark.positive
    def test_hunt_waits_for_settled_screen(self, fake_screen):
        """After the search delay the hunt still waits for the screen to settle."""
        steps = [ClickStep([Target(f"templates/x/{n}.png")]) for n in "ABCD"]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick(_frame(0))  # click A
        fake_screen.visible = {"C.png"}  # step 2, non-expected and non-terminal
        runner.tick(_frame(10))  # lost; _lost_since set
        fake_screen.clock.now += SEARCH_DELAY + 0.1

        _tick_frames(runner, [_frame(40), _frame(80), _frame(120)])
        assert runner._index == 0  # hunting but the screen never settled

        _tick_frames(runner, [_frame(200)] * 4)
        assert runner._index == 2

    @pytest.mark.edge
    def test_hunt_keeps_pending_across_unsettled_frame(self, fake_screen):
        """During the hunt, a wobble frame does not discard the verification in progress."""
        steps = [ClickStep([Target(f"templates/x/{n}.png")]) for n in "ABCD"]
        runner = _runner(steps)
        fake_screen.visible = {"A.png"}
        runner.tick(_frame(0))  # click A
        fake_screen.visible = {"C.png"}  # step 2, non-expected and non-terminal
        runner.tick(_frame(10))  # lost; _lost_since set
        fake_screen.clock.now += SEARCH_DELAY + 0.1

        runner.tick(_frame(100))
        runner.tick(_frame(100))
        runner.tick(_frame(100))  # settled -> hunt picks step 2
        assert runner._pending_pick == 2
        runner.tick(_frame(255))  # wobble
        assert runner._pending_pick == 2


class TestPlanCompletion:
    """Suite: how a plan ends — terminal steps, out-of-range jumps, and post-done ticks."""

    @pytest.mark.positive
    def test_terminal_step_done_on_gone(self, fake_screen):
        """The last step finishes the plan as soon as its target disappears."""
        runner = _runner([ClickStep([Target("templates/x/A.png")])])
        fake_screen.visible = {"A.png"}
        runner.tick("screen")
        fake_screen.visible = set()
        runner.tick("screen")
        assert runner.done is True

    @pytest.mark.edge
    def test_goto_step_if_not_found_past_end_finishes(self, fake_screen):
        """A jump past the last step lands out of range and finishes on the next tick."""
        runner = _runner([ClickStep([Target("templates/x/A.png")], goto_step_if_not_found=9)])
        fake_screen.visible = set()
        runner.tick("screen")
        assert runner._index == 9
        assert runner.done is False
        runner.tick("screen")
        assert runner.done is True

    @pytest.mark.edge
    def test_done_tick_is_noop(self, fake_screen):
        """Ticking a finished plan does nothing and does not raise."""
        runner = _runner([])
        runner.tick("screen")
        assert runner.done is True
        runner.tick("screen")
        assert runner.done is True
