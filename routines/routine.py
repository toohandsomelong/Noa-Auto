from __future__ import annotations

import time
from typing import Any

import pyautogui

from core.screen_bot import _load_template, _match

from routines.base import WAIT, DONE, RECOVER
from routines.step import Step


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
        self._try_click_home(screenshot)
        self.logger.state(f"Routine '{self.name}' aborted and restarted")
        self.done = True

    def _try_click_home(self, screenshot: Any) -> None:
        home_template = _load_template("templates/main/home.png", True)
        if home_template is None:
            return
        home_match = _match(screenshot, home_template, 0.85, True)
        if home_match is None:
            return
        try:
            pyautogui.click(home_match.center[0], home_match.center[1])
            self.logger.info("Clicked home.png during routine recovery")
        except Exception as e:
            self.logger.error(f"Recovery home click failed: {e}")
