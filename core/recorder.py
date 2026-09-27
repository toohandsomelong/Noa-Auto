from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

import cv2
import mss
import numpy as np
from pynput import keyboard

from core.screen_bot import _capture, resolve_capture_region


RECORDED_DIR = "templates/recorded"
TOGGLE_KEY = keyboard.Key.f8
CROP_KEY = keyboard.Key.f9
NEXT_KEY = keyboard.Key.f10
SCROLL_AMOUNT = 5


class Recorder:
    def __init__(
        self,
        *,
        on_toggle: Callable[[], None] | None = None,
        on_crop_request: Callable[[], None] | None = None,
        on_next_step: Callable[[], None] | None = None,
    ) -> None:
        self._state = "IDLE"
        self._lock = threading.Lock()
        self._listener: keyboard.Listener | None = None
        self._name: str | None = None
        self._slug: str | None = None
        self._step_index = 1
        self._current_targets: list[dict[str, Any]] = []
        self._steps: list[dict[str, Any]] = []
        self._file_hashes: dict[str, str] = {}
        self._on_toggle = on_toggle
        self._on_crop_request = on_crop_request
        self._on_next_step = on_next_step

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "name": self._name,
                "step_count": len(self._steps),
                "target_count": len(self._current_targets),
                "step_index": self._step_index,
                "steps": list(self._steps),
                "current_targets": list(self._current_targets),
            }

    def start(self, name: str | None = None) -> bool:
        with self._lock:
            if self._state != "IDLE":
                return False
            self._state = "RECORDING"
            self._name = name or self._default_name()
            self._slug = self._make_slug(self._name)
            self._step_index = 1
            self._current_targets = []
            self._steps = []
            self._file_hashes = {}
        self._start_listener()
        return True

    def stop(self) -> dict[str, Any] | None:
        self.next_step()
        with self._lock:
            if self._state == "IDLE":
                return None
            self._state = "IDLE"
            steps = list(self._steps)
            name = self._name or self._default_name()
            self._stop_listener()
        if not steps:
            return None
        return {"name": name, "steps": steps}

    def next_step(self) -> dict[str, Any] | None:
        with self._lock:
            if self._state != "RECORDING" or not self._current_targets:
                return None
            step_index = self._step_index
            targets = list(self._current_targets)
            self._current_targets = []
            self._step_index += 1
        step: dict[str, Any] = {
            "type": "click",
            "threshold": 0.85,
            "grayscale": True,
            "label": f"step {step_index}",
            "targets": targets,
        }
        with self._lock:
            self._steps.append(step)
        return step

    def begin_crop(self) -> tuple[np.ndarray, dict[str, int]] | None:
        with self._lock:
            state = self._state
        if state != "RECORDING":
            return None
        sct = mss.MSS()
        try:
            resolved = resolve_capture_region(sct, None)
            if resolved is None:
                return None
            region, _origin = resolved
            frame = _capture(sct, region)
            if frame is None:
                return None
            frame = np.ascontiguousarray(frame[:, :, ::-1])
            return frame, region
        finally:
            sct.close()

    def accept_target(
        self,
        crops: list[np.ndarray],
        action: str,
        *,
        scroll_dir: int | None = None,
        scroll_anchor: tuple[int, int] | None = None,
        offset: tuple[int, int] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            if self._state != "RECORDING" or self._slug is None:
                return None
            step_index = self._step_index
            target_index = len(self._current_targets) + 1
            slug = self._slug

        templates = self._save_crops(slug, step_index, target_index, crops)
        if not templates:
            return None

        offset_x, offset_y = offset if offset is not None else (0, 0)
        target: dict[str, Any] = {
            "template": templates[0] if len(templates) == 1 else templates,
            "action": action,
            "offset_x": offset_x,
            "offset_y": offset_y,
            "stay_on_confirm": False,
            "threshold": 0.85,
            "grayscale": True,
            "label": f"step {step_index} target {target_index}",
        }
        if scroll_dir is not None and scroll_anchor is not None:
            target["scrollValue"] = scroll_dir * SCROLL_AMOUNT
            target["scroll_point"] = list(scroll_anchor)

        with self._lock:
            self._current_targets.append(target)
        return target

    def _save_crops(
        self, slug: str, step_index: int, target_index: int, crops: list[np.ndarray]
    ) -> list[str]:
        templates: list[str] = []
        base_dir = os.path.join(RECORDED_DIR, slug)
        os.makedirs(base_dir, exist_ok=True)
        for i, crop in enumerate(crops):
            label = "main" if i == 0 else f"val{i}"
            data = crop.tobytes()
            h = hashlib.sha1(data).hexdigest()
            with self._lock:
                existing = self._file_hashes.get(h)
            if existing is not None:
                templates.append(f"templates/recorded/{slug}/{existing}")
                continue
            filename = f"{step_index:04d}_{target_index:02d}_{label}.png"
            path = os.path.join(base_dir, filename)
            cv2.imwrite(path, crop)
            with self._lock:
                self._file_hashes[h] = filename
            templates.append(f"templates/recorded/{slug}/{filename}")
        return templates

    def _default_name(self) -> str:
        return f"recorded {datetime.now().strftime('%Y-%m-%d %H%M')}"

    @staticmethod
    def _make_slug(name: str) -> str:
        safe = "".join(c if c.isalnum() or c in " ._-" else "_" for c in name)
        safe = safe.strip(" .")
        return safe or "recorded"

    def _start_listener(self) -> None:
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.start()

    def _stop_listener(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is not None:
            listener.stop()

    def _on_press(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        try:
            if key == TOGGLE_KEY:
                if self._on_toggle is not None:
                    self._on_toggle()
                return
            with self._lock:
                recording = self._state == "RECORDING"
            if not recording:
                return
            if key == CROP_KEY:
                if self._on_crop_request is not None:
                    self._on_crop_request()
            elif key == NEXT_KEY:
                if self._on_next_step is not None:
                    self._on_next_step()
        except Exception:
            pass
