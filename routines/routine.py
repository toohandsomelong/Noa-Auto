from __future__ import annotations

import time
from typing import Any

from routines.base import WAIT, DONE, RECOVER, match_template
from routines.config import RoutineConfig
from routines.step import Step


class Routine:
    def __init__(
        self,
        name: str,
        steps: list[Step],
        logger: Any,
        config: RoutineConfig,
        interrupt_steps: list[Step] | None = None,
    ) -> None:
        self.name = name
        self.steps = steps
        self.logger = logger
        self.config = config
        self.done = False
        self.aborted = False

        for i, step in enumerate(steps):
            step.index = i
            step.logger = logger
            step.delay = config.delay
            step.max_step_retry = config.max_step_retry
            step.timeout = config.timeout
            step.set_verify_next(self._steps_visible)

        self._interrupt_steps = interrupt_steps or []
        for i, step in enumerate(self._interrupt_steps):
            step.index = i
            step.logger = logger
            step.delay = config.delay
            step.max_step_retry = config.max_step_retry
            step.timeout = config.timeout

        self._index = 0
        self._reset_on_enter(0)

        self._interrupt_was_active = False
        self._resync_pending = False
        self._resync_origin = 0
        self._resync_deadline: float | None = None
        self._resync_candidate: int | None = None
        self._resync_hits = 0

    def _reset_on_enter(self, idx: int) -> None:
        if 0 <= idx < len(self.steps):
            step = self.steps[idx]
            step.reset()
            if self.logger is not None:
                self.logger.info(
                    f'[routine "{self.name}"] entering step {idx} ({step.label or "step"}) '
                    f"targets: {self._targets_desc(step)}"
                )

    def _targets_desc(self, step: Step) -> str:
        names = [getattr(t, "label", None) or t.template for t in getattr(step, "_rules", [])]
        return ", ".join(names) or "none"

    def _step_visible(self, step: Step, screenshot: Any) -> bool:
        for target in getattr(step, "_rules", []):
            thresh = target.threshold if target.threshold is not None else step.threshold
            gs = target.grayscale if target.grayscale is not None else step.grayscale
            if match_template(screenshot, target.template, threshold=thresh, grayscale=gs) is not None:
                return True
        return False

    def _steps_visible(self, idx: int, screenshot: Any) -> bool:
        if not (0 <= idx < len(self.steps)):
            return True
        return self._step_visible(self.steps[idx], screenshot)

    def _current_step_templates(self) -> set[str]:
        step = self.current_step()
        if step is None:
            return set()
        return {getattr(t, "template", "") for t in getattr(step, "_rules", [])}

    def _tick_interrupts(self, screenshot: Any) -> bool:
        """Tick the first visible interrupt (blocker) and short-circuit the routine.

        Interrupts are checked every cycle, regardless of the current step, and never
        advance the routine. Returns True while any blocker is on screen.
        """
        current_templates = self._current_step_templates()
        for step in self._interrupt_steps:
            step_templates = {getattr(t, "template", "") for t in getattr(step, "_rules", [])}
            if step_templates & current_templates:
                continue
            if self._step_visible(step, screenshot):
                self._interrupt_was_active = True
                if step.tick(screenshot) == RECOVER:
                    step.reset_click_state()
                return True

        if self._interrupt_was_active:
            for step in self._interrupt_steps:
                step.reset_click_state()
            self._interrupt_was_active = False
        return False

    def current_step(self) -> Step | None:
        if self.done:
            return None
        if 0 <= self._index < len(self.steps):
            return self.steps[self._index]
        return None

#TODO
#add multiple templates in a target step

    def tick(self, screenshot: Any) -> None:
        if self.done:
            return
        if self._tick_interrupts(screenshot):
            return
        if self._resync_pending:
            self._resync_tick(screenshot)
            return
        if self._index < 0 or self._index >= len(self.steps):
            self.done = True
            return

        cur = self.steps[self._index]
        result = cur.tick(screenshot)
        log = self.logger

        if result == WAIT:
            return
        if result == DONE:
            if log:
                log.info(f'[routine "{self.name}"] step {self._index} returned DONE - routine finished')
            self.done = True
            return
        if result == RECOVER:
            if log:
                log.info(f'[routine "{self.name}"] step {self._index} returned RECOVER')
            self._enter_resync()
            return

        if log:
            log.info(f'[routine "{self.name}"] step {self._index} returned result {result}, advancing')

        if result != self._index:
            self._advance_to(result)

    def _advance_to(self, new_idx: int, *, force_reset: bool = False) -> None:
        if self.logger is not None:
            self.logger.info(f'[routine "{self.name}"] advancing step {self._index} -> {new_idx}')
        if new_idx != self._index or force_reset:
            self._reset_on_enter(new_idx)
        self._index = new_idx

    def _resume_candidates(self) -> list[int]:
        """Return resume candidates in priority order (origin is the last resort)."""
        n = len(self.steps)
        if n == 0:
            return []
        origin = min(max(self._resync_origin, 0), n - 1)
        order: list[int] = []
        seen: set[int] = set()

        def add(idx: int) -> None:
            if 0 <= idx < n and idx not in seen:
                seen.add(idx)
                order.append(idx)

        step = self.steps[origin]
        for rule in getattr(step, "_rules", []):
            goto = getattr(rule, "goto", None)
            if goto is not None:
                add(goto)
        fallback = getattr(step, "_goto_step_if_not_found", None)
        if fallback is not None:
            add(fallback)
        add(origin + 1)
        for idx in range(origin + 1, n):
            add(idx)
        for idx in range(0, origin):
            add(idx)
        add(origin)
        return order

    def _resync_tick(self, screenshot: Any) -> None:
        best: int | None = None
        for idx in self._resume_candidates():
            if self._steps_visible(idx, screenshot):
                best = idx
                break

        if best is None:
            self._resync_candidate = None
            self._resync_hits = 0
            if self._resync_deadline is not None and time.time() > self._resync_deadline:
                if self.logger is not None:
                    self.logger.state(
                        f"Routine '{self.name}' resync timed out - no known step visible, aborting"
                    )
                self.aborted = True
                self.done = True
                self._resync_pending = False
                return
            if self.logger is not None:
                self.logger.info(
                    f'[routine "{self.name}"] resync: no step visible yet, staying in resync'
                )
            return

        if best == self._resync_candidate:
            self._resync_hits += 1
        else:
            self._resync_candidate = best
            self._resync_hits = 1

        if self._resync_hits < 2:
            if self.logger is not None:
                self.logger.info(
                    f'[routine "{self.name}"] resync: candidate step {best} seen '
                    f"{self._resync_hits}/2, confirming"
                )
            return

        origin = self._resync_origin
        self._resync_pending = False
        self._resync_candidate = None
        self._resync_hits = 0
        if self.logger is not None:
            self.logger.state(
                f"Routine '{self.name}' resynced to step {best} (was stuck at step {origin})"
            )
        self._advance_to(best, force_reset=True)

    def _enter_resync(self) -> None:
        origin = self._index
        self._resync_pending = True
        self._resync_origin = origin
        self._resync_candidate = None
        self._resync_hits = 0
        timeout = self.config.resync_timeout
        self._resync_deadline = time.time() + timeout if timeout is not None else None
        if self.logger is not None:
            self.logger.state(
                f"Routine '{self.name}' lost its place at step {origin} - scanning screen to resume"
            )
