from __future__ import annotations

import pytest

from engine.click_step import ClickStep
from engine.config import PlanConfig
from engine.plan_runner import PlanRunner
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

        fake_screen.visible = {"A.png"}
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
    def test_overlap_guard_skips_candidate(self, fake_screen):
        """A candidate sharing a template with the current step is not considered."""
        shared = Target("templates/x/shared.png")
        steps = [
            ClickStep([shared, Target("templates/x/A.png")]),
            ClickStep([shared, Target("templates/x/B.png")]),
        ]
        runner = _runner(steps)
        fake_screen.visible = {"shared.png", "A.png"}
        runner.tick("screen")

        fake_screen.visible = {"shared.png", "B.png"}
        _tick(runner, "screen", 5)
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
    def test_anchor_candidate_order_is_goto_then_forward_then_earlier(self):
        """Candidate order is goto successors, then forward steps, then earlier steps."""
        steps = [
            ClickStep([Target("templates/x/A.png", goto=2)]),
            ClickStep([Target("templates/x/B.png")]),
            ClickStep([Target("templates/x/C.png")]),
        ]
        runner = _runner(steps)
        assert runner._anchor_candidates() == [2, 1]

    @pytest.mark.edge
    def test_origin_excluded_from_candidates(self):
        """The current step is never a candidate for itself."""
        steps = [ClickStep([Target("templates/x/A.png")]), ClickStep([Target("templates/x/B.png")])]
        runner = _runner(steps)
        runner._index = 1
        assert 1 not in runner._anchor_candidates()

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
