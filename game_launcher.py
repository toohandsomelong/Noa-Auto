import os
import time
import subprocess

import win32gui
import win32process


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

    def _find_game_window(self, timeout=30):
        keywords = ["ウマ娘", "Uma Musume", "Umamusume", "umamusume"]
        deadline = time.time() + timeout
        while time.time() < deadline:
            found = []
            def enum_callback(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    for kw in keywords:
                        if kw in title:
                            found.append((hwnd, title))
                            return False
                return True
            win32gui.EnumWindows(enum_callback, None)
            if found:
                hwnd, title = found[0]
                self.logger.info(f"Found window — HWND: {hwnd}, Title: \"{title}\"")
                return hwnd
            time.sleep(1)
        return None

    def _find_hwnd_by_pid(self, pid):
        found = []
        def enum_callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if found_pid == pid:
                    found.append(hwnd)
            return True
        win32gui.EnumWindows(enum_callback, None)
        return found[0] if found else None
