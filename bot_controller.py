from __future__ import annotations

import json
import os
import string
import subprocess
import threading
import time
from collections.abc import Callable

from focus_watcher import FocusWatcher
from game_launcher import GameLauncher
from logger import Logger
from screen_bot import ScreenBot
from state_manager import BotState, StateManager

CONFIG_FILE = "config.json"


class BotController:
    def __init__(
        self,
        logger: Logger,
        state_manager: StateManager,
        game_launcher: GameLauncher,
        focus_watcher: FocusWatcher,
        screen_bot: ScreenBot | None = None,
    ) -> None:
        self.logger = logger
        self.state_manager = state_manager
        self.game_launcher = game_launcher
        self.focus_watcher = focus_watcher
        self.screen_bot = screen_bot
        self._process: subprocess.Popen[bytes] | None = None
        self._hwnd: int | None = None

        self._log_listeners: list[Callable[[str], None]] = []
        self._state_listeners: list[Callable[[dict], None]] = []

        self._flush_stop = threading.Event()
        self._flush_thread: threading.Thread | None = None

        self.logger.on_log(self._on_log_line)
        self.state_manager.on_state_change(self._on_state_change)

    def on_log_event(self, listener: Callable[[str], None]) -> None:
        self._log_listeners.append(listener)

    def on_state_event(self, listener: Callable[[dict], None]) -> None:
        self._state_listeners.append(listener)

    def start_flush(self) -> None:
        if self._flush_thread is not None:
            return
        self._flush_stop.clear()
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def stop_flush(self) -> None:
        self._flush_stop.set()
        if self._flush_thread:
            self._flush_thread.join(timeout=3)
            self._flush_thread = None

    def _flush_loop(self) -> None:
        while not self._flush_stop.is_set():
            self.logger.flush()
            time.sleep(0.05)

    def _on_log_line(self, line: str) -> None:
        for listener in self._log_listeners:
            try:
                listener(line)
            except Exception:
                pass

    def _on_state_change(self, state: BotState) -> None:
        data = {"type": "state", "state": state.value}
        for listener in self._state_listeners:
            try:
                listener(data)
            except Exception:
                pass

    def get_state(self) -> dict:
        return {
            "state": self.state_manager.state.value,
            "game_path": self._load_config_path(),
        }

    def start(self, path: str) -> None:
        if self.state_manager.is_active():
            self.logger.warning("Game already running")
            return

        if not path:
            self.logger.error("No game path configured")
            return
        if not os.path.exists(path):
            self.logger.error(f"Path not found: {path}")
            return

        self._save_config(path)

        existing_hwnd = self.game_launcher.find_existing_window()
        if existing_hwnd is not None:
            self.logger.warning("Game already running; reusing existing window")
            self.state_manager.state = BotState.RUNNING
            threading.Thread(
                target=self._attach, args=(existing_hwnd,), daemon=True
            ).start()
            return

        self.logger.info(f"Starting game: {path}")
        self.state_manager.state = BotState.RUNNING
        threading.Thread(target=self._launch, args=(path,), daemon=True).start()

    def stop(self) -> None:
        self.logger.info("User requested stop")
        self._cleanup()

    def _attach(self, hwnd: int) -> None:
        self._hwnd = hwnd
        self.focus_watcher.hwnd = hwnd
        self.focus_watcher.set_callback(self._on_focus_change)

        self.logger.info(f"Game HWND: {hwnd}")
        self.logger.info(
            f'Foreground window: "{self.focus_watcher.foreground_title}"'
        )

        if self.focus_watcher.is_focused:
            self.state_manager.state = BotState.RUNNING
            self.logger.state("RUNNING — game focused")
        else:
            self.state_manager.state = BotState.PAUSED
            self.logger.state("PAUSED — game unfocused")

        self.focus_watcher.start()
        if self.screen_bot is not None:
            self.screen_bot.start()
        self._monitor_process()

    def _launch(self, path: str) -> None:
        try:
            process, hwnd = self.game_launcher.launch(path)
        except FileNotFoundError as e:
            self.logger.error(str(e))
            self._reset_state()
            return
        except RuntimeError as e:
            self.logger.error(str(e))
            self._reset_state()
            return
        except Exception as e:
            self.logger.error(f"Launch failed: {e}")
            self._reset_state()
            return

        self._process = process
        self._hwnd = hwnd
        self.focus_watcher.hwnd = hwnd
        self.focus_watcher.set_callback(self._on_focus_change)

        self.logger.info(f"Game PID: {process.pid}")
        self.logger.info(f"Game HWND: {hwnd}")
        self.logger.info(
            f'Foreground window: "{self.focus_watcher.foreground_title}"'
        )

        if self.focus_watcher.is_focused:
            self.state_manager.state = BotState.RUNNING
            self.logger.state("RUNNING — game focused")
        else:
            self.state_manager.state = BotState.PAUSED
            self.logger.state("PAUSED — game unfocused")

        self.focus_watcher.start()
        if self.screen_bot is not None:
            self.screen_bot.start()
        self._monitor_process()

    def _monitor_process(self) -> None:
        def monitor() -> None:
            while self.state_manager.state != BotState.IDLE:
                if not self.focus_watcher.is_window_alive:
                    self.logger.state("STOPPED — game window closed")
                    self.state_manager.state = BotState.STOPPED
                    self._cleanup()
                    break
                time.sleep(1)

        threading.Thread(target=monitor, daemon=True).start()

    def _on_focus_change(self, focused: bool) -> None:
        if focused:
            self.state_manager.state = BotState.RUNNING
            self.logger.state("RESUMED — game focused")
        else:
            self.state_manager.state = BotState.PAUSED
            self.logger.state("PAUSED — game unfocused")

    def _cleanup(self) -> None:
        if self.screen_bot is not None:
            self.screen_bot.stop()
        self.focus_watcher.stop()
        self._reset_state()

    def _reset_state(self) -> None:
        self.state_manager.state = BotState.IDLE
        self._process = None
        self._hwnd = None
        self.focus_watcher.hwnd = None

    def _load_config_path(self) -> str:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return ""
        return config.get("game_path", "")

    def get_config(self) -> dict:
        return {"game_path": self._load_config_path()}

    def set_config(self, game_path: str) -> None:
        self._save_config(game_path)

    def _save_config(self, game_path: str) -> None:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"game_path": game_path.strip()}, f)
        except Exception as e:
            self.logger.error(f"Failed to save config: {e}")

    @staticmethod
    def browse(path: str) -> dict:
        if not path:
            drives = []
            for letter in string.ascii_uppercase:
                drive = f"{letter}:/"
                if os.path.exists(drive):
                    drives.append(drive)
            return {"dirs": drives, "exes": [], "parent": None}

        abs_path = os.path.abspath(path)
        if not os.path.isdir(abs_path):
            abs_path = os.path.dirname(abs_path) or abs_path

        try:
            entries = os.listdir(abs_path)
        except PermissionError:
            return {"dirs": [], "exes": [], "parent": abs_path}

        dirs: list[str] = []
        exes: list[str] = []
        for entry in sorted(entries, key=lambda e: e.lower()):
            full = os.path.join(abs_path, entry)
            if os.path.isdir(full):
                dirs.append(entry)
            elif entry.lower().endswith(".exe"):
                exes.append(entry)

        parent = os.path.dirname(abs_path)
        if parent == abs_path:
            parent = ""

        return {"dirs": dirs, "exes": exes, "parent": parent}

    def shutdown(self) -> None:
        self.stop_flush()
        self._cleanup()
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass
