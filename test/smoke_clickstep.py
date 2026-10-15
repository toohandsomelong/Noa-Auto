from __future__ import annotations

"""Smoke test for ClickStep / PlanRunner logic -- no game, no templates.

``match_template`` is simulated via a ``visible`` set of template basenames,
so each scenario controls exactly which templates the bot sees on screen.

Run from anywhere:
    "C:\\Users\\trucn\\miniconda3\\python.exe" test\\smoke_clickstep.py
"""

import os
import sys
from collections.abc import Callable

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine.base as base_mod
import engine.click_step as cs_mod
import engine.plan_runner as plan_runner_mod
from core.match_result import MatchResult
from engine.click_step import ClickStep
from engine.config import PlanConfig
from engine.plan_runner import PlanRunner
from engine.target import Target


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
    set_attr(plan_runner_mod, "match_template", fake_match)


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


def make_runner(
    steps: list[ClickStep] | None = None,
    interrupts: list[ClickStep] | None = None,
) -> PlanRunner:
    return PlanRunner(
        "smoke",
        steps if steps is not None else make_steps(),
        logger=LOG,
        config=PlanConfig(delay=0.0),
        interrupt_steps=interrupts,
    )


def tick(plan: PlanRunner, times: int = 1) -> None:
    for _ in range(times):
        plan.tick(None)


def reset_visible(*names: str) -> None:
    visible.clear()
    visible.update(names)


def scenario_a_retries_while_matched() -> None:
    print("A: current template stays on screen -> keeps re-clicking (count grows)")
    plan = make_runner()
    clicks.clear()
    reset_visible("B.png", "C.png", "D.png")
    tick(plan, 3)
    target = plan.steps[0]._rules[0]
    assert len(clicks) == 3, f"expected 3 clicks, got {len(clicks)}"
    assert target.click_count == 3, f"expected count 3, got {target.click_count}"
    assert plan._index == 0, f"expected to stay at step 0, got {plan._index}"
    print("    PASS: re-clicks every tick while template is found")


def scenario_c_transition_anchors() -> None:
    print("C: real transition (current gone, next step visible 2 frames) -> anchors & advances")
    plan = make_runner()
    clicks.clear()
    reset_visible("B.png")
    tick(plan, 1)  # B clicked
    reset_visible("C.png")  # screen moved to C
    tick(plan, 2)  # anchor sees C, debounces, then jumps
    assert plan._index == 1, f"expected index 1, got {plan._index}"
    print("    PASS: advanced to step 1 only after next screen was confirmed visible")


def scenario_d_loading_waits_then_anchors() -> None:
    print("D: current gone + next NOT visible (loading) -> waits, then anchors when next appears")
    plan = make_runner()
    clicks.clear()
    reset_visible("B.png")
    tick(plan, 1)  # B clicked
    visible.clear()  # loading / transition -- nothing known visible
    tick(plan, 3)
    assert plan._index == 0, f"expected still at step 0 while loading, got {plan._index}"
    reset_visible("C.png")
    tick(plan, 2)  # anchor debounce
    assert plan._index == 1, f"expected idx 1 after loading, got {plan._index}"
    print("    PASS: waited through loading, then anchored to next step")


def scenario_d2_reclick_when_current_returns() -> None:
    print("D2: current template still visible after click (click failed) -> re-click, no advance")
    plan = make_runner()
    clicks.clear()
    reset_visible("B.png")
    tick(plan, 1)  # B clicked, count=1
    tick(plan, 1)
    tick(plan, 1)
    target = plan.steps[0]._rules[0]
    assert plan._index == 0, f"expected still step 0, got {plan._index}"
    assert target.click_count == 3, f"expected re-click (count 3), got {target.click_count}"
    print("    PASS: kept re-clicking while current template stayed visible")


def scenario_e_last_step_still_finishes() -> None:
    print("E: confirming on the LAST step (terminal target gone) finishes the plan immediately")
    steps = [ClickStep([Target("templates/x/B.png")])]
    plan = PlanRunner(
        "last",
        steps,
        logger=LOG,
        config=PlanConfig(delay=0.0),
    )
    clicks.clear()
    reset_visible("B.png")
    tick(plan, 1)  # clicked
    visible.clear()  # gone -> terminal target -> DONE
    tick(plan, 1)
    assert plan.done, f"expected plan done, got done={plan.done} idx={plan._index}"
    print("    PASS: plan ended cleanly on the last step")


def _drive_to_step(plan: PlanRunner, idx: int) -> None:
    """Walk the plan forward to ``idx`` by showing each step's screen."""
    names = {0: "B.png", 1: "C.png", 2: "D.png"}
    for i in range(idx):
        reset_visible(names[i])
        tick(plan, 1)  # click step i
        reset_visible(names[i + 1])
        tick(plan, 2)  # anchor debounce -> advance to i + 1
    assert plan._index == idx, f"expected to reach step {idx}, got {plan._index}"


def scenario_f_anchor_to_visible_step() -> None:
    print("F: stuck at step 2, step 1 screen visible -> anchor resumes from step 1")
    plan = make_runner()
    clicks.clear()
    _drive_to_step(plan, 2)
    reset_visible("C.png")  # game actually shows step 1's screen
    tick(plan, 2)  # anchor sees C, debounces, then jumps
    assert plan._index == 1, f"expected anchor to step 1, got {plan._index}"
    assert not plan.done, "expected plan to keep running after anchor"
    print("    PASS: proactive anchor resumed at step 1")


def scenario_g_unknown_screen_stays_lost() -> None:
    print("G: nothing visible after click -> stays lost (no abort, no timeout)")
    plan = make_runner()
    clicks.clear()
    reset_visible("B.png")
    tick(plan, 1)  # click B
    visible.clear()  # unknown screen
    tick(plan, 20)
    assert plan._index == 0, f"expected to stay at step 0, got {plan._index}"
    assert not plan.done, "expected plan to keep scanning"
    print("    PASS: unknown screen keeps scanning, never aborts")


def scenario_i_interrupt_dismissed_without_advancing() -> None:
    print("I: blocker visible -> interrupt clicks it, current step does not advance")
    interrupt = ClickStep([Target("templates/x/HALT.png")], label="halt")
    plan = make_runner(interrupts=[interrupt])
    clicks.clear()
    reset_visible("HALT.png", "B.png")  # blocker covers the step-0 screen
    tick(plan, 1)
    assert clicks == ["HALT.png"], f"expected blocker click, got {clicks}"
    assert plan._index == 0, f"expected to stay at step 0, got {plan._index}"
    assert plan.steps[0]._rules[0].click_count == 0, "step target must not be clicked while blocked"
    reset_visible("B.png")  # blocker gone
    tick(plan, 1)
    assert clicks == ["HALT.png", "B.png"], f"expected step to resume after blocker gone, got {clicks}"
    assert plan._index == 0, f"expected still at step 0, got {plan._index}"
    print("    PASS: interrupt dismissed the blocker, then the step proceeded normally")


def scenario_j_interrupt_overlap_guard() -> None:
    print("J: interrupt template equal to current step target is NOT dismissed")
    interrupt = ClickStep([Target("templates/x/B.png")], label="guard")
    plan = make_runner(interrupts=[interrupt])
    clicks.clear()
    reset_visible("B.png")
    tick(plan, 1)
    assert plan.steps[0]._rules[0].click_count == 1, "current step should own the click"
    assert interrupt._rules[0].click_count == 0, "interrupt must be skipped on template overlap"
    print("    PASS: overlapping interrupt skipped; current step acted")


def scenario_k_forward_successor_preferred() -> None:
    print("K: anchor prefers the forward successor over the origin")
    plan = make_runner()
    clicks.clear()
    _drive_to_step(plan, 1)
    reset_visible("D.png")  # origin+1 is visible
    tick(plan, 2)  # debounce -> commit
    assert plan._index == 2, f"expected forward successor step 2, got {plan._index}"
    print("    PASS: forward successor chosen over origin")


def scenario_l_origin_is_last_resort() -> None:
    print("L: only the origin screen is visible -> resume on the origin (last resort)")
    plan = make_runner()
    clicks.clear()
    _drive_to_step(plan, 2)
    reset_visible("C.png")  # only origin (step 1) visible
    tick(plan, 2)  # debounce -> commit on origin
    assert plan._index == 1, f"expected origin step 1, got {plan._index}"
    print("    PASS: origin used only when nothing else matches")


def scenario_m_non_origin_preferred() -> None:
    print("M: an earlier step is visible while origin is not -> earlier step wins")
    plan = make_runner()
    clicks.clear()
    _drive_to_step(plan, 2)
    reset_visible("B.png")  # earlier step 0 visible, origin (step 1) not visible
    tick(plan, 2)  # debounce -> commit
    assert plan._index == 0, f"expected step 0 over origin, got {plan._index}"
    print("    PASS: earlier non-origin candidate preferred")


def scenario_n_and_target_requires_all_templates() -> None:
    print("N: AND target only clicks when all its templates are visible")
    and_target = Target(["templates/x/A1.png", "templates/x/A2.png"])
    plan = make_runner(steps=[ClickStep([and_target]), ClickStep([Target("templates/x/C.png")])])
    clicks.clear()
    reset_visible("A1.png")
    tick(plan, 2)
    assert len(clicks) == 0, f"expected no clicks with only A1 visible, got {clicks}"
    reset_visible("A1.png", "A2.png")
    tick(plan, 1)
    assert clicks == ["A1.png"], f"expected click on first template, got {clicks}"
    assert plan.steps[0]._rules[0].click_count == 1
    print("    PASS: AND target clicked only after every template appeared")


def scenario_o_and_target_waits_for_next_screen() -> None:
    print("O: AND target waits for the next step screen after one template disappears")
    and_target = Target(["templates/x/A1.png", "templates/x/A2.png"])
    plan = make_runner(steps=[ClickStep([and_target]), ClickStep([Target("templates/x/C.png")])])
    clicks.clear()
    reset_visible("A1.png", "A2.png")
    tick(plan, 1)  # click
    reset_visible("A1.png", "C.png")  # A2 gone, next step visible
    tick(plan, 2)  # anchor debounce -> advance
    assert plan._index == 1, f"expected advance to step 1, got {plan._index}"
    print("    PASS: AND target advanced after next screen appeared")


def scenario_p_interrupt_overlap_guard_multi_template() -> None:
    print("P: multi-template interrupt sharing a template with current step is skipped")
    interrupt = ClickStep([Target(["templates/x/B.png", "templates/x/Z.png"])], label="guard-multi")
    plan = make_runner(interrupts=[interrupt])
    clicks.clear()
    reset_visible("B.png", "Z.png")
    tick(plan, 1)
    assert plan.steps[0]._rules[0].click_count == 1, "current step should own the click"
    assert interrupt._rules[0].click_count == 0, "overlapping interrupt must be skipped"
    print("    PASS: multi-template interrupt skipped on template overlap")


def scenario_q_plan_loader_accepts_list_template() -> None:
    print("Q: plan loader accepts string or list for target.template and rejects invalid values")
    from engine.plan_loader import _target_kwargs
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
    print("ClickStep/PlanRunner smoke test  (simulated template matching)")
    print("A-O: step lifecycle + proactive self-anchoring (no timeout/abort)")
    print("=" * 78)
    scenario_a_retries_while_matched()
    print()
    scenario_c_transition_anchors()
    print()
    scenario_d_loading_waits_then_anchors()
    print()
    scenario_d2_reclick_when_current_returns()
    print()
    scenario_e_last_step_still_finishes()
    print()
    scenario_f_anchor_to_visible_step()
    print()
    scenario_g_unknown_screen_stays_lost()
    print()
    scenario_i_interrupt_dismissed_without_advancing()
    print()
    scenario_j_interrupt_overlap_guard()
    print()
    scenario_k_forward_successor_preferred()
    print()
    scenario_l_origin_is_last_resort()
    print()
    scenario_m_non_origin_preferred()
    print()
    scenario_n_and_target_requires_all_templates()
    print()
    scenario_o_and_target_waits_for_next_screen()
    print()
    scenario_p_interrupt_overlap_guard_multi_template()
    print()
    scenario_q_plan_loader_accepts_list_template()
    print()
    print("All assertions passed.")


if __name__ == "__main__":
    main()
