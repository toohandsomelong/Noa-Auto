import time
import threading

import win32gui
import win32process

from core.constants import GAME_KEYWORDS


class FocusWatcher:
    def __init__(self, check_interval=0.5):
        self._hwnd = None
        self._tab_name = ""
        self._tab_pid: int | None = None
        self._callback = None
        self._check_interval = check_interval
        self._stop_event = threading.Event()
        self._thread = None

    @property
    def hwnd(self):
        return self._hwnd

    @hwnd.setter
    def hwnd(self, value):
        self._hwnd = value

    def set_target(self, tab_name: str = "", tab_pid: int | None = None, hwnd: int | None = None):
        self._tab_name = tab_name
        self._tab_pid = tab_pid
        if hwnd is not None:
            self._hwnd = hwnd

    def clear_target(self):
        self._tab_name = ""
        self._tab_pid = None
        self._hwnd = None

    @property
    def foreground_title(self):
        return win32gui.GetWindowText(win32gui.GetForegroundWindow())

    @property
    def is_focused(self):
        fg = win32gui.GetForegroundWindow()
        fg_title = win32gui.GetWindowText(fg)
        if self._tab_name and self._tab_name in fg_title:
            return True
        for kw in GAME_KEYWORDS:
            if kw in fg_title:
                return True
        if (self._hwnd
            and win32gui.IsWindow(self._hwnd)
            and (fg == self._hwnd or win32gui.IsChild(self._hwnd, fg))):
            return True
        return False

    @property
    def is_window_alive(self):
        if not self._tab_name and self._tab_pid is None and not self._hwnd:
            return True

        def enum_callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            if self._tab_pid is not None:
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if found_pid == self._tab_pid:
                    found.append(True)
                    return True
            if self._tab_name:
                title = win32gui.GetWindowText(hwnd)
                if self._tab_name in title:
                    found.append(True)
                    return True
            if self._hwnd and win32gui.IsWindow(hwnd) and (hwnd == self._hwnd or win32gui.IsChild(self._hwnd, hwnd)):
                found.append(True)
                return True
            return True
        found = []
        win32gui.EnumWindows(enum_callback, None)
        return bool(found)

    def set_callback(self, callback):
        self._callback = callback

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self):
        was_focused = None
        while not self._stop_event.is_set():
            focused = self.is_focused
            if was_focused is not None and focused != was_focused and self._callback:
                self._callback(focused)
            was_focused = focused
            time.sleep(self._check_interval)
