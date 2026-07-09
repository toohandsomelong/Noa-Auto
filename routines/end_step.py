from __future__ import annotations

from typing import Any

from routines.base import DONE
from routines.step import Step


class EndStep(Step):
    """Terminal step. Returns DONE."""

    def tick(self, screenshot: Any) -> int:
        log = self.logger
        if log:
            log.state("Routine complete")
        return DONE
