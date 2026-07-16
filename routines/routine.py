from __future__ import annotations

import time
from typing import Any

from routines.base import WAIT, DONE, RECOVER
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

        for i, step in enumerate(steps):
            step.index = i
            step.logger = logger
            step.delay = config.delay
            step.max_step_retry = config.max_step_retry
            step.timeout = config.timeout

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
        self._last_recover_index: int | None = None

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
            if self._last_recover_index is None or new_idx > self._last_recover_index:
                self._recover_count = 0
                self._last_recover_index = None
        self._index = new_idx

    def _recover(self, screenshot: Any) -> None:
        self._recover_count += 1
        self._last_recover_index = self._index

        if self._recover_count > self._max_recover:
            self.logger.state(
                f"Routine '{self.name}' aborted after {self._max_recover} recoveries"
            )
            self.done = True
            return

        for step in self._recover_steps:
            step.reset()
            step.tick(screenshot)

        self._index = 0
        self._reset_on_enter(0)
        self.logger.state(
            f"Routine '{self.name}' recovered "
            f"({self._recover_count}/{self._max_recover}), restarting from step 0"
        )
