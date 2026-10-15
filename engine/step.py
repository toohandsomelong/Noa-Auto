from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from core.match_result import MatchResult

from engine.base import WAIT, match_template, do_click


class Step:
    index: int = 0
    logger: Any = None
    delay: float = 0.0
    threshold: float = 0.85
    grayscale: bool = True
    label: str | None = None

    click_count: int = 0
    lost: bool = False
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
        self.lost = False

    def reset_click_state(self) -> None:
        self.click_count = 0

    def match(self, screenshot: Any, path: str) -> MatchResult | None:
        result = match_template(
            screenshot, path, threshold=self.threshold, grayscale=self.grayscale
        )
        self.last_match = result
        if result is not None:
            self.last_match_label = self.label or os.path.basename(path)
        return result

    def stuck_or_wait(self, label: str | None = None) -> int:
        self.lost = True
        if self.logger is not None:
            self.logger.info(f"{self.log_prefix()} seeking template, status WAIT")
        return WAIT
