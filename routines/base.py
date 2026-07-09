from __future__ import annotations

from typing import Any

import pyautogui

from core.match_result import MatchResult
from core.screen_bot import _load_template, _match


WAIT = -1
DONE = -2
RECOVER = -3


def match_template(
    screenshot: Any,
    path: str,
    *,
    threshold: float = 0.85,
    grayscale: bool = True,
) -> MatchResult | None:
    template = _load_template(path, grayscale)
    if template is None:
        return None
    return _match(screenshot, template, threshold, grayscale)


def do_click(
    point: tuple[int, int],
    *,
    right: bool = False,
    label: str | None = None,
    logger: Any = None,
) -> bool:
    try:
        if right:
            pyautogui.rightClick(point[0], point[1])
        else:
            pyautogui.click(point[0], point[1])
    except Exception as e:
        if logger is not None:
            logger.error(f"Click failed for {label or 'step'}: {e}")
        return False
    return True
