from __future__ import annotations

import os
import time
import threading
from collections.abc import Callable
from functools import lru_cache
from typing import Any

import cv2
import mss
import numpy as np
import pyautogui

from core.match_result import MatchResult
from core.state_manager import BotState, StateManager


def _capture(sct: Any | None = None) -> Any | None:
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
        self._routine: Any | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.on_routine_done: Callable[[str], None] | None = None

    def start_routine(self, routine: Any) -> None:
        self._routine = routine

    def is_routine_running(self) -> bool:
        return self._routine is not None and not self._routine.done

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def _run(self) -> None:
        pyautogui.FAILSAFE = True
        sct = mss.mss()
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
                        done_routine = self._routine
                        self._routine = None
                        if done_routine is not None and done_routine.done:
                            if self.on_routine_done is not None:
                                try:
                                    self.on_routine_done(done_routine.name)
                                except Exception as e:
                                    self.logger.error(f"on_routine_done failed: {e}")
                    continue

                self._routine = None
                time.sleep(self.check_interval)
        finally:
            sct.close()
