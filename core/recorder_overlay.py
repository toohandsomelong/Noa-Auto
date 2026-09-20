from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np

from core.logger import Logger


try:
    import tkinter as tk
    from PIL import Image, ImageTk
except Exception:  # pragma: no cover - headless fallback
    tk = None  # type: ignore
    Image = None  # type: ignore
    ImageTk = None  # type: ignore


ACTION_LEFT = "left_click"
ACTION_RIGHT = "right_click"
ACTION_CONTINUE = "continue"
ACTION_SCROLL = "scroll"

BUTTON_HEIGHT = 1
BAR_BUTTON_WIDTH = 12
TOOLBAR_BUTTON_WIDTH = 9

MIN_RECT = 4
EDGE_MARGIN = 6
CROSSHAIR_RADIUS = 12
HANDLE_SIZE = 4
CAPTURE_HIDE_DELAY_MS = 120


class OverlayController:
    def __init__(self) -> None:
        self.state = "IDLE"
        self.frame: np.ndarray | None = None
        self.region: dict[str, int] | None = None
        self.rects: list[tuple[int, int, int, int]] = []
        self.action = ACTION_LEFT
        self.scroll_dir = -1
        self.scroll_anchor: tuple[int, int] | None = None
        self.offset: tuple[int, int] = (0, 0)

    def show(self, frame: np.ndarray, region: dict[str, int]) -> None:
        self.state = "VISIBLE"
        self.frame = frame
        self.region = region
        self.rects = []
        self.action = ACTION_LEFT
        self.scroll_dir = -1
        self.scroll_anchor = None
        self.offset = (0, 0)

    def hide(self) -> None:
        self.state = "IDLE"
        self.frame = None
        self.region = None
        self.rects = []
        self.scroll_anchor = None

    def add_rect(self, rect: tuple[int, int, int, int]) -> None:
        x1, y1, x2, y2 = rect
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        if x2 - x1 < MIN_RECT or y2 - y1 < MIN_RECT:
            return
        self.rects.append((x1, y1, x2, y2))

    def remove_rect(self, index: int) -> None:
        if 0 <= index < len(self.rects):
            self.rects.pop(index)

    def clear_rects(self) -> None:
        self.rects = []
        self.scroll_anchor = None

    def set_action(self, action: str) -> None:
        self.action = action
        if action != ACTION_SCROLL:
            self.scroll_anchor = None

    def set_scroll_dir(self, direction: int) -> None:
        self.scroll_dir = 1 if direction > 0 else -1

    def set_scroll_anchor(self, point: tuple[int, int]) -> None:
        self.scroll_anchor = point

    def set_offset(self, x: int, y: int) -> None:
        self.offset = (x, y)

    def get_offset(self) -> tuple[int, int]:
        return self.offset

    def _frame_size(self) -> tuple[int, int] | None:
        if self.frame is None:
            return None
        return self.frame.shape[1], self.frame.shape[0]

    def main_center(self) -> tuple[int, int] | None:
        if not self.rects:
            return None
        x1, y1, x2, y2 = self.rects[0]
        return (x1 + x2) // 2, (y1 + y2) // 2

    def crosshair_point(self) -> tuple[int, int] | None:
        center = self.main_center()
        if center is None:
            return None
        x = center[0] + self.offset[0]
        y = center[1] + self.offset[1]
        size = self._frame_size()
        if size is not None:
            x = max(0, min(x, size[0] - 1))
            y = max(0, min(y, size[1] - 1))
        return x, y

    def hit_test_rect(self, x: int, y: int) -> int | None:
        for index in range(len(self.rects) - 1, -1, -1):
            x1, y1, x2, y2 = self.rects[index]
            if x1 <= x <= x2 and y1 <= y <= y2:
                return index
        return None

    def hit_test_edge(
        self, x: int, y: int, margin: int = EDGE_MARGIN
    ) -> tuple[int, frozenset[str]] | None:
        for index in range(len(self.rects) - 1, -1, -1):
            x1, y1, x2, y2 = self.rects[index]
            if not (x1 - margin <= x <= x2 + margin and y1 - margin <= y <= y2 + margin):
                continue
            edges: set[str] = set()
            if abs(x - x1) <= margin:
                edges.add("left")
            if abs(x - x2) <= margin:
                edges.add("right")
            if abs(y - y1) <= margin:
                edges.add("top")
            if abs(y - y2) <= margin:
                edges.add("bottom")
            if edges:
                return index, frozenset(edges)
        return None

    def move_rect(self, index: int, dx: int, dy: int) -> None:
        if not (0 <= index < len(self.rects)):
            return
        x1, y1, x2, y2 = self.rects[index]
        width = x2 - x1
        height = y2 - y1
        size = self._frame_size()
        x1 += dx
        y1 += dy
        if size is not None:
            fw, fh = size
            x1 = max(0, min(x1, fw - width))
            y1 = max(0, min(y1, fh - height))
        self.rects[index] = (x1, y1, x1 + width, y1 + height)

    def resize_rect(self, index: int, edges: frozenset[str], x: int, y: int) -> None:
        if not (0 <= index < len(self.rects)):
            return
        x1, y1, x2, y2 = self.rects[index]
        if "left" in edges:
            x1 = x
        if "right" in edges:
            x2 = x
        if "top" in edges:
            y1 = y
        if "bottom" in edges:
            y2 = y
        size = self._frame_size()
        if size is not None:
            fw, fh = size
            x1, x2 = max(0, min(x1, fw)), max(0, min(x2, fw))
            y1, y2 = max(0, min(y1, fh)), max(0, min(y2, fh))
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        if x2 - x1 < MIN_RECT or y2 - y1 < MIN_RECT:
            return
        self.rects[index] = (x1, y1, x2, y2)

    def can_confirm(self) -> bool:
        return self.state == "VISIBLE" and len(self.rects) > 0

    def get_crops(self) -> list[np.ndarray] | None:
        if self.frame is None or not self.rects:
            return None
        crops = []
        for x1, y1, x2, y2 in self.rects:
            x1 = max(0, min(x1, self.frame.shape[1] - 1))
            x2 = max(0, min(x2, self.frame.shape[1]))
            y1 = max(0, min(y1, self.frame.shape[0] - 1))
            y2 = max(0, min(y2, self.frame.shape[0]))
            if y2 > y1 and x2 > x1:
                crops.append(self.frame[y1:y2, x1:x2].copy())
        return crops if crops else None

    def get_scroll_info(self) -> tuple[int | None, tuple[int, int] | None]:
        if self.action != ACTION_SCROLL:
            return None, None
        return self.scroll_dir, self.scroll_anchor


class RecorderOverlay:
    def __init__(
        self,
        on_capture: Callable[[], None] | None = None,
        on_confirm: Callable[[list[np.ndarray], str, int | None, tuple[int, int] | None, tuple[int, int]], None] | None = None,
        on_next_step: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        logger: Logger | None = None,
    ) -> None:
        self._controller = OverlayController()
        self._command_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._on_capture = on_capture
        self._on_confirm = on_confirm
        self._on_next_step = on_next_step
        self._on_stop = on_stop
        self._logger = logger
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> bool:
        if self._thread is not None:
            return False
        if tk is None:
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._tk_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        self._put({"cmd": "destroy"})
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def show_bar(self, step: int = 1, targets: int = 0) -> None:
        self._put({"cmd": "show_bar", "step": step, "targets": targets})

    def hide_bar(self) -> None:
        self._put({"cmd": "hide_bar"})

    def request_crop(self) -> None:
        self._put({"cmd": "request_crop"})

    def show_crop(self, frame: np.ndarray, region: dict[str, int]) -> None:
        self._controller.show(frame, region)
        self._put({"cmd": "show_crop", "frame": frame, "region": region})

    def hide_crop(self) -> None:
        self._controller.hide()
        self._put({"cmd": "hide_crop"})

    def set_counts(self, step: int, targets: int) -> None:
        self._put({"cmd": "set_counts", "step": step, "targets": targets})

    def _put(self, item: dict[str, Any]) -> None:
        self._command_queue.put(item)

    def _tk_loop(self) -> None:
        try:
            view = RecorderOverlayTk(
                self._command_queue,
                self._controller,
                on_capture=self._on_capture,
                on_confirm=self._on_confirm,
                on_next_step=self._on_next_step,
                on_stop=self._on_stop,
                logger=self._logger,
            )
            view.run()
        except Exception as exc:
            if self._logger is not None:
                self._logger.error(f"Recorder overlay crashed: {exc}")


class RecorderOverlayTk:
    def __init__(
        self,
        command_queue: queue.Queue[dict[str, Any]],
        controller: OverlayController,
        on_capture: Callable[[], None] | None = None,
        on_confirm: Callable[[list[np.ndarray], str, int | None, tuple[int, int] | None, tuple[int, int]], None] | None = None,
        on_next_step: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        logger: Logger | None = None,
    ) -> None:
        self._cmd_q = command_queue
        self._ctrl = controller
        self._on_capture = on_capture
        self._on_confirm = on_confirm
        self._on_next_step = on_next_step
        self._on_stop = on_stop
        self._logger = logger

        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        self._root = tk.Tk()
        self._root.withdraw()

        self._bar: tk.Toplevel | None = None
        self._crop_win: tk.Toplevel | None = None
        self._toolbar_win: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._canvas_image: int | None = None
        self._rect_items: list[int] = []
        self._anchor_item: int | None = None
        self._crosshair_items: list[int] = []
        self._handle_items: list[int] = []
        self._drag_start: tuple[int, int] | None = None
        self._drag_rect: int | None = None
        self._drag_mode: str | None = None
        self._drag_index: int | None = None
        self._drag_edges: frozenset[str] | None = None
        self._drag_last: tuple[int, int] | None = None
        self._action_var = tk.StringVar(value=ACTION_LEFT)
        self._scroll_var = tk.StringVar(value="down")
        self._after_id: str | None = None

    def run(self) -> None:
        self._schedule_poll()
        self._root.mainloop()

    def _schedule_poll(self) -> None:
        try:
            self._poll()
        except Exception as exc:
            if self._logger is not None:
                self._logger.error(f"Recorder overlay poll error: {exc}")
        try:
            if self._root.winfo_exists():
                self._after_id = self._root.after(50, self._schedule_poll)
        except Exception:
            pass

    def _poll(self) -> None:
        try:
            while True:
                item = self._cmd_q.get_nowait()
                self._handle_command(item)
        except queue.Empty:
            pass

    def _handle_command(self, item: dict[str, Any]) -> None:
        cmd = item.get("cmd")
        if cmd == "destroy":
            self._destroy()
        elif cmd == "show_bar":
            self._show_bar(item.get("step", 1), item.get("targets", 0))
        elif cmd == "hide_bar":
            self._hide_bar()
        elif cmd == "set_counts":
            self._set_counts(item.get("step", 1), item.get("targets", 0))
        elif cmd == "request_crop":
            self._request_crop()
        elif cmd == "show_crop":
            self._show_crop(item["frame"], item["region"])
        elif cmd == "hide_crop":
            self._hide_crop()

    def _destroy(self) -> None:
        if self._after_id:
            self._root.after_cancel(self._after_id)
            self._after_id = None
        self._hide_crop()
        self._hide_bar()
        self._root.quit()

    def _show_bar(self, step: int, targets: int) -> None:
        if self._bar is not None:
            self._set_counts(step, targets)
            self._bar.deiconify()
            return
        self._bar = tk.Toplevel(self._root)
        self._bar.overrideredirect(True)
        self._bar.attributes("-topmost", True)
        self._bar.attributes("-alpha", 0.9)
        self._bar.configure(bg="#1e1e1e")

        frame = tk.Frame(self._bar, bg="#1e1e1e")
        frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        self._rec_label = tk.Label(
            frame, text="REC", fg="red", bg="#1e1e1e", font=("Consolas", 10, "bold")
        )
        self._rec_label.pack(side=tk.LEFT)

        self._count_label = tk.Label(
            frame,
            text=f"step {step} · targets {targets}",
            fg="white",
            bg="#1e1e1e",
            font=("Consolas", 10),
        )
        self._count_label.pack(side=tk.LEFT, padx=(10, 0))

        add_btn = tk.Button(
            frame, text="Add target (F9)", command=self._enqueue_crop, bg="#333", fg="white", bd=0,
            width=BAR_BUTTON_WIDTH, height=BUTTON_HEIGHT,
        )
        add_btn.pack(side=tk.RIGHT, padx=(4, 0))

        next_btn = tk.Button(
            frame, text="Next step (F10)", command=self._request_next_step, bg="#553", fg="white", bd=0,
            width=BAR_BUTTON_WIDTH, height=BUTTON_HEIGHT,
        )
        next_btn.pack(side=tk.RIGHT, padx=(4, 0))

        stop_btn = tk.Button(
            frame, text="Stop (F8)", command=self._request_stop, bg="#722", fg="white", bd=0,
            width=BAR_BUTTON_WIDTH, height=BUTTON_HEIGHT,
        )
        stop_btn.pack(side=tk.RIGHT, padx=(4, 0))

        self._fit_bar()

    def _fit_bar(self) -> None:
        if self._bar is None:
            return
        self._bar.update_idletasks()
        width = self._bar.winfo_reqwidth()
        height = self._bar.winfo_reqheight()
        screen_w = self._bar.winfo_screenwidth()
        x = max(0, (screen_w - width) // 2)
        self._bar.geometry(f"{width}x{height}+{x}+0")

    def _fit_toolbar(self, top: int) -> None:
        if self._toolbar_win is None:
            return
        self._toolbar_win.update_idletasks()
        width = self._toolbar_win.winfo_screenwidth()
        height = self._toolbar_win.winfo_reqheight()
        y = max(0, top)
        self._toolbar_win.geometry(f"{width}x{height}+0+{y}")
        self._toolbar_win.lift()

    def _lift_toolbar(self) -> None:
        if self._toolbar_win is not None:
            self._toolbar_win.lift()

    def _hide_bar(self) -> None:
        if self._bar is not None:
            self._bar.withdraw()

    def _set_counts(self, step: int, targets: int) -> None:
        if self._count_label is not None:
            self._count_label.config(text=f"step {step} · targets {targets}")
            self._fit_bar()

    def _enqueue_crop(self) -> None:
        self._cmd_q.put({"cmd": "request_crop"})

    def _request_crop(self) -> None:
        self._hide_bar()
        self._hide_crop()
        if self._root.winfo_exists():
            self._root.after(CAPTURE_HIDE_DELAY_MS, self._do_capture)

    def _do_capture(self) -> None:
        try:
            if self._on_capture is not None:
                result = self._on_capture()
                if isinstance(result, dict) and not result.get("ok", True) and self._logger is not None:
                    self._logger.warning(f"Recorder capture unavailable: {result.get('error')}")
        except Exception as exc:
            if self._logger is not None:
                self._logger.error(f"Recorder capture failed: {exc}")
        finally:
            if self._bar is not None:
                self._bar.deiconify()
                self._fit_bar()

    def _request_next_step(self) -> None:
        if self._on_next_step is not None:
            self._on_next_step()

    def _request_stop(self) -> None:
        if self._on_stop is not None:
            self._on_stop()

    def _show_crop(self, frame: np.ndarray, region: dict[str, int]) -> None:
        if self._crop_win is not None:
            self._hide_crop()

        try:
            self._crop_win = tk.Toplevel(self._root)
            self._crop_win.overrideredirect(True)
            self._crop_win.attributes("-topmost", True)
            left = region["left"]
            top = region["top"]
            width = region["width"]
            height = region["height"]
            self._crop_win.geometry(f"{width}x{height}+{left}+{top}")

            self._toolbar_win = tk.Toplevel(self._root)
            self._toolbar_win.overrideredirect(True)
            self._toolbar_win.attributes("-topmost", True)
            self._toolbar_win.configure(bg="#1e1e1e")
            self._toolbar_win.transient(self._crop_win)

            toolbar = tk.Frame(self._toolbar_win, bg="#1e1e1e")
            toolbar.pack(fill=tk.X, expand=True)

            tk.Button(toolbar, text="Left", command=lambda: self._set_action(ACTION_LEFT), bg="#333", fg="white", bd=0, width=TOOLBAR_BUTTON_WIDTH, height=BUTTON_HEIGHT).pack(side=tk.LEFT, padx=2)
            tk.Button(toolbar, text="Right", command=lambda: self._set_action(ACTION_RIGHT), bg="#333", fg="white", bd=0, width=TOOLBAR_BUTTON_WIDTH, height=BUTTON_HEIGHT).pack(side=tk.LEFT, padx=2)
            tk.Button(toolbar, text="Continue", command=lambda: self._set_action(ACTION_CONTINUE), bg="#333", fg="white", bd=0, width=TOOLBAR_BUTTON_WIDTH, height=BUTTON_HEIGHT).pack(side=tk.LEFT, padx=2)

            scroll_frame = tk.Frame(toolbar, bg="#1e1e1e")
            scroll_frame.pack(side=tk.LEFT, padx=(6, 0))
            tk.Button(scroll_frame, text="Scroll", command=lambda: self._set_action(ACTION_SCROLL), bg="#333", fg="white", bd=0, width=TOOLBAR_BUTTON_WIDTH, height=BUTTON_HEIGHT).pack(side=tk.LEFT)
            tk.Radiobutton(scroll_frame, text="Up", variable=self._scroll_var, value="up", bg="#1e1e1e", fg="white", selectcolor="#333").pack(side=tk.LEFT)
            tk.Radiobutton(scroll_frame, text="Down", variable=self._scroll_var, value="down", bg="#1e1e1e", fg="white", selectcolor="#333").pack(side=tk.LEFT)

            tk.Button(toolbar, text="Center", command=self._center_offset, bg="#553", fg="white", bd=0, width=TOOLBAR_BUTTON_WIDTH, height=BUTTON_HEIGHT).pack(side=tk.LEFT, padx=(6, 0))

            tk.Button(toolbar, text="Clear", command=self._clear_rects, bg="#333", fg="white", bd=0, width=TOOLBAR_BUTTON_WIDTH, height=BUTTON_HEIGHT).pack(side=tk.RIGHT, padx=2)
            tk.Button(toolbar, text="Cancel", command=self._confirm_cancel, bg="#722", fg="white", bd=0, width=TOOLBAR_BUTTON_WIDTH, height=BUTTON_HEIGHT).pack(side=tk.RIGHT, padx=2)
            tk.Button(toolbar, text="Confirm", command=self._confirm_crop, bg="#272", fg="white", bd=0, width=TOOLBAR_BUTTON_WIDTH, height=BUTTON_HEIGHT).pack(side=tk.RIGHT, padx=2)

            self._fit_toolbar(top)

            self._canvas = tk.Canvas(self._crop_win, bg="black", highlightthickness=0)
            self._canvas.pack(fill=tk.BOTH, expand=True)

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil = Image.fromarray(rgb)
            self._photo = ImageTk.PhotoImage(image=pil)
            self._canvas_image = self._canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)

            self._canvas.bind("<ButtonPress-1>", self._on_press)
            self._canvas.bind("<B1-Motion>", self._on_drag)
            self._canvas.bind("<ButtonRelease-1>", self._on_release)
            self._canvas.bind("<ButtonPress-3>", self._on_right_press)
            self._crop_win.bind("<FocusIn>", lambda _e: self._lift_toolbar(), add="+")
            self._crop_win.bind("<Map>", lambda _e: self._lift_toolbar(), add="+")
            self._crop_win.bind("<ButtonPress>", lambda _e: self._lift_toolbar(), add="+")
            self._root.after_idle(self._lift_toolbar)
            self._crop_win.bind("<Return>", lambda _e: self._confirm_crop())
            self._crop_win.bind("<Escape>", lambda _e: self._confirm_cancel())
        except Exception as exc:
            if self._logger is not None:
                self._logger.error(f"Failed to open crop overlay: {exc}")
            self._hide_crop()

    def _hide_crop(self) -> None:
        self._ctrl.hide()
        if self._toolbar_win is not None:
            self._toolbar_win.destroy()
            self._toolbar_win = None
        if self._crop_win is not None:
            self._crop_win.destroy()
            self._crop_win = None
        self._canvas = None
        self._photo = None
        self._canvas_image = None
        self._rect_items = []
        self._anchor_item = None
        self._crosshair_items = []
        self._handle_items = []
        self._drag_start = None
        self._drag_rect = None
        self._drag_mode = None
        self._drag_index = None
        self._drag_edges = None
        self._drag_last = None

    def _set_action(self, action: str) -> None:
        self._action_var.set(action)
        self._ctrl.set_action(action)
        if action == ACTION_SCROLL:
            self._ctrl.set_scroll_dir(1 if self._scroll_var.get() == "up" else -1)

    def _clear_rects(self) -> None:
        self._ctrl.clear_rects()
        self._redraw_rects()

    def _center_offset(self) -> None:
        self._ctrl.set_offset(0, 0)
        self._redraw_rects()

    def _redraw_rects(self) -> None:
        if self._canvas is None:
            return
        for item in self._rect_items + self._handle_items + self._crosshair_items:
            self._canvas.delete(item)
        self._rect_items = []
        self._handle_items = []
        self._crosshair_items = []
        for i, (x1, y1, x2, y2) in enumerate(self._ctrl.rects):
            color = "red" if i == 0 else "cyan"
            item = self._canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=2)
            self._rect_items.append(item)
        if self._ctrl.rects:
            x1, y1, x2, y2 = self._ctrl.rects[0]
            for cx, cy in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
                handle = self._canvas.create_rectangle(
                    cx - HANDLE_SIZE, cy - HANDLE_SIZE, cx + HANDLE_SIZE, cy + HANDLE_SIZE,
                    fill="red", outline="white",
                )
                self._handle_items.append(handle)
            crosshair = self._ctrl.crosshair_point()
            if crosshair is not None:
                hx, hy = crosshair
                self._crosshair_items.append(self._canvas.create_line(hx - 8, hy, hx + 8, hy, fill="orange", width=2))
                self._crosshair_items.append(self._canvas.create_line(hx, hy - 8, hx, hy + 8, fill="orange", width=2))
                self._crosshair_items.append(self._canvas.create_oval(hx - 3, hy - 3, hx + 3, hy + 3, outline="orange", width=1))
        if self._anchor_item is not None:
            self._canvas.delete(self._anchor_item)
            self._anchor_item = None
        if self._ctrl.scroll_anchor is not None:
            ax, ay = self._ctrl.scroll_anchor
            self._anchor_item = self._canvas.create_oval(ax - 5, ay - 5, ax + 5, ay + 5, outline="yellow", width=2)

    def _on_press(self, event: tk.Event) -> None:  # type: ignore[name-defined]
        self._lift_toolbar()
        if self._canvas is None:
            return
        if self._action_var.get() == ACTION_SCROLL and len(self._ctrl.rects) > 0:
            self._ctrl.set_scroll_anchor((event.x, event.y))
            self._redraw_rects()
            return
        crosshair = self._ctrl.crosshair_point()
        if (
            crosshair is not None
            and abs(event.x - crosshair[0]) <= CROSSHAIR_RADIUS
            and abs(event.y - crosshair[1]) <= CROSSHAIR_RADIUS
        ):
            self._drag_mode = "offset"
            self._drag_last = (event.x, event.y)
            return
        edge = self._ctrl.hit_test_edge(event.x, event.y)
        if edge is not None:
            self._drag_mode = "resize"
            self._drag_index, self._drag_edges = edge
            return
        index = self._ctrl.hit_test_rect(event.x, event.y)
        if index is not None:
            self._drag_mode = "move"
            self._drag_index = index
            self._drag_last = (event.x, event.y)
            return
        self._drag_mode = "draw"
        self._drag_start = (event.x, event.y)
        self._drag_rect = self._canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="red", width=2)

    def _on_drag(self, event: tk.Event) -> None:  # type: ignore[name-defined]
        if self._canvas is None:
            return
        if self._drag_mode == "draw":
            if self._drag_rect is None or self._drag_start is None:
                return
            x1, y1 = self._drag_start
            self._canvas.coords(self._drag_rect, x1, y1, event.x, event.y)
            return
        if self._drag_mode == "offset":
            if self._drag_last is None:
                return
            dx = event.x - self._drag_last[0]
            dy = event.y - self._drag_last[1]
            ox, oy = self._ctrl.get_offset()
            self._ctrl.set_offset(ox + dx, oy + dy)
            self._drag_last = (event.x, event.y)
            self._redraw_rects()
            return
        if self._drag_mode == "move":
            if self._drag_index is None or self._drag_last is None:
                return
            dx = event.x - self._drag_last[0]
            dy = event.y - self._drag_last[1]
            self._ctrl.move_rect(self._drag_index, dx, dy)
            self._drag_last = (event.x, event.y)
            self._redraw_rects()
            return
        if self._drag_mode == "resize":
            if self._drag_index is None or self._drag_edges is None:
                return
            self._ctrl.resize_rect(self._drag_index, self._drag_edges, event.x, event.y)
            self._redraw_rects()

    def _on_release(self, event: tk.Event) -> None:  # type: ignore[name-defined]
        if self._drag_mode == "draw" and self._drag_start is not None and self._drag_rect is not None:
            x1, y1 = self._drag_start
            self._canvas.delete(self._drag_rect)
            self._ctrl.add_rect((x1, y1, event.x, event.y))
            self._redraw_rects()
        self._reset_drag()

    def _reset_drag(self) -> None:
        self._drag_start = None
        self._drag_rect = None
        self._drag_mode = None
        self._drag_index = None
        self._drag_edges = None
        self._drag_last = None

    def _on_right_press(self, event: tk.Event) -> None:  # type: ignore[name-defined]
        self._lift_toolbar()
        if self._canvas is None:
            return
        index = self._ctrl.hit_test_rect(event.x, event.y)
        if index is not None:
            self._ctrl.remove_rect(index)
            self._redraw_rects()

    def _confirm_crop(self) -> None:
        if not self._ctrl.can_confirm():
            return
        crops = self._ctrl.get_crops()
        if crops is None:
            return
        action = self._ctrl.action
        scroll_dir, scroll_anchor = self._ctrl.get_scroll_info()
        if action == ACTION_SCROLL and scroll_anchor is None:
            return
        if self._on_confirm is not None:
            self._on_confirm(crops, action, scroll_dir, scroll_anchor, self._ctrl.get_offset())
        self._hide_crop()

    def _confirm_cancel(self) -> None:
        self._hide_crop()
