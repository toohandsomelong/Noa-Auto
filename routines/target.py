from __future__ import annotations

import os
from typing import Callable

from routines.click_action import ClickAction

class Target:
    def __init__(
        self,
        template: str,
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
        self.template = template
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
        self.label = label or os.path.basename(template)

        self.clicked = False
        self.click_count = 0

    def reset(self) -> None:
        self.clicked = False
        self.click_count = 0
