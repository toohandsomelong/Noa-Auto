from __future__ import annotations

import os
import time
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

try:
    import cv2
    import mss
    import numpy as np
    import pyautogui
    HAS_DEPS = True
except ImportError:
    cv2 = None
    mss = None
    np = None
    pyautogui = None
    HAS_DEPS = False

from state_manager import BotState, StateManager


@dataclass(frozen=True)
class MatchResult:
    location: tuple[int, int]
    size: tuple[int, int]
    confidence: float

    @property
    def center(self) -> tuple[int, int]:
        x, y = self.location
        w, h = self.size
        return x + w // 2, y + h // 2


class Validator:
    def __init__(
        self,
        template_path: str,
        threshold: float = 0.85,
        grayscale: bool = True,
        action: Callable[[MatchResult], None] | None = None,
    ) -> None:
        self.template_path = template_path
        self.threshold = threshold
        self.grayscale = grayscale
        self.action = action

    def match(self, screenshot: Any) -> MatchResult | None:
        if not HAS_DEPS or np is None or cv2 is None:
            return None
        template = _load_template(self.template_path, self.grayscale)
        if template is None:
            return None
        return _match(screenshot, template, self.threshold, self.grayscale)


def _capture(sct: Any | None = None) -> Any | None:
    if not HAS_DEPS or mss is None or np is None or cv2 is None:
        return None
    close_on_exit = sct is None
    sct = sct or mss.mss()
    try:
        img = sct.grab(sct.monitors[0])
        bgr = np.array(img)[:, :, :3][:, :, ::-1]
        return bgr
    finally:
        if close_on_exit:
            sct.close()


@lru_cache(maxsize=128)
def _load_template(template_path: str, grayscale: bool) -> Any | None:
    if not HAS_DEPS or cv2 is None or np is None:
        return None
    full_path = os.path.abspath(template_path)
    if not os.path.exists(full_path):
        return None
    flags = cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR
    template = cv2.imread(full_path, flags)
    if template is None:
        return None
    return template


def _match(
    screenshot: Any,
    template: Any,
    threshold: float,
    grayscale: bool,
) -> MatchResult | None:
    if not HAS_DEPS or cv2 is None or np is None:
        return None
    screen = screenshot
    if grayscale and len(screenshot.shape) == 3:
        screen = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None
    h, w = template.shape[:2]
    return MatchResult(location=max_loc, size=(w, h), confidence=max_val)


class ScreenBot:
    def __init__(
        self,
        logger,
        state_manager: StateManager,
        focus_watcher,
        check_interval: float = 0.5,
    ) -> None:
        self.logger = logger
        self.state_manager = state_manager
        self.focus_watcher = focus_watcher
        self.check_interval = check_interval
        self._validators: list[Validator] = []
        self._routine: Any | None = None
        self._flags: dict[str, bool] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def register(self, validator: Validator) -> None:
        full_path = os.path.abspath(validator.template_path)
        if not os.path.exists(full_path):
            self.logger.warning(f"Template not found: {validator.template_path}")
        self._validators.append(validator)

    def start_routine(self, routine: Any) -> None:
        self._routine = routine

    def set_flag(self, name: str, value: bool) -> None:
        self._flags[name] = value

    def is_flag_set(self, name: str) -> bool:
        return self._flags.get(name, False)

    def start(self) -> None:
        if not HAS_DEPS:
            self.logger.warning(
                "ScreenBot dependencies missing (cv2, mss, numpy, pyautogui)"
            )
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def _run(self) -> None:
        if pyautogui is not None:
            pyautogui.FAILSAFE = True
        sct = mss.mss() if mss is not None else None
        try:
            while not self._stop_event.is_set():
                if self.state_manager.state != BotState.RUNNING:
                    time.sleep(self.check_interval)
                    continue
                screenshot = _capture(sct)
                if screenshot is None:
                    time.sleep(self.check_interval)
                    continue

                if self._routine is not None and not self._routine.done:
                    try:
                        self._routine.tick(screenshot)
                    except Exception as e:
                        self.logger.error(f"Routine tick failed: {e}")
                    if self._routine is None or self._routine.done:
                        self._routine = None
                else:
                    self._routine = None
                    for validator in self._validators:
                        match = validator.match(screenshot)
                        if match is not None:
                            if validator.action is not None:
                                try:
                                    validator.action(match)
                                except Exception as e:
                                    self.logger.error(f"Validator action failed: {e}")
                            break
                time.sleep(self.check_interval)
        finally:
            if sct is not None:
                sct.close()
