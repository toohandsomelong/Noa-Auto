from __future__ import annotations

import os
import time
from typing import Any, Callable

import pyautogui

from screen_bot import MatchResult, _load_template, _match


WAIT = -1
DONE = -2
RECOVER = -3


def match_template(
    screenshot: Any,
    path: str,
    *,
    threshold: float = 0.85,
    grayscale: bool = True,
) -> MatchResult | None:
    template = _load_template(path, grayscale)
    if template is None:
        return None
    return _match(screenshot, template, threshold, grayscale)


def do_click(
    point: tuple[int, int],
    *,
    right: bool = False,
    label: str | None = None,
    logger: Any = None,
) -> bool:
    try:
        if right:
            pyautogui.rightClick(point[0], point[1])
        else:
            pyautogui.click(point[0], point[1])
    except Exception as e:
        if logger is not None:
            logger.error(f"Click failed for {label or 'step'}: {e}")
        return False
    return True


class Step:
    index: int = 0
    logger: Any = None
    pre_click_delay: float = 0.1
    max_click_retries: int = 5
    stuck_timeout: float = 15.0
    threshold: float = 0.85
    grayscale: bool = True
    label: str | None = None

    clicked: bool = False
    click_count: int = 0
    seek_start_time: float = 0.0

    def tick(self, screenshot: Any) -> int:
        return WAIT

    def reset(self) -> None:
        self.reset_click_state()

    def reset_click_state(self) -> None:
        self.clicked = False
        self.click_count = 0
        self.seek_start_time = 0.0

    def match(self, screenshot: Any, path: str) -> MatchResult | None:
        return match_template(
            screenshot, path, threshold=self.threshold, grayscale=self.grayscale
        )

    def click(self, point: tuple[int, int], *, right: bool = False) -> bool:
        return do_click(point, right=right, label=self.label, logger=self.logger)

    def stuck_or_wait(self, label: str | None = None) -> int:
        lbl = label or self.label
        if self.seek_start_time == 0.0:
            self.seek_start_time = time.time()
        elif time.time() - self.seek_start_time > self.stuck_timeout:
            if self.logger is not None:
                self.logger.warning(f"Step {lbl} not found for {self.stuck_timeout}s")
            return RECOVER
        return WAIT


class ClickRule:
    def __init__(
        self,
        template: str,
        *,
        action: str = "click",
        offset_x: int = 0,
        offset_below: int = 0,
        on_match: Callable[[], None] | None = None,
        on_confirm: Callable[[], None] | None = None,
        goto: int | None = None,
        stay_on_confirm: bool = False,
        threshold: float | None = None,
        grayscale: bool | None = None,
        label: str | None = None,
    ) -> None:
        self.template = template
        self.action = action
        self.offset_x = offset_x
        self.offset_below = offset_below
        self.on_match = on_match
        self.on_confirm = on_confirm
        self.goto = goto
        self.stay_on_confirm = stay_on_confirm
        self.threshold = threshold
        self.grayscale = grayscale
        self.label = label or os.path.basename(template)

        self.clicked = False
        self.click_count = 0

    def reset(self) -> None:
        self.clicked = False
        self.click_count = 0


class ClickStep(Step):
    """Step driven by an ordered list of ClickRules.  Each tick, rules are tested in
    order; the first matching rule applies.  If no rule matches, fall-through
    handles alt-chain, goto_step_not_found, or stuck_timeout.

    Replaces all former click-variant classes through composition-free fall-through:

      * ``stay_on_confirm=True`` → a blocker rule (right-click & dismiss, stay on step).
      * ``action="advance"`` → match the template and advance immediately (no click).
      * ``goto_step_not_found`` → branch index when no rule has ever matched.
      * ``alt_chain`` → sequential fallback clicks run only while no non-stay rule
        has been matched (faithful to the original PopupGuardedClickStep alt-chain).
      * ``ready_delay`` — grace period after (re)entry before any action.
    """

    def __init__(
        self,
        rules: list[ClickRule],
        *,
        alt_chain: list[str] | None = None,
        goto_step_not_found: int | None = None,
        ready_delay: float = 0.0,
        threshold: float = 0.85,
        grayscale: bool = True,
        label: str | None = None,
    ) -> None:
        self._rules = list(rules)
        self._alt_chain = list(alt_chain) if alt_chain else []
        self._goto_step_not_found = goto_step_not_found
        self._ready_delay = ready_delay
        self.threshold = threshold
        self.grayscale = grayscale
        self.label = label or "step"

        self._ready_until = 0.0
        self._alt_idx = 0
        self._alt_clicked = False
        self._alt_click_count = 0
        self._alt_seek_start = 0.0
        self._alt_active = False
        self._main_engaged = False

    def reset(self) -> None:
        super().reset()
        for rule in self._rules:
            rule.reset()
        self._alt_idx = 0
        self._alt_clicked = False
        self._alt_click_count = 0
        self._alt_seek_start = 0.0
        self._alt_active = False
        self._main_engaged = False
        self._ready_until = time.time() + self._ready_delay

    def tick(self, screenshot: Any) -> int:
        if time.time() < self._ready_until:
            return WAIT

        for rule in self._rules:
            result = self._apply(rule, screenshot)
            if result is not None:
                return result

        if not self._main_engaged and self._alt_chain:
            result = self._tick_alt_chain(screenshot)
            if result is not None:
                return result

        if self._main_engaged:
            return self.index + 1

        if self._goto_step_not_found is not None:
            return self._goto_step_not_found

        return self.stuck_or_wait()

    def _apply(self, rule: ClickRule, screenshot: Any) -> int | None:
        thresh = rule.threshold if rule.threshold is not None else self.threshold
        gs = rule.grayscale if rule.grayscale is not None else self.grayscale
        m = match_template(screenshot, rule.template, threshold=thresh, grayscale=gs)
        if m is not None:
            if rule.action == "advance":
                lbl = rule.label
                if self.logger is not None:
                    self.logger.info(f"{self.label}: {lbl} already satisfied, advancing")
                self._fire(rule.on_match, "on_match", lbl)
                return rule.goto if rule.goto is not None else self.index + 1

            if rule.click_count < self.max_click_retries:
                time.sleep(self.pre_click_delay)
                target = self._target_point(m, rule)
                right = rule.action == "right_click"
                do_click(target, right=right, label=rule.label, logger=self.logger)
                rule.click_count += 1
                rule.clicked = True
                self.seek_start_time = 0.0
                if not rule.stay_on_confirm:
                    self._main_engaged = True
                if self.logger is not None:
                    btn = "Right-clicked" if right else "Clicked"
                    self.logger.info(f"{btn} {rule.label} ({rule.click_count}) at {target}")
                self._fire(rule.on_match, "on_match", rule.label)
                return WAIT

            if self.logger is not None:
                self.logger.warning(
                    f"Rule {rule.label} retried {rule.click_count}x without transition"
                )
            return RECOVER

        if rule.clicked:
            if rule.stay_on_confirm:
                rule.reset()
                if self.logger is not None:
                    self.logger.info(f"Blocker {rule.label} dismissed")
                return None

            self._fire(rule.on_confirm, "on_confirm", rule.label)
            return rule.goto if rule.goto is not None else self.index + 1

        return None

    @staticmethod
    def _fire(cb: Callable[[], None] | None, name: str, label: str) -> None:
        if cb is None:
            return
        try:
            cb()
        except Exception:
            pass

    @staticmethod
    def _target_point(m: MatchResult, rule: ClickRule) -> tuple[int, int]:
        x = m.location[0] + m.size[0] // 2 + rule.offset_x
        if rule.offset_below:
            y = m.location[1] + m.size[1] + rule.offset_below
        else:
            y = m.location[1] + m.size[1] // 2
        return (x, y)

    def _tick_alt_chain(self, screenshot: Any) -> int | None:
        if self._alt_active:
            if self._alt_idx >= len(self._alt_chain):
                return None
            cur = self._alt_chain[self._alt_idx]
            m = self.match(screenshot, cur)
            if m is not None:
                if self._alt_click_count < self.max_click_retries:
                    time.sleep(self.pre_click_delay)
                    self.click(m.center)
                    self._alt_click_count += 1
                    self._alt_clicked = True
                    self._alt_seek_start = 0.0
                    if self.logger is not None:
                        self.logger.info(
                            f"Clicked alt {os.path.basename(cur)} "
                            f"({self._alt_idx}/{len(self._alt_chain)} "
                            f"click {self._alt_click_count})"
                        )
                    return WAIT
                if self.logger is not None:
                    self.logger.warning(
                        f"Alt {os.path.basename(cur)} retried {self._alt_click_count}x"
                    )
                return RECOVER

            if self._alt_clicked:
                self._alt_idx += 1
                if self._alt_idx >= len(self._alt_chain):
                    self._alt_idx = 0
                    self._alt_active = False
                    self._alt_clicked = False
                    self._alt_click_count = 0
                    self._alt_seek_start = 0.0
                    if self.logger is not None:
                        self.logger.info("Alt chain complete")
                    return None
                self._alt_clicked = False
                self._alt_click_count = 0
                self._alt_seek_start = 0.0
                return WAIT

            if self._alt_seek_start == 0.0:
                self._alt_seek_start = time.time()
            elif time.time() - self._alt_seek_start > self.stuck_timeout:
                if self.logger is not None:
                    self.logger.warning(
                        f"Alt {os.path.basename(cur)} not found for {self.stuck_timeout}s"
                    )
                return RECOVER
            return WAIT

        if not self._alt_chain:
            return None
        m = self.match(screenshot, self._alt_chain[0])
        if m is not None:
            self._alt_active = True
            time.sleep(self.pre_click_delay)
            self.click(m.center)
            self._alt_click_count = 1
            self._alt_clicked = True
            if self.logger is not None:
                self.logger.info(
                    f"Started alt chain at {os.path.basename(self._alt_chain[0])} (click 1)"
                )
            return WAIT
        return None


class BranchStep(Step):
    """Pure conditional jump on template presence. No click, no state."""

    def __init__(
        self,
        template_path: str,
        goto_found: int,
        goto_step_not_found: int,
        threshold: float = 0.85,
        grayscale: bool = True,
        label: str | None = None,
    ) -> None:
        self.template_path = template_path
        self.goto_found = goto_found
        self.goto_step_not_found = goto_step_not_found
        self.threshold = threshold
        self.grayscale = grayscale
        self.label = label or os.path.basename(template_path)

    def tick(self, screenshot: Any) -> int:
        m = self.match(screenshot, self.template_path)
        if m is not None:
            if self.logger is not None:
                self.logger.info(f"{self.label} found; branching to {self.goto_found}")
            return self.goto_found
        return self.goto_step_not_found


class EndStep(Step):
    """Terminal step. Fires ``on_done`` and returns DONE."""

    def __init__(self, on_done: Callable[[], None] | None = None) -> None:
        self.on_done = on_done

    def tick(self, screenshot: Any) -> int:
        if self.on_done is not None:
            try:
                self.on_done()
            except Exception as e:
                if self.logger is not None:
                    self.logger.error(f"End callback failed: {e}")
        if self.logger is not None:
            self.logger.state("Team trials routine complete")
        return DONE


class Routine:
    def __init__(
        self,
        name: str,
        steps: list[Step],
        logger: Any,
        pre_click_delay: float = 0.1,
        max_click_retries: int = 5,
        stuck_timeout: float = 15.0,
    ) -> None:
        self.name = name
        self.steps = steps
        self.logger = logger
        self.done = False

        for i, step in enumerate(steps):
            step.index = i
            step.logger = logger
            step.pre_click_delay = pre_click_delay
            step.max_click_retries = max_click_retries
            step.stuck_timeout = stuck_timeout

        self._index = 0
        self._reset_on_enter(0)

    def _reset_on_enter(self, idx: int) -> None:
        if 0 <= idx < len(self.steps):
            self.steps[idx].reset()

    def tick(self, screenshot: Any) -> None:
        if self.done:
            return
        if self._index < 0 or self._index >= len(self.steps):
            self.done = True
            return

        cur = self.steps[self._index]
        result = cur.tick(screenshot)

        if result == WAIT:
            return
        if result == DONE:
            self.done = True
            return
        if result == RECOVER:
            self._recover(screenshot)
            return

        if result != self._index:
            self._advance_to(result)

    def _advance_to(self, new_idx: int) -> None:
        if new_idx != self._index:
            self._reset_on_enter(new_idx)
        self._index = new_idx

    def _recover(self, screenshot: Any) -> None:
        home_template = _load_template("templates/main/home.png", True)
        if home_template is not None:
            home_match = _match(screenshot, home_template, 0.85, True)
            if home_match is not None:
                try:
                    pyautogui.click(home_match.center[0], home_match.center[1])
                    self.logger.info("Clicked home.png during routine recovery")
                except Exception as e:
                    self.logger.error(f"Recovery home click failed: {e}")

        self.logger.state(f"Routine '{self.name}' aborted and restarted")
        self.done = True


def build_team_trials_routine(
    logger: Any,
    on_done: Callable[[], None] | None = None,
) -> Routine:
    select_opponent_index = 2
    home_index = 12

    steps: list[Step] = [
        ClickStep([ClickRule("templates/racemenu/teamtrials.png")]),
        ClickStep([ClickRule("templates/racemenu/teamtrials/1.png")]),
        ClickStep(
            [
                ClickRule(
                    "templates/racemenu/teamtrials/end.png",
                    action="right_click",
                    on_confirm=on_done,
                    goto=home_index,
                ),
                ClickRule(
                    "templates/racemenu/teamtrials/selectopponent.png",
                    offset_below=50,
                ),
            ],
            ready_delay=2.0,
        ),
        ClickStep([ClickRule("templates/racemenu/teamtrials/2-6.png")]),
        ClickStep([ClickRule("templates/racemenu/teamtrials/3.png")]),
        ClickStep(
            [
                ClickRule(
                    "templates/racemenu/teamtrials/quickYes.png",
                    action="advance",
                ),
                ClickRule("templates/racemenu/teamtrials/quickNo.png"),
            ],
        ),
        ClickStep([ClickRule("templates/racemenu/teamtrials/4.png")]),
        ClickStep([ClickRule("templates/racemenu/teamtrials/5.png")]),
        ClickStep([ClickRule("templates/racemenu/teamtrials/2-6.png")]),
        ClickStep(
            [
                ClickRule(
                    "templates/racemenu/teamtrials/shop.png",
                    action="right_click",
                    stay_on_confirm=True,
                ),
                ClickRule("templates/racemenu/teamtrials/7.png"),
            ],
            alt_chain=[
                "templates/racemenu/teamtrials/smallnext.png",
                "templates/racemenu/teamtrials/2-6.png",
            ],
        ),
        ClickStep(
            [ClickRule("templates/racemenu/teamtrials/end.png", action="right_click")],
            goto_step_not_found=select_opponent_index,
        ),
        ClickStep([ClickRule("templates/racemenu/teamtrials/smallnext.png")]),
        ClickStep(
            [ClickRule("templates/main/home.png", on_match=on_done)],
        ),
        EndStep(on_done=on_done),
    ]

    return Routine("team_trials", steps, logger)