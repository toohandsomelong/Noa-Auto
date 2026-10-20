from __future__ import annotations

import copy
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

from core.screen_bot import _capture, _load_template, resolve_capture_region


RECORDED_DIR = "templates/recorded"
TOGGLE_KEY = keyboard.Key.f8
CROP_KEY = keyboard.Key.f9
NEXT_KEY = keyboard.Key.f10
SCROLL_AMOUNT = 5


PREV_KEY = keyboard.Key.f7
UNDO_KEY = keyboard.Key.f6


class Recorder:
    def __init__(
        self,
        *,
        on_toggle: Callable[[], None] | None = None,
        on_crop_request: Callable[[], None] | None = None,
        on_next_step: Callable[[], None] | None = None,
        on_prev_step: Callable[[], None] | None = None,
        on_remove_target: Callable[[], None] | None = None,
        focus_watcher=None,
    ) -> None:
        self._state = "IDLE"
        self._lock = threading.Lock()
        self._listener: keyboard.Listener | None = None
        self._name: str | None = None
        self._slug: str | None = None
        self._plan_name: str | None = None
        self._editing = False
        self._edit_index = 0
        self._current_targets: list[dict[str, Any]] = []
        self._steps: list[dict[str, Any]] = []
        self._pressed_keys: set[Any] = set()
        self._file_hashes: dict[str, str] = {}
        self._on_toggle = on_toggle
        self._on_crop_request = on_crop_request
        self._on_next_step = on_next_step
        self._on_prev_step = on_prev_step
        self._on_remove_target = on_remove_target
        self._focus_watcher = focus_watcher
        self._last_region: dict[str, int] | None = None

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "name": self._name,
                "plan_name": self._plan_name,
                "editing": self._editing,
                "step_count": len(self._steps),
                "target_count": len(self._current_targets),
                "step_index": self._edit_index + 1,
                "steps": list(self._steps),
                "current_targets": list(self._current_targets),
            }

    def last_region(self) -> dict[str, int] | None:
        with self._lock:
            return self._last_region

    def start(self, name: str | None = None) -> bool:
        with self._lock:
            if self._state != "IDLE":
                return False
            self._state = "RECORDING"
            self._name = name or self._default_name()
            self._slug = self._make_slug(self._name)
            self._plan_name = None
            self._editing = False
            self._edit_index = 0
            self._current_targets = []
            self._steps = []
            self._pressed_keys = set()
            self._file_hashes = {}
        self._start_listener()
        return True

    def start_edit(self, name: str, plan: dict[str, Any]) -> bool:
        with self._lock:
            if self._state != "IDLE":
                return False
            self._state = "RECORDING"
            self._name = plan.get("name") or name
            self._slug = self._derive_slug(plan) or self._make_slug(name)
            self._plan_name = name
            self._editing = True
            self._steps = copy.deepcopy(plan.get("steps", []))
            self._edit_index = max(0, len(self._steps) - 1)
            self._current_targets = (
                self._steps[self._edit_index]["targets"]
                if self._steps
                else []
            )
            self._pressed_keys = set()
            self._file_hashes = {}
        self._start_listener()
        return True

    def stop(self) -> dict[str, Any] | None:
        with self._lock:
            if self._state == "IDLE":
                return None
            if self._edit_index >= len(self._steps) and self._current_targets:
                self._commit_pending_locked()
            self._state = "IDLE"
            steps = [step for step in self._steps if step.get("targets")]
            name = self._name or self._default_name()
            plan_name = self._plan_name
            editing = self._editing
            self._plan_name = None
            self._editing = False
            self._stop_listener()
        if not steps:
            return None
        result: dict[str, Any] = {"name": name, "steps": steps}
        if editing:
            result["plan_name"] = plan_name
            result["editing"] = True
        return result

    def next_step(self) -> dict[str, Any] | None:
        with self._lock:
            if self._state != "RECORDING":
                return None
            if self._edit_index >= len(self._steps):
                if not self._current_targets:
                    return None
                self._commit_pending_locked()
            if self._edit_index + 1 < len(self._steps):
                self._edit_index += 1
                step = self._steps[self._edit_index]
                self._current_targets = step["targets"]
                return step
            self._edit_index = len(self._steps)
            self._current_targets = []
            return self._steps[-1]

    def previous_step(self) -> dict[str, Any] | None:
        with self._lock:
            if self._state != "RECORDING" or self._edit_index == 0:
                return None
            if self._edit_index >= len(self._steps) and self._current_targets:
                self._commit_pending_locked()
            self._edit_index -= 1
            step = self._steps[self._edit_index]
            self._current_targets = step["targets"]
        return step

    def _commit_pending_locked(self) -> dict[str, Any]:
        step: dict[str, Any] = {
            "type": "click",
            "threshold": 0.85,
            "grayscale": True,
            "label": f"step {self._edit_index + 1}",
            "targets": list(self._current_targets),
        }
        self._steps.append(step)
        self._edit_index = len(self._steps) - 1
        self._current_targets = step["targets"]
        return step

    def remove_target(self, index: int) -> dict[str, Any] | None:
        with self._lock:
            if self._state != "RECORDING" or not self._current_targets:
                return None
            if index < 0:
                index = len(self._current_targets) + index
            if index < 0 or index >= len(self._current_targets):
                return None
            target = self._current_targets.pop(index)
            self._relabel_targets_locked()
        return target

    def _relabel_targets_locked(self) -> None:
        for i, target in enumerate(self._current_targets, start=1):
            target["label"] = f"step {self._edit_index + 1} target {i}"

    def begin_crop(self) -> tuple[np.ndarray, dict[str, int]] | None:
        with self._lock:
            state = self._state
        if state != "RECORDING":
            return None
        sct = mss.MSS()
        try:
            resolved = resolve_capture_region(sct, self._focus_watcher)
            if resolved is None:
                return None
            region, _origin = resolved
            self._last_region = region
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
            step_index = self._edit_index + 1
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
            if os.path.exists(path):
                with open(path, "rb") as f:
                    existing_hash = hashlib.sha1(f.read()).hexdigest()
                if existing_hash != h:
                    _load_template.cache_clear()
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

    @staticmethod
    def _derive_slug(plan: dict[str, Any]) -> str:
        steps = plan.get("steps", []) if isinstance(plan, dict) else []
        for step in steps:
            for target in step.get("targets", []):
                template = target.get("template")
                paths = template if isinstance(template, list) else [template]
                for path in paths:
                    if isinstance(path, str) and path.startswith("templates/recorded/"):
                        parts = path.split("/")
                        if len(parts) >= 3:
                            return parts[2]
        return ""

    def _start_listener(self) -> None:
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()

    def _stop_listener(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is not None:
            listener.stop()

    def _on_release(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        try:
            self._pressed_keys.discard(key)
        except Exception:
            pass

    def _on_press(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        try:
            if key in self._pressed_keys:
                return
            self._pressed_keys.add(key)
            if key == TOGGLE_KEY:
                if self._on_toggle is not None:
                    self._on_toggle()
                return
            with self._lock:
                recording = self._state == "RECORDING"
            if not recording:
                return
            if key == UNDO_KEY:
                if self._on_remove_target is not None:
                    self._on_remove_target()
            elif key == PREV_KEY:
                if self._on_prev_step is not None:
                    self._on_prev_step()
            elif key == CROP_KEY:
                if self._on_crop_request is not None:
                    self._on_crop_request()
            elif key == NEXT_KEY:
                if self._on_next_step is not None:
                    self._on_next_step()
        except Exception:
            pass
