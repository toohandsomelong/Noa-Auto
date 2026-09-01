from __future__ import annotations

import time
from typing import Any, Callable

from core.match_result import MatchResult

from routines.base import WAIT, RECOVER, match_template, do_click
from routines.step import Step
from routines.click_action import ClickAction
from routines.target import Target


class ClickStep(Step):
    def __init__(
        self,
        rules: list[Target],
        *,
        goto_step_if_not_found: int | None = None,
        ready_delay: float = 0.0,
        threshold: float = 0.85,
        grayscale: bool = True,
        label: str | None = None,
    ) -> None:
        self._rules = list(rules)
        self._goto_step_if_not_found = goto_step_if_not_found
        self._ready_delay = ready_delay
        self.threshold = threshold
        self.grayscale = grayscale
        self.label = label or "step"

        self._ready_until = 0.0
        self._verify_next: Callable[[int, Any], bool] | None = None

    def set_verify_next(self, verifier: Callable[[int, Any], bool] | None) -> None:
        self._verify_next = verifier

    def reset(self) -> None:
        super().reset()
        for rule in self._rules:
            rule.reset()
        self._ready_until = time.time() + self._ready_delay

    def tick(self, screenshot: Any) -> int:
        if time.time() < self._ready_until:
            return WAIT

        for rule in self._rules:
            result = self._apply(rule, screenshot)
            if result is not None:
                return result

        if self._goto_step_if_not_found is not None:
            return self._goto_step_if_not_found

        return self.stuck_or_wait()

    def _apply(self, target: Target, screenshot: Any) -> int | None:
        # #because something still save after loop back step so it not trigger retry
        # #so we need to find that variable and reset it when it get loop back
        # print(str(time.localtime().tm_hour) + ":" + str(time.localtime().tm_min) + ":" + str(time.localtime().tm_sec)
        #         + " " + str(target.clicked))
            
        thresh = target.threshold if target.threshold is not None else self.threshold
        gs = target.grayscale if target.grayscale is not None else self.grayscale
        m = match_template(screenshot, target.template, threshold=thresh, grayscale=gs)

        self.last_match = m
        self.last_match_label = target.label if m is not None else None
        log = self.logger

        if m is None:
            if target.clicked:
                if target.stay_on_confirm:
                    target.reset()
                    if log:
                        log.info(f"Blocker {target.label} dismissed")
                    return None
                next_idx = target.goto if target.goto is not None else self.index + 1
                if self._verify_next is not None and not self._verify_next(next_idx, screenshot):
                    return WAIT
                self._fire(target.on_confirm, "on_confirm", target.label)
                return next_idx
            return None

        if target.action == ClickAction.CONTINUE:
            if log:
                log.info(f"{self.label}: {target.label} already satisfied, advancing")
            self._fire(target.on_match, "on_match", target.label)
            return target.goto if target.goto is not None else self.index + 1

        max_step_retry = self.max_step_retry
        if max_step_retry is not None and target.click_count >= max_step_retry:
            if log:
                log.warning(f"Target {target.label} retried {target.click_count}x without transition")
            return RECOVER

        time.sleep(self.delay)
        point = self._target_point(m, target)
        do_click(point, ClickAction=target.action, scrollValue=target.scrollValue, label=target.label, logger=self.logger)

        target.click_count += 1
        target.clicked = True
        self.seek_start_time = 0.0
        if log:
            btn = "Right-clicked" if target.action == ClickAction.RIGHT_CLICK else "Clicked"
            log.info(f"{btn} {target.label} ({target.click_count}) at {point}")
        self._fire(target.on_match, "on_match", target.label)
        
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
    def _target_point(m: MatchResult, target: Target) -> tuple[int, int]:
        x = m.location[0] + m.size[0] // 2 + target.offset_x
        if target.offset_y:
            y = m.location[1] + m.size[1] + target.offset_y
        else:
            y = m.location[1] + m.size[1] // 2
        return (x, y)
