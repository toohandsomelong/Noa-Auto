from __future__ import annotations

"""Smoke test for ClickStep / Routine logic -- no game, no templates.

``match_template`` is simulated via a ``visible`` set of template basenames,
so each scenario controls exactly which templates the bot sees on screen.

Run from anywhere:
    "C:\\Users\\trucn\\miniconda3\\python.exe" test\\smoke_clickstep.py
"""

import os
import sys
import time
from collections.abc import Callable

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routines.base as base_mod
import routines.click_step as cs_mod
import routines.routine as routine_mod
from core.match_result import MatchResult
from routines.click_step import ClickStep
from routines.config import RoutineConfig
from routines.routine import Routine
from routines.target import Target


class FakeLogger:
    def __init__(self, verbose: bool = True) -> None:
        self._verbose = verbose

    def state(self, message: str, *args: object) -> None:
        self._emit("STATE", message)

    def info(self, message: str, *args: object) -> None:
        self._emit("INFO", message)

    def warning(self, message: str, *args: object) -> None:
        self._emit("WARN", message)

    def error(self, message: str, *args: object) -> None:
        self._emit("ERR", message)

    def _emit(self, level: str, message: str) -> None:
        if self._verbose:
            print(f"    [{level}] {message}")


visible: set[str] = set()
clicks: list[str] = []


def fake_match(screenshot: object, path: str, threshold: float = 0.85, grayscale: bool = True) -> MatchResult | None:
    if os.path.basename(path) in visible:
        return MatchResult(location=(10, 10), size=(10, 10), confidence=0.97)
    return None


def fake_click(*args: object, **kwargs: object) -> bool:
    clicks.append(str(kwargs.get("label")))
    return True


def _apply_patches(set_attr: Callable[..., None]) -> None:
    set_attr(cs_mod, "match_template", fake_match)
    set_attr(cs_mod, "do_click", fake_click)
    set_attr(base_mod, "match_template", fake_match)
    set_attr(base_mod, "do_click", fake_click)
    set_attr(routine_mod, "match_template", fake_match)


@pytest.fixture(autouse=True)
def _patch_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply_patches(monkeypatch.setattr)


LOG = FakeLogger()


def make_steps() -> list[ClickStep]:
    return [
        ClickStep([Target("templates/x/B.png")]),  # step 0
        ClickStep([Target("templates/x/C.png")]),  # step 1
        ClickStep([Target("templates/x/D.png")]),  # step 2
    ]


def make_routine(
    steps: list[ClickStep] | None = None,
    interrupts: list[ClickStep] | None = None,
    *,
    max_step_retry: int = 4,
    timeout: float | None = None,
    resync_timeout: float | None = None,
) -> Routine:
    return Routine(
        "smoke",
        steps if steps is not None else make_steps(),
        logger=LOG,
        config=RoutineConfig(
            delay=0.0,
            max_step_retry=max_step_retry,
            timeout=timeout,
            resync_timeout=resync_timeout,
        ),
        interrupt_steps=interrupts,
    )


def tick(routine: Routine, times: int = 1) -> None:
    for _ in range(times):
        routine.tick(None)


def reset_visible(*names: str) -> None:
    visible.clear()
    visible.update(names)


def scenario_a_retries_while_matched() -> None:
    print("A: current template stays on screen -> keeps re-clicking (count grows)")
    routine = make_routine()
    clicks.clear()
    reset_visible("B.png", "C.png", "D.png")
    tick(routine, 3)
    target = routine.steps[0]._rules[0]
    assert len(clicks) == 3, f"expected 3 clicks, got {len(clicks)}"
    assert target.click_count == 3, f"expected count 3, got {target.click_count}"
    assert routine._index == 0, f"expected to stay at step 0, got {routine._index}"
    print("    PASS: re-clicks every tick while template is found")


def scenario_b_max_step_then_resync_no_abort() -> None:
    print("B: template always matched -> max retry -> RECOVER -> resync (never aborts)")
    routine = make_routine()
    clicks.clear()
    reset_visible("B.png", "C.png", "D.png")  # B stays visible, click never registers
    tick(routine, 8)
    assert not routine.aborted, "expected routine to never abort"
    assert not routine.done, "expected routine to keep running after resync"
    print("    PASS: max-step RECOVER enters resync; routine keeps going instead of aborting")


def scenario_c_transition_advances() -> None:
    print("C: real transition (current gone, next step visible) -> verifies & advances")
    routine = make_routine()
    clicks.clear()
    reset_visible("B.png")
    tick(routine, 1)  # B clicked
    reset_visible("C.png")  # screen moved to C
    tick(routine, 1)  # confirm -> verify next step (C) visible -> advance
    assert routine._index == 1, f"expected index 1, got {routine._index}"
    print("    PASS: advanced to step 1 only after next screen was confirmed visible")


def scenario_d_loading_advances() -> None:
    print("D: current gone + next NOT visible (loading/transition) -> advances anyway")
    routine = make_routine()
    clicks.clear()
    reset_visible("B.png")
    tick(routine, 1)  # B clicked, count=1
    visible.clear()  # B gone AND C (next) gone -- game is transitioning/loading
    tick(routine, 1)  # confirm -> current done, next not visible -> advance (rule 3)
    assert routine._index == 1, f"expected idx 1 (loading advance), got {routine._index}"
    print("    PASS: advanced on 'both gone' = screen transitioning")


def scenario_d2_reclick_when_current_returns() -> None:
    print("D2: current template still visible after click (click failed) -> re-click, no advance")
    routine = make_routine()
    clicks.clear()
    reset_visible("B.png")
    tick(routine, 1)  # B clicked, count=1
    tick(routine, 1)
    tick(routine, 1)
    target = routine.steps[0]._rules[0]
    assert routine._index == 0, f"expected still step 0, got {routine._index}"
    assert target.click_count == 3, f"expected re-click (count 3), got {target.click_count}"
    print("    PASS: kept re-clicking while current template stayed visible")


def scenario_e_last_step_still_finishes() -> None:
    print("E: confirming on the LAST step (next out of range) still finishes the routine")
    steps = [ClickStep([Target("templates/x/B.png")])]
    routine = Routine(
        "last",
        steps,
        logger=LOG,
        config=RoutineConfig(delay=0.0, max_step_retry=4, timeout=None),
    )
    clicks.clear()
    reset_visible("B.png")
    tick(routine, 1)  # clicked
    visible.clear()  # gone -> next idx out of range -> verify allows -> advance
    tick(routine, 1)
    tick(routine, 1)  # idx now out of range -> routine done
    assert routine.done, f"expected routine done, got done={routine.done} idx={routine._index}"
    print("    PASS: routine ended cleanly on the last step")


def _drive_to_step(routine: Routine, idx: int) -> None:
    """Walk the routine forward to ``idx`` by showing each step's screen."""
    names = {0: "B.png", 1: "C.png", 2: "D.png"}
    for i in range(idx):
        reset_visible(names[i])
        tick(routine, 1)  # click step i
        reset_visible(names[i + 1])
        tick(routine, 1)  # confirm -> advance to i + 1
    assert routine._index == idx, f"expected to reach step {idx}, got {routine._index}"


def scenario_f_resync_to_visible_step() -> None:
    print("F: stuck at step 2, step 1 screen visible -> resync resumes from step 1")
    routine = make_routine()
    clicks.clear()
    _drive_to_step(routine, 2)
    reset_visible("D.png")
    tick(routine, 5)  # step 2 clicks 4x, then RECOVER while D is still on screen
    assert routine._resync_pending, "expected routine to be resync-pending after RECOVER"
    reset_visible("C.png")  # game actually shows step 1's screen
    tick(routine, 1)  # candidate seen 1/2 -- debounce, do not commit yet
    assert routine._resync_pending, "expected debounce to delay the resume by one tick"
    tick(routine, 1)  # candidate seen 2/2 -> commit
    assert routine._index == 1, f"expected resync to step 1, got {routine._index}"
    assert not routine.done and not routine.aborted, "expected routine to keep running after resync"
    print("    PASS: debounced resync resumed at step 1")


def scenario_g_unknown_screen_never_aborts() -> None:
    print("G: nothing visible during resync -> polls forever (no abort)")
    routine = make_routine()
    clicks.clear()
    reset_visible("B.png")
    tick(routine, 5)  # step 0 clicks 4x, then RECOVER
    assert routine._resync_pending, "expected routine to be resync-pending after RECOVER"
    visible.clear()  # unknown screen - no step matches
    tick(routine, 20)
    assert routine._resync_pending and not routine.done and not routine.aborted, (
        f"expected to stay pending, got pending={routine._resync_pending} "
        f"done={routine.done} aborted={routine.aborted}"
    )
    print("    PASS: unknown screen keeps polling, never aborts")


def scenario_h_resync_timeout_aborts() -> None:
    print("H: resync_timeout set -> no known step within the deadline -> aborts (escape hatch)")
    routine = make_routine(resync_timeout=0.01)
    clicks.clear()
    reset_visible("B.png")
    tick(routine, 5)  # RECOVER -> resync with a 10ms deadline
    visible.clear()
    time.sleep(0.02)
    tick(routine, 1)
    assert routine.aborted and routine.done, (
        f"expected abort, got aborted={routine.aborted} done={routine.done}"
    )
    print("    PASS: configured resync_timeout still aborts")


def scenario_i_interrupt_dismissed_without_advancing() -> None:
    print("I: blocker visible -> interrupt clicks it, current step does not advance")
    interrupt = ClickStep([Target("templates/x/HALT.png")], label="halt")
    routine = make_routine(interrupts=[interrupt])
    clicks.clear()
    reset_visible("HALT.png", "B.png")  # blocker covers the step-0 screen
    tick(routine, 1)
    assert clicks == ["HALT.png"], f"expected blocker click, got {clicks}"
    assert routine._index == 0, f"expected to stay at step 0, got {routine._index}"
    assert routine.steps[0]._rules[0].click_count == 0, "step target must not be clicked while blocked"
    reset_visible("B.png")  # blocker gone
    tick(routine, 1)
    assert clicks == ["HALT.png", "B.png"], f"expected step to resume after blocker gone, got {clicks}"
    assert routine._index == 0, f"expected still at step 0, got {routine._index}"
    print("    PASS: interrupt dismissed the blocker, then the step proceeded normally")


def scenario_j_interrupt_overlap_guard() -> None:
    print("J: interrupt template equal to current step target is NOT dismissed")
    interrupt = ClickStep([Target("templates/x/B.png")], label="guard")
    routine = make_routine(interrupts=[interrupt])
    clicks.clear()
    reset_visible("B.png")
    tick(routine, 1)
    assert routine.steps[0]._rules[0].click_count == 1, "current step should own the click"
    assert interrupt._rules[0].click_count == 0, "interrupt must be skipped on template overlap"
    print("    PASS: overlapping interrupt skipped; current step acted")


def scenario_k_forward_successor_preferred() -> None:
    print("K: resync prefers the forward successor over the origin")
    routine = make_routine()
    clicks.clear()
    _drive_to_step(routine, 1)
    reset_visible("C.png")
    tick(routine, 5)  # step 1 RECOVER
    reset_visible("D.png")  # origin+1 is visible
    tick(routine, 2)  # debounce -> commit
    assert routine._index == 2, f"expected forward successor step 2, got {routine._index}"
    print("    PASS: forward successor chosen over origin")


def scenario_l_origin_is_last_resort() -> None:
    print("L: only the origin screen is visible -> resume on the origin (last resort)")
    routine = make_routine()
    clicks.clear()
    _drive_to_step(routine, 1)
    reset_visible("C.png")
    tick(routine, 5)  # step 1 RECOVER (C still visible)
    tick(routine, 2)  # debounce -> commit on origin
    assert routine._index == 1, f"expected origin step 1, got {routine._index}"
    print("    PASS: origin used only when nothing else matches")


def scenario_m_non_origin_preferred_when_origin_visible() -> None:
    print("M: origin and an earlier step both visible -> non-origin wins")
    routine = make_routine()
    clicks.clear()
    _drive_to_step(routine, 1)
    reset_visible("C.png")
    tick(routine, 5)  # step 1 RECOVER
    reset_visible("B.png", "C.png")  # origin (C) and step 0 (B) both visible
    tick(routine, 2)  # debounce -> commit
    assert routine._index == 0, f"expected step 0 over origin, got {routine._index}"
    print("    PASS: non-origin candidate preferred even though origin is visible")


def scenario_n_and_target_requires_all_templates() -> None:
    print("N: AND target only clicks when all its templates are visible")
    and_target = Target(["templates/x/A1.png", "templates/x/A2.png"])
    routine = make_routine(steps=[ClickStep([and_target]), ClickStep([Target("templates/x/C.png")])])
    clicks.clear()
    reset_visible("A1.png")
    tick(routine, 2)
    assert len(clicks) == 0, f"expected no clicks with only A1 visible, got {clicks}"
    reset_visible("A1.png", "A2.png")
    tick(routine, 1)
    assert clicks == ["A1.png"], f"expected click on first template, got {clicks}"
    assert routine.steps[0]._rules[0].click_count == 1
    print("    PASS: AND target clicked only after every template appeared")


def scenario_o_and_target_confirms_when_any_template_gone() -> None:
    print("O: AND target advances as soon as any template disappears after click")
    and_target = Target(["templates/x/A1.png", "templates/x/A2.png"])
    routine = make_routine(steps=[ClickStep([and_target]), ClickStep([Target("templates/x/C.png")])])
    clicks.clear()
    reset_visible("A1.png", "A2.png")
    tick(routine, 1)  # click
    reset_visible("A1.png")  # A2 gone -> confirm -> advance
    tick(routine, 1)
    assert routine._index == 1, f"expected advance to step 1, got {routine._index}"
    print("    PASS: AND target advanced when one template disappeared")


def scenario_p_interrupt_overlap_guard_multi_template() -> None:
    print("P: multi-template interrupt sharing a template with current step is skipped")
    interrupt = ClickStep([Target(["templates/x/B.png", "templates/x/Z.png"])], label="guard-multi")
    routine = make_routine(interrupts=[interrupt])
    clicks.clear()
    reset_visible("B.png", "Z.png")
    tick(routine, 1)
    assert routine.steps[0]._rules[0].click_count == 1, "current step should own the click"
    assert interrupt._rules[0].click_count == 0, "overlapping interrupt must be skipped"
    print("    PASS: multi-template interrupt skipped on template overlap")


def scenario_q_plan_loader_accepts_list_template() -> None:
    print("Q: plan loader accepts string or list for target.template and rejects invalid values")
    from routines.plan_loader import _target_kwargs
    kwargs = _target_kwargs({"template": ["templates/x/A.png", "templates/x/B.png"]})
    assert kwargs["template"] == ["templates/x/A.png", "templates/x/B.png"]
    kwargs2 = _target_kwargs({"template": "templates/x/A.png"})
    assert kwargs2["template"] == "templates/x/A.png"
    try:
        _target_kwargs({"template": []})
        assert False, "empty list should raise"
    except ValueError:
        pass
    try:
        _target_kwargs({"template": ["templates/x/A.png", ""]})
        assert False, "empty string in list should raise"
    except ValueError:
        pass
    try:
        _target_kwargs({"template": 123})
        assert False, "non-string/non-list should raise"
    except ValueError:
        pass
    print("    PASS: plan loader validates template correctly")


def main() -> None:
    _apply_patches(setattr)
    print("=" * 78)
    print("ClickStep/Routine smoke test  (simulated template matching)")
    print("A-E: step lifecycle with max_step_retry=4")
    print("F-M: interrupt-first blockers + debounced priority resync (never abort by default)")
    print("=" * 78)
    scenario_a_retries_while_matched()
    print()
    scenario_b_max_step_then_resync_no_abort()
    print()
    scenario_c_transition_advances()
    print()
    scenario_d_loading_advances()
    print()
    scenario_d2_reclick_when_current_returns()
    print()
    scenario_e_last_step_still_finishes()
    print()
    scenario_f_resync_to_visible_step()
    print()
    scenario_g_unknown_screen_never_aborts()
    print()
    scenario_h_resync_timeout_aborts()
    print()
    scenario_i_interrupt_dismissed_without_advancing()
    print()
    scenario_j_interrupt_overlap_guard()
    print()
    scenario_k_forward_successor_preferred()
    print()
    scenario_l_origin_is_last_resort()
    print()
    scenario_m_non_origin_preferred_when_origin_visible()
    print()
    scenario_n_and_target_requires_all_templates()
    print()
    scenario_o_and_target_confirms_when_any_template_gone()
    print()
    scenario_p_interrupt_overlap_guard_multi_template()
    print()
    scenario_q_plan_loader_accepts_list_template()
    print()
    print("All assertions passed.")


if __name__ == "__main__":
    main()
