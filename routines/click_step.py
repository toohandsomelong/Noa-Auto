from __future__ import annotations

import os
import time
from typing import Any, Callable

from core.match_result import MatchResult

from routines.base import WAIT, RECOVER, match_template, do_click
from routines.step import Step
from routines.click_action import ClickAction
from routines.click import Click


class ClickStep(Step):
    """Step driven by an ordered list of ClickRules.  Each tick, rules are tested in
    order; the first matching rule applies.  If no rule matches, fall-through
    handles alt-chain, goto_step_not_found, or stuck_timeout.

    Replaces all former click-variant classes through composition-free fall-through:

      * ``stay_on_confirm=True`` → a blocker rule (right-click & dismiss, stay on step).
      * ``action=\"advance\"`` → match the template and advance immediately (no click).
      * ``goto_step_not_found`` → branch index when no rule has ever matched.
      * ``alt_chain`` → sequential fallback clicks run only while no non-stay rule
        has been matched (faithful to the original PopupGuardedClickStep alt-chain).
      * ``ready_delay`` — grace period after (re)entry before any action.
    """

    def __init__(
        self,
        rules: list[Click],
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

    def _apply(self, click: Click, screenshot: Any) -> int | None:
        thresh = click.threshold if click.threshold is not None else self.threshold
        gs = click.grayscale if click.grayscale is not None else self.grayscale
        m = match_template(screenshot, click.template, threshold=thresh, grayscale=gs)
        log = self.logger

        if m is None:
            if click.clicked:
                if click.stay_on_confirm:
                    click.reset()
                    if log:
                        log.info(f"Blocker {click.label} dismissed")
                    return None
                self._fire(click.on_confirm, "on_confirm", click.label)
                return click.goto if click.goto is not None else self.index + 1
            return None

        if click.action == ClickAction.ADVANCE:
            if log:
                log.info(f"{self.label}: {click.label} already satisfied, advancing")
            self._fire(click.on_match, "on_match", click.label)
            return click.goto if click.goto is not None else self.index + 1

        max_step_retry = self.max_step_retry
        if max_step_retry is not None and click.click_count >= max_step_retry:
            if log:
                log.warning(f"Rule {click.label} retried {click.click_count}x without transition")
            return RECOVER

        time.sleep(self.delay)
        target = self._target_point(m, click)
        right = click.action == ClickAction.RIGHT_CLICK
        do_click(target, right=right, label=click.label, logger=self.logger)
        click.click_count += 1
        click.clicked = True
        self.seek_start_time = 0.0
        if not click.stay_on_confirm:
            self._main_engaged = True
        if log:
            btn = "Right-clicked" if right else "Clicked"
            log.info(f"{btn} {click.label} ({click.click_count}) at {target}")
        self._fire(click.on_match, "on_match", click.label)
        return WAIT

    @staticmethod
    def _fire(cb: Callable[[], None] | None, name: str, label: str) -> None:
        if cb is None:
            return
        try:
            cb()
        except Exception:
            pass

    @staticmethod
    def _target_point(m: MatchResult, rule: Click) -> tuple[int, int]:
        x = m.location[0] + m.size[0] // 2 + rule.offset_x
        if rule.offset_y:
            y = m.location[1] + m.size[1] + rule.offset_y
        else:
            y = m.location[1] + m.size[1] // 2
        return (x, y)

    def _tick_alt_chain(self, screenshot: Any) -> int | None:
        log = self.logger

        if not self._alt_active:
            if not self._alt_chain:
                return None
            m = self.match(screenshot, self._alt_chain[0])
            if m is None:
                return None
            self._alt_active = True
            time.sleep(self.delay)
            self.click(m.center)
            self._alt_click_count = 1
            self._alt_clicked = True
            if log:
                log.info(f"Started alt chain at {os.path.basename(self._alt_chain[0])} (click 1)")
            return WAIT

        if self._alt_idx >= len(self._alt_chain):
            return None

        cur = self._alt_chain[self._alt_idx]
        m = self.match(screenshot, cur)

        if m is not None:
            max_step_retry = self.max_step_retry
            if max_step_retry is not None and self._alt_click_count >= max_step_retry:
                if log:
                    log.warning(f"Alt {os.path.basename(cur)} retried {self._alt_click_count}x")
                return RECOVER
            time.sleep(self.delay)
            self.click(m.center)
            self._alt_click_count += 1
            self._alt_clicked = True
            self._alt_seek_start = 0.0
            if log:
                log.info(
                    f"Clicked alt {os.path.basename(cur)} "
                    f"({self._alt_idx}/{len(self._alt_chain)} "
                    f"click {self._alt_click_count})"
                )
            return WAIT

        if self._alt_clicked:
            self._alt_idx += 1
            if self._alt_idx >= len(self._alt_chain):
                self._alt_idx = 0
                self._alt_active = False
                self._alt_clicked = False
                self._alt_click_count = 0
                self._alt_seek_start = 0.0
                if log:
                    log.info("Alt chain complete")
                return None
            self._alt_clicked = False
            self._alt_click_count = 0
            self._alt_seek_start = 0.0
            return WAIT

        if self._alt_seek_start == 0.0:
            self._alt_seek_start = time.time()
        else:
            timeout = self.timeout
            if timeout is not None and time.time() - self._alt_seek_start > timeout:
                if log:
                    log.warning(f"Alt {os.path.basename(cur)} not found for {timeout}s")
                return RECOVER
        return WAIT
