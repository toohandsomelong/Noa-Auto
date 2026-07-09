import time
import threading

import win32gui

from core.constants import GAME_KEYWORDS

class FocusWatcher:
    def __init__(self, check_interval=0.5):
        self._hwnd = None
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

    @property
    def foreground_title(self):
        return win32gui.GetWindowText(win32gui.GetForegroundWindow())

    @property
    def is_focused(self):
        fg = win32gui.GetForegroundWindow()
        fg_title = win32gui.GetWindowText(fg)
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
        def enum_callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                for kw in GAME_KEYWORDS:
                    if kw in title:
                        found.append(True)
                        break
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
