from __future__ import annotations

import os
from typing import Any

from routines.step import Step


class BranchStep(Step):
    """Pure conditional jump on template presence. No click, no state."""

    def __init__(
        self,
        template_path: str,
        goto_found: int,
        goto_step_not_found: int,
        threshold: float = 0.85,
        grayscale: bool = True,
        label: str | None = None,
    ) -> None:
        self.template_path = template_path
        self.goto_found = goto_found
        self.goto_step_not_found = goto_step_not_found
        self.threshold = threshold
        self.grayscale = grayscale
        self.label = label or os.path.basename(template_path)

    def tick(self, screenshot: Any) -> int:
        m = self.match(screenshot, self.template_path)
        if m is not None:
            if self.logger:
                self.logger.info(f"{self.label} found; branching to {self.goto_found}")
            return self.goto_found
        return self.goto_step_not_found
