from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

from core.match_result import MatchResult

from routines.base import WAIT, RECOVER, match_template, do_click

class Step:
    index: int = 0
    logger: Any = None
    delay: float = 0.0
    max_step_retry: int | None = None
    timeout: float | None = None
    threshold: float = 0.85
    grayscale: bool = True
    label: str | None = None

    clicked: bool = False
    click_count: int = 0
    seek_start_time: float = 0.0
    last_match: MatchResult | None = None
    last_match_label: str | None = None

    def tick(self, screenshot: Any) -> int:
        return WAIT

    def set_verify_next(self, verifier: Callable[[int, Any], bool] | None) -> None:
        pass

    def log_prefix(self) -> str:
        return f'[step {self.index} "{self.label or "step"}"]'

    def reset(self) -> None:
        if self.logger is not None:
            self.logger.info(f"{self.log_prefix()} reset")
        self.reset_click_state()
        self.last_match = None
        self.last_match_label = None

    def reset_click_state(self) -> None:
        self.clicked = False
        self.click_count = 0
        self.seek_start_time = 0.0

    def match(self, screenshot: Any, path: str) -> MatchResult | None:
        result = match_template(
            screenshot, path, threshold=self.threshold, grayscale=self.grayscale
        )
        self.last_match = result
        if result is not None:
            self.last_match_label = self.label or os.path.basename(path)
        return result

    def stuck_or_wait(self, label: str | None = None) -> int:
        lbl = label or self.label
        if self.seek_start_time == 0.0:
            self.seek_start_time = time.time()
            if self.logger is not None:
                self.logger.info(f"{self.log_prefix()} seek_start_time initialized:")
                self.logger.info(f"{self.log_prefix()} seeking template for step, status WAIT")
            return WAIT
        timeout = self.timeout
        if timeout is not None and time.time() - self.seek_start_time > timeout:
            if self.logger is not None:
                self.logger.warning(f"Step {lbl} not found for {timeout}s")
                self.logger.info(f"{self.log_prefix()} timeout exceeded, returning RECOVER")
            return RECOVER
        if self.logger is not None:
            self.logger.info(f"{self.log_prefix()} template not found yet, staying WAIT")
        return WAIT
