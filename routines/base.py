from __future__ import annotations

from typing import Any

import pyautogui

from core.match_result import MatchResult
from core.screen_bot import _load_template, _match
from routines.click_action import ClickAction
from routines.step_status import StepStatus


WAIT = StepStatus.WAIT
DONE = StepStatus.DONE
RECOVER = StepStatus.RECOVER


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
    scrollValue: int = 0,
    *,
    ClickAction: ClickAction = ClickAction.LEFT_CLICK,
    label: str | None = None,
    logger: Any = None,
) -> bool:
    try:
        if(scrollValue != 0):
            pyautogui.scroll(scrollValue, x=point[0], y=point[1])
            
        match ClickAction:
            case ClickAction.LEFT_CLICK:
                pyautogui.click(point[0], point[1])
            case ClickAction.RIGHT_CLICK:
                pyautogui.rightClick(point[0], point[1])                
            case _:
                printLogError(f"Unknown ClickAction: {ClickAction}", logger)
                return False
    except Exception as e:
        printLogError(f"Click failed for {label or 'step'}: {e}", logger)
        return False
    return True

def printLogError(message: str, logger: Any = None) -> None:
    if logger is not None:
        logger.error(message)