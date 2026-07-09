from __future__ import annotations

import time
from typing import Any

from core.match_result import MatchResult

from routines.base import WAIT, RECOVER, match_template, do_click


class Step:
    index: int = 0
    logger: Any = None
    pre_click_delay: float = 0.1
    max_click_retries: int = 15
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
            return WAIT
        if time.time() - self.seek_start_time > self.stuck_timeout:
            if self.logger is not None:
                self.logger.warning(f"Step {lbl} not found for {self.stuck_timeout}s")
            return RECOVER
        return WAIT
