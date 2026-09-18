from __future__ import annotations

import os
from collections.abc import Callable

from routines.click_action import ClickAction

class Target:
    def __init__(
        self,
        template: str | list[str],
        *,
        action: ClickAction = ClickAction.LEFT_CLICK,
        scrollValue: int = 0,
        offset_x: int = 0,
        offset_y: int = 0,
        on_match: Callable[[], None] | None = None,
        on_confirm: Callable[[], None] | None = None,
        goto: int | None = None,
        stay_on_confirm: bool = False,
        threshold: float | None = None,
        grayscale: bool = True,
        label: str | None = None,
    ) -> None:
        self.templates = self._normalize_templates(template)
        self.action = action
        self.scrollValue = scrollValue
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.on_match = on_match
        self.on_confirm = on_confirm
        self.goto = goto
        self.stay_on_confirm = stay_on_confirm
        self.threshold = threshold
        self.grayscale = grayscale
        self.label = label or os.path.basename(self.templates[0])

        self.click_count = 0

    @property
    def template(self) -> str:
        return self.templates[0]

    @staticmethod
    def _normalize_templates(template: str | list[str]) -> list[str]:
        if isinstance(template, str):
            if not template:
                raise ValueError("target template must be a non-empty string")
            return [template]
        if isinstance(template, list):
            if not template:
                raise ValueError("target template list must be non-empty")
            if not all(isinstance(t, str) and t for t in template):
                raise ValueError("target template list must contain only non-empty strings")
            return list(template)
        raise ValueError(f"target template must be a string or list of strings, got {type(template).__name__}")

    def reset(self) -> None:
        self.click_count = 0
