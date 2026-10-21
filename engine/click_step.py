from __future__ import annotations

import time
from typing import Any, Callable

from core.match_result import MatchResult
from core.screen_bot import get_capture_origin, get_capture_scale

from engine.base import WAIT, DONE, match_template, do_click
from engine.step import Step
from engine.click_action import ClickAction
from engine.target import Target


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

    def reset(self) -> None:
        super().reset()
        for rule in self._rules:
            rule.reset()
        self._ready_until = time.time() + self._ready_delay
        self._clicked_gone = False

    def reset_click_state(self) -> None:
        super().reset_click_state()
        for rule in self._rules:
            rule.reset()

    def tick(self, screenshot: Any) -> int:
        self.lost = False
        self.confirming = False
        self._clicked_gone = False
        log = self.logger
        if time.time() < self._ready_until:
            if log:
                log.info(f"{self.log_prefix()} waiting ready_delay {self._ready_until - time.time():.2f}s")
            return WAIT

        for rule in self._rules:
            if log:
                log.info(f'{self.log_prefix()} evaluating target "{rule.label}" ({rule.template})')
            result = self._apply(rule, screenshot)
            if result is not None:
                if self._clicked_gone:
                    continue
                if log:
                    log.info(f'{self.log_prefix()} target "{rule.label}" decided result {result}')
                return result
            if log:
                log.info(f'{self.log_prefix()} target "{rule.label}" returned None (inconclusive)')

        if self._clicked_gone:
            if log:
                log.info(
                    f'{self.log_prefix()} clicked target gone - '
                    f"waiting for anchor to locate next step"
                )
            return WAIT

        if self._goto_step_if_not_found is not None:
            if log:
                log.info(f"{self.log_prefix()} no target acted - goto_step_if_not_found={self._goto_step_if_not_found}")
            return self._goto_step_if_not_found

        return self.stuck_or_wait()

    def _apply(self, target: Target, screenshot: Any) -> int | None:
        thresh = target.threshold if target.threshold is not None else self.threshold
        gs = target.grayscale if target.grayscale is not None else self.grayscale
        matches: list[MatchResult] = []
        missing: list[str] = []
        for path in target.templates:
            mi = match_template(screenshot, path, threshold=thresh, grayscale=gs)
            if mi is None:
                missing.append(path)
                break
            matches.append(mi)

        m = matches[0] if matches and not missing else None

        self.last_match = m
        self.last_match_label = target.label if m is not None else None
        log = self.logger

        if m is not None and log:
            log.info(
                f'{self.log_prefix()} target "{target.label}": matched at '
                f"{m.location[0]},{m.location[1]} conf={m.confidence:.2f}"
            )
        elif m is None and log:
            if len(target.templates) > 1 and missing:
                log.info(
                    f'{self.log_prefix()} target "{target.label}": NOT found '
                    f"(missing {len(missing)} of {len(target.templates)} templates: {', '.join(missing)})"
                )
            else:
                log.info(f'{self.log_prefix()} target "{target.label}": NOT found')

        if m is None:
            if (
                target.click_count == 0
                and target.scrollValue != 0
                and target.scroll_point is not None
            ):
                ox, oy = get_capture_origin()
                scale_x, scale_y = get_capture_scale()
                sx, sy = target.scroll_point
                point = (
                    int(sx * scale_x) + ox,
                    int(sy * scale_y) + oy,
                )
                if log:
                    log.info(
                        f'{self.log_prefix()} target "{target.label}": not found - '
                        f"scrolling at {point}"
                    )
                do_click(
                    point,
                    scrollValue=target.scrollValue,
                    ClickAction=ClickAction.SCROLL,
                    label=target.label,
                    logger=self.logger,
                )
                return None

            if target.click_count > 0:
                if target.stay_on_confirm:
                    target.reset()
                    if log:
                        log.info(f"Blocker {target.label} dismissed")
                    return None

                next_idx = target.goto if target.goto is not None else self.index + 1
                if getattr(target, "terminal", False):
                    if log:
                        log.info(
                            f'{self.log_prefix()} target "{target.label}": terminal target gone - finishing'
                        )
                    self._fire(target.on_confirm, "on_confirm", target.label)
                    return DONE

                if log:
                    log.info(
                        f'{self.log_prefix()} target "{target.label}": clicked target gone'
                    )
                self._clicked_target = target
                self.lost = True
                self.confirming = True

                # If the clicked target had an explicit goto, preserve the old
                # behaviour: stop evaluating this step and let the runner expect
                # that specific step. Otherwise keep checking later targets in
                # case one of them can still act on this screen.
                if target.goto is None:
                    self._clicked_gone = True
                    return None
                return WAIT

            return None

        if target.action == ClickAction.CONTINUE:
            if log:
                log.info(f"{self.label}: {target.label} already satisfied, advancing")
            self._clicked_gone = False
            self.lost = False
            self.confirming = False
            self._fire(target.on_match, "on_match", target.label)
            return target.goto if target.goto is not None else self.index + 1

        if target.action == ClickAction.SCROLL:
            if log:
                log.info(f"{self.label}: {target.label} matched after scroll, advancing")
            self._clicked_gone = False
            self.lost = False
            self.confirming = False
            self._fire(target.on_match, "on_match", target.label)
            return target.goto if target.goto is not None else self.index + 1

        if target.click_count > 0 and log:
            log.info(
                f'{self.log_prefix()} target "{target.label}": still visible after '
                f"{target.click_count} clicks - re-clicking"
            )

        self._clicked_gone = False
        self.lost = False
        self.confirming = False
        time.sleep(self.delay)
        point = self._target_point(m, target)
        post_scroll = 0 if target.scroll_point is not None else target.scrollValue
        do_click(point, ClickAction=target.action, scrollValue=post_scroll, label=target.label, logger=self.logger)

        target.click_count += 1
        if log:
            btn = "Right-clicked" if target.action == ClickAction.RIGHT_CLICK else "Clicked"
            log.info(f"{btn} {target.label} ({target.click_count}) at {point}")
            log.info(
                f'{self.log_prefix()} target "{target.label}": clicked - returning WAIT, awaiting confirmation'
            )
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
        ox, oy = get_capture_origin()
        scale_x, scale_y = get_capture_scale()
        x = int((m.location[0] + m.size[0] // 2 + target.offset_x) * scale_x) + ox
        y = int((m.location[1] + m.size[1] // 2 + target.offset_y) * scale_y) + oy
        return (x, y)
