from __future__ import annotations

import base64
import logging
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

logger = logging.getLogger(__name__)

def _capture(sct: Any | None = None) -> Any | None:
    close_on_exit = sct is None
    sct = sct or mss.mss()
    try:
        img = sct.grab(sct.monitors[0]) # type: ignore
        bgr = np.array(img)[:, :, :3][:, :, ::-1]
        return bgr
    finally:
        if close_on_exit:
            sct.close() # type: ignore


@lru_cache(maxsize=128)
def _load_template(template_path: str, grayscale: bool) -> Any | None:
    full_path = os.path.abspath(template_path)
    if not os.path.exists(full_path):
        logger.error(f"Template file not found: {full_path}")
        return None
    flags = cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR
    template = cv2.imread(full_path, flags)
    if template is None:
        logger.error(f"Failed to load template: {full_path}")
        return None
    return template


def _match(screenshot: Any, template: Any, threshold: float, grayscale: bool) -> MatchResult | None:
    screen = screenshot
    if grayscale and len(screenshot.shape) == 3:
        screen = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None
    h, w = template.shape[:2]
    return MatchResult(location=max_loc, size=(w, h), confidence=max_val) # type: ignore


class ScreenBot:
    def __init__(
        self,
        logger,
        state_manager: StateManager,
        focus_watcher,
        check_interval: float = 0.5,
        preview: bool = False,
        preview_mode: str = "snapshot",
        preview_fps: float = 5.0,
    ) -> None:
        self.logger = logger
        self.state_manager = state_manager
        self.focus_watcher = focus_watcher
        self.check_interval = check_interval
        self.preview = preview
        self.preview_mode = preview_mode
        self.preview_fps = preview_fps
        self._routine: Any | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.on_routine_done: Callable[[str], None] | None = None
        self.on_frame: Callable[[dict], None] | None = None
        self._last_frame_ts: float = 0.0
        self._last_match_key: tuple | None = None

    def start_routine(self, routine: Any) -> None:
        self._routine = routine
        self._last_match_key = None
        if self.preview and self.on_frame is not None:
            try:
                self.on_frame({"action": "clear"})
            except Exception:
                pass

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

    def _annotate(self, screenshot: Any, step: Any | None) -> Any:
        frame = screenshot.copy()
        if step is None:
            return frame
        match = getattr(step, "last_match", None)
        label = getattr(step, "last_match_label", None) or getattr(step, "label", None)
        if match is None:
            return frame
        x, y = match.location
        w, h = match.size
        pt1 = (x, y)
        pt2 = (x + w, y + h)
        cv2.rectangle(frame, pt1, pt2, (0, 255, 0), 2)
        text = f"{label or 'match'} {match.confidence:.2f}"
        tx, ty = x, max(y - 10, h + 10)
        cv2.putText(frame, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        return frame

    def _encode_frame(self, frame: Any) -> tuple[str, int, int] | None:
        max_width = 1280
        h, w = frame.shape[:2]
        if w > max_width:
            scale = max_width / w
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            h, w = frame.shape[:2]
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        if not ok:
            return None
        b64 = base64.b64encode(buf).decode("utf-8")
        return b64, w, h

    def _match_key(self, step: Any | None) -> tuple | None:
        if step is None:
            return None
        match = getattr(step, "last_match", None)
        label = getattr(step, "last_match_label", None) or getattr(step, "label", None)
        if match is None:
            return None
        return (
            label or "match",
            match.location,
            match.size,
            round(match.confidence, 2),
        )

    def _boxes_for_step(self, step: Any | None) -> list[dict]:
        if step is None:
            return []
        match = getattr(step, "last_match", None)
        label = getattr(step, "last_match_label", None) or getattr(step, "label", None)
        if match is None:
            return []
        return [{
            "x": match.location[0],
            "y": match.location[1],
            "w": match.size[0],
            "h": match.size[1],
            "label": label or "match",
            "confidence": match.confidence,
        }]

    def _broadcast_frame(self, screenshot: Any, step: Any | None) -> None:
        if self.on_frame is None:
            return
        frame = self._annotate(screenshot, step)
        encoded = self._encode_frame(frame)
        if encoded is None:
            return
        b64, w, h = encoded
        boxes = self._boxes_for_step(step)
        match = getattr(step, "last_match", None)
        label = getattr(step, "last_match_label", None) or getattr(step, "label", None)
        self._last_match_key = self._match_key(step)
        try:
            self.on_frame({
                "action": "frame",
                "jpeg": b64,
                "width": w,
                "height": h,
                "boxes": boxes,
                "step_index": getattr(step, "index", None),
                "step_label": label,
                "confidence": match.confidence if match is not None else None,
                "timestamp": time.time(),
            })
        except Exception:
            pass

    def _maybe_broadcast_frame(self, screenshot: Any) -> None:
        if not self.preview or self.on_frame is None:
            return
        step = None
        if self._routine is not None and not self._routine.done:
            step = self._routine.current_step()

        if self.preview_mode == "live":
            now = time.monotonic()
            interval = 1.0 / max(self.preview_fps, 1.0)
            if now - self._last_frame_ts < interval:
                return
            self._last_frame_ts = now
            self._broadcast_frame(screenshot, step)
            return

        key = self._match_key(step)
        if key is None:
            return
        if key == self._last_match_key:
            return
        self._broadcast_frame(screenshot, step)

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

                    self._maybe_broadcast_frame(screenshot)

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
