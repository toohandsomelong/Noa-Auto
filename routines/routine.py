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
        recover_steps: list[Step] | None = None,
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

        self._recover_steps = recover_steps or []
        for i, step in enumerate(self._recover_steps):
            step.index = i
            step.logger = logger
            step.delay = config.delay
            step.max_step_retry = config.max_step_retry
            step.timeout = config.timeout

        self._index = 0
        self._reset_on_enter(0)

        self._recover_count = 0
        self._max_recover = config.max_recover
        self._high_water = 0
        self._resync_pending = False
        self._resync_origin = 0
        self._resync_deadline: float | None = None

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

    def _steps_visible(self, idx: int, screenshot: Any) -> bool:
        if not (0 <= idx < len(self.steps)):
            return True
        step = self.steps[idx]
        for target in getattr(step, "_rules", []):
            thresh = target.threshold if target.threshold is not None else step.threshold
            gs = target.grayscale if target.grayscale is not None else step.grayscale
            if match_template(screenshot, target.template, threshold=thresh, grayscale=gs) is not None:
                return True
        return False

    def current_step(self) -> Step | None:
        if self.done:
            return None
        if 0 <= self._index < len(self.steps):
            return self.steps[self._index]
        return None

    def tick(self, screenshot: Any) -> None:
        if self.done:
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
            self._recover(screenshot)
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
        if new_idx > self._high_water:
            self._high_water = new_idx
            self._recover_count = 0
        self._index = new_idx

    def _resync_order(self) -> list[int]:
        origin = self._resync_origin
        return sorted(range(len(self.steps)), key=lambda i: (abs(i - origin), i))

    def _resync_tick(self, screenshot: Any) -> None:
        for step in self._recover_steps:
            step.tick(screenshot)

        for idx in self._resync_order():
            if self._steps_visible(idx, screenshot):
                origin = self._resync_origin
                self._resync_pending = False
                if self.logger is not None:
                    self.logger.state(
                        f"Routine '{self.name}' resynced to step {idx} "
                        f"(recovering from step {origin})"
                    )
                self._advance_to(idx, force_reset=True)
                return

        if self._resync_deadline is not None and time.time() > self._resync_deadline:
            if self.logger is not None:
                self.logger.state(
                    f"Routine '{self.name}' resync failed - no known step visible, aborting"
                )
            self.aborted = True
            self.done = True
            self._resync_pending = False
            return

        if self.logger is not None:
            self.logger.info(f'[routine "{self.name}"] resync: no step visible yet, staying in resync')

    def _recover(self, screenshot: Any) -> None:
        self._recover_count += 1
        origin = self._index

        if self._recover_count > self._max_recover:
            if self.logger is not None:
                self.logger.state(
                    f"Routine '{self.name}' aborted after {self._max_recover} recoveries"
                )
            self.aborted = True
            self.done = True
            self._resync_pending = False
            return

        for step in self._recover_steps:
            step.reset()
            step.tick(screenshot)

        self._resync_pending = True
        self._resync_origin = origin
        timeout = self.config.timeout
        self._resync_deadline = time.time() + timeout if timeout is not None else None
        if self.logger is not None:
            self.logger.state(
                f"Routine '{self.name}' recover ({self._recover_count}/{self._max_recover}) "
                f"at step {origin} - scanning screen to resume"
            )
