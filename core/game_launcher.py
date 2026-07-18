import os
import time
import subprocess

import win32gui
import win32process

from core.constants import GAME_KEYWORDS


class GameLauncher:
    def __init__(self, logger):
        self.logger = logger

    def launch(self, exe_path):
        if not os.path.exists(exe_path):
            raise FileNotFoundError(f"Path not found: {exe_path}")

        process = subprocess.Popen(exe_path)
        self.logger.info(f"Game process started (PID: {process.pid})")

        hwnd = self._find_game_window(timeout=30)
        if hwnd is None:
            self.logger.warning("Game window not found by title; trying PID match")
            time.sleep(3)
            hwnd = self._find_hwnd_by_pid(process.pid)

        if hwnd is None:
            raise RuntimeError("Could not find game window")

        return process, hwnd

    def find_existing_window(self):
        return self.find_window_by_tab(GAME_KEYWORDS[0])

    def find_window_by_tab(self, tab_name: str = "", tab_pid: int | None = None):
        found = []

        def enum_callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            if tab_pid is not None:
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if found_pid == tab_pid:
                    title = win32gui.GetWindowText(hwnd)
                    found.append((hwnd, title))
                    return True
            if tab_name:
                title = win32gui.GetWindowText(hwnd)
                if tab_name in title:
                    found.append((hwnd, title))
            return True

        win32gui.EnumWindows(enum_callback, None)
        if found:
            hwnd, title = found[0]
            self.logger.info(f"Found window — HWND: {hwnd}, Title: \"{title}\"")
            return hwnd
        return None

    @staticmethod
    def get_window_title(hwnd):
        return win32gui.GetWindowText(hwnd) if hwnd else ""

    @staticmethod
    def list_visible_windows():
        result = []
        seen = set()

        def enum_callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            key = (pid, title)
            if key in seen:
                return True
            seen.add(key)
            result.append({"title": title, "pid": pid})
            return True

        win32gui.EnumWindows(enum_callback, None)
        return sorted(result, key=lambda w: w["title"].lower())

    def _find_game_window(self, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            hwnd = self.find_window_by_tab(GAME_KEYWORDS[0])
            if hwnd:
                return hwnd
            time.sleep(1)
        return None

    def _find_hwnd_by_pid(self, pid):
        return self.find_window_by_tab(tab_pid=pid)
