from __future__ import annotations

import json
import os
import string
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any

from core.focus_watcher import FocusWatcher
from core.game_launcher import GameLauncher
from core.logger import Logger
from core.recorder import Recorder
from core.recorder_overlay import RecorderOverlay
from core.screen_bot import ScreenBot
from core.state_manager import BotState, StateManager
from engine import PLANS, refresh_plans
from engine.plan_loader import get_plan, list_plan_labels, save_plan

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
        self._frame_listeners: list[Callable[[dict], None]] = []
        self._config_listeners: list[Callable[[dict], None]] = []
        self._record_listeners: list[Callable[[dict], None]] = []
        self._step_listeners: list[Callable[[dict], None]] = []

        self._flush_stop = threading.Event()
        self._flush_thread: threading.Thread | None = None

        self._recorder = Recorder(
            on_toggle=self._on_record_toggle,
            on_crop_request=self._on_record_crop_request,
            on_next_step=self.next_step,
            on_prev_step=self.previous_step,
            on_remove_target=lambda: self.remove_target(-1),
            focus_watcher=self.focus_watcher,
        )
        self._overlay = RecorderOverlay(
            on_capture=self.begin_crop,
            on_confirm=self._on_crop_confirm,
            on_next_step=self.next_step,
            on_prev_step=self.previous_step,
            on_remove_target=self.remove_target,
            on_stop=self._on_record_toggle,
            logger=self.logger,
        )
        self._overlay_started = False

        self._chain: list[str] = []
        self._chain_idx: int = 0
        self._repeat: int = 1
        self._play_count: int = 0
        self._chain_lock = threading.Lock()
        self._active_target: dict[str, Any] | None = None
        self._focus_started: bool = False
        self._editing_plan_name: str | None = None
        self._editing_plan_config: dict[str, Any] | None = None

        self.logger.on_log(self._on_log_line)
        self.state_manager.on_state_change(self._on_state_change)

    def on_log_event(self, listener: Callable[[str], None]) -> None:
        self._log_listeners.append(listener)

    def on_state_event(self, listener: Callable[[dict], None]) -> None:
        self._state_listeners.append(listener)

    def on_frame_event(self, listener: Callable[[dict], None]) -> None:
        self._frame_listeners.append(listener)

    def on_config_event(self, listener: Callable[[dict], None]) -> None:
        self._config_listeners.append(listener)

    def on_record_event(self, listener: Callable[[dict], None]) -> None:
        self._record_listeners.append(listener)

    def on_step_event(self, listener: Callable[[dict], None]) -> None:
        self._step_listeners.append(listener)

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

    def _on_frame(self, payload: dict) -> None:
        if payload.get("action") == "clear":
            data = {"type": "preview_clear"}
        else:
            data = {"type": "frame", **payload}
        for listener in self._frame_listeners:
            try:
                listener(data)
            except Exception:
                pass

    def _on_step(self, payload: dict) -> None:
        data = {"type": "step", **payload}
        for listener in self._step_listeners:
            try:
                listener(data)
            except Exception:
                pass

    def _emit_config(self) -> None:
        data = {"type": "config", "active_target": self._active_target}
        for listener in self._config_listeners:
            try:
                listener(data)
            except Exception:
                pass

    def _set_active_target(self, game_path: str | None, tab_name: str | None, plan: str | None) -> None:
        self._active_target = {
            "game_path": game_path or None,
            "tab_name": tab_name or None,
            "plan": plan or None,
        }
        self._emit_config()

    def _broadcast_record(self) -> None:
        data = {"type": "record", **self._recorder.status()}
        for listener in self._record_listeners:
            try:
                listener(data)
            except Exception:
                pass

    def start_recording(
        self, name: str | None = None, plan_name: str | None = None
    ) -> dict[str, Any]:
        if self.state_manager.is_active():
            self.logger.warning("Cannot record while bot is running")
            return {"ok": False, "error": "bot is running"}
        if not self._overlay_started:
            self._overlay_started = self._overlay.start()
            if not self._overlay_started:
                self.logger.error("Failed to start overlay UI")
                return {"ok": False, "error": "overlay unavailable"}

        started: bool
        if plan_name is not None:
            plan = get_plan(plan_name)
            if plan is None:
                self.logger.error(f"Plan '{plan_name}' not found")
                return {"ok": False, "error": f"plan '{plan_name}' not found"}
            self._editing_plan_name = plan_name
            self._editing_plan_config = plan.get("config", {})
            started = self._recorder.start_edit(plan_name, plan)
        else:
            self._editing_plan_name = None
            self._editing_plan_config = None
            started = self._recorder.start(name=name)
        if not started:
            return {"ok": False, "error": "already recording"}

        status = self._recorder.status()
        self._overlay.show_bar(step=status["step_index"], targets=status["target_count"])
        self._sync_bar()
        self._broadcast_record()
        self.logger.state("RECORDING")
        return {"ok": True, **status}

    def stop_recording(self, save_as: str | None = None) -> dict[str, Any]:
        data = self._recorder.stop()
        self._overlay.hide_bar()
        self._overlay.hide_crop()
        self._broadcast_record()
        self.logger.state("IDLE")
        if data is None:
            self.logger.warning("No steps recorded")
            return {"ok": False, "error": "no steps recorded"}

        editing_plan = self._editing_plan_name
        self._editing_plan_name = None
        editing_config = self._editing_plan_config
        self._editing_plan_config = None

        data["config"] = self._build_record_config(editing_config)
        if data.get("editing") and editing_plan is not None and save_as is None:
            name = editing_plan
        else:
            name = self._unique_plan_name(save_as or data["name"])
        data["name"] = data.get("name") or name
        try:
            save_plan(name, data)
            refresh_plans()
        except Exception as e:
            self.logger.error(f"Failed to save recorded plan: {e}")
            return {"ok": False, "error": str(e)}
        self.logger.info(f"Saved recorded plan '{name}' ({len(data['steps'])} steps)")
        return {"ok": True, "name": name, "steps": len(data["steps"])}

    def begin_crop(self) -> dict[str, Any]:
        result = self._recorder.begin_crop()
        if result is None:
            return {"ok": False, "error": "capture unavailable"}
        frame, region = result
        self._overlay.show_crop(frame, region)
        return {"ok": True}

    def request_crop(self) -> dict[str, Any]:
        self._overlay.request_crop()
        return {"ok": True}

    def next_step(self) -> dict[str, Any]:
        step = self._recorder.next_step()
        if step is None:
            self.logger.warning("No targets in current step")
            return {"ok": False, "error": "no targets in current step"}
        self._sync_bar()
        self._broadcast_record()
        self.logger.info(f"{step['label']} ({len(step['targets'])} targets)")
        return {"ok": True}

    def previous_step(self) -> dict[str, Any]:
        step = self._recorder.previous_step()
        if step is None:
            self.logger.warning("No previous step")
            return {"ok": False, "error": "no previous step"}
        self._sync_bar()
        self._broadcast_record()
        self.logger.info(f"Back to {step['label']} ({len(step.get('targets', []))} targets)")
        return {"ok": True}

    def remove_target(self, index: int) -> dict[str, Any]:
        target = self._recorder.remove_target(index)
        if target is None:
            self.logger.warning("No target to remove")
            return {"ok": False, "error": "no target to remove"}
        self._sync_bar()
        self._broadcast_record()
        self.logger.info(f"Removed {target.get('label', 'target')}")
        return {"ok": True}

    def get_recording_status(self) -> dict[str, Any]:
        return self._recorder.status()

    def _sync_bar(self) -> None:
        status = self._recorder.status()
        self._overlay.set_counts(status["step_index"], status["target_count"])
        self._overlay.set_targets(status["step_index"], status["current_targets"])

    def _on_record_toggle(self) -> None:
        if self._recorder.state == "IDLE":
            self.start_recording()
        else:
            self.stop_recording()

    def _on_record_crop_request(self) -> None:
        self._overlay.request_crop()

    def _on_crop_confirm(
        self,
        crops: list[Any],
        action: str,
        scroll_dir: int | None,
        scroll_anchor: tuple[int, int] | None,
        offset: tuple[int, int],
    ) -> None:
        target = self._recorder.accept_target(
            crops,
            action,
            scroll_dir=scroll_dir,
            scroll_anchor=scroll_anchor,
            offset=offset,
        )
        if target is not None:
            self._sync_bar()
            self._broadcast_record()

    def _build_record_config(
        self, existing: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        config: dict[str, Any] = {
            "game_path": None,
            "tab_name": None,
            "delay": 0.5,
        }
        if isinstance(existing, dict):
            for key in ("game_path", "tab_name", "delay", "capture_width", "capture_height"):
                if key in existing and existing[key] is not None:
                    config[key] = existing[key]
        region = self._recorder.last_region()
        if region is not None:
            config["capture_width"] = region["width"]
            config["capture_height"] = region["height"]
        return config

    def _unique_plan_name(self, name: str) -> str:
        try:
            if get_plan(name) is None:
                return name
        except Exception:
            pass
        base = name
        i = 2
        while True:
            candidate = f"{base} ({i})"
            try:
                if get_plan(candidate) is None:
                    return candidate
            except Exception:
                pass
            i += 1

    def set_preview(self, enabled: bool) -> bool:
        if self.screen_bot is None:
            return False
        self.screen_bot.preview = enabled
        return True

    def set_preview_mode(self, mode: str) -> bool:
        if self.screen_bot is None:
            return False
        if mode not in ("snapshot", "live"):
            return False
        self.screen_bot.preview_mode = mode
        return True

    def get_preview(self) -> dict:
        if self.screen_bot is None:
            return {"enabled": False, "mode": "snapshot"}
        return {
            "enabled": self.screen_bot.preview,
            "mode": self.screen_bot.preview_mode,
        }

    def get_state(self) -> dict:
        return {
            "state": self.state_manager.state.value,
            "active_target": self._active_target,
        }

    def start(self) -> None:
        if self.state_manager.is_active():
            self.logger.warning("Game already running")
            return
        if self._recorder.state != "IDLE":
            self.stop_recording()

        config = self.get_config()
        plans = config.get("plans", [])
        chain = self._validate_plans(plans)
        if not chain:
            self.logger.warning("No plans configured")
            return

        first = self._load_plan(chain[0])
        if first is None:
            self.logger.error(f"Failed to load plan '{chain[0]}'")
            return

        self._chain = chain
        self._chain_idx = 0
        self._play_count = 0
        self._repeat = max(1, int(config.get("repeat", 1)))
        self._focus_started = False

        self.state_manager.state = BotState.RUNNING
        threading.Thread(
            target=self._dispatch,
            args=(first, chain[0]),
            daemon=True,
        ).start()

    def stop(self) -> None:
        self.logger.info("User requested stop")
        self._cleanup()

    def _load_plan(self, name: str) -> dict[str, Any] | None:
        try:
            return get_plan(name)
        except Exception as e:
            self.logger.error(f"Failed to load plan '{name}': {e}")
            return None

    def _plan_target(self, data: dict[str, Any] | None) -> tuple[str, str]:
        if data is None:
            return "", ""
        config = data.get("config", {})
        game_path = config.get("game_path", "") if isinstance(config, dict) else ""
        tab_name = config.get("tab_name", "") if isinstance(config, dict) else ""
        return (game_path.strip() if isinstance(game_path, str) else ""), (tab_name.strip() if isinstance(tab_name, str) else "")

    def _dispatch(self, plan_data: dict[str, Any] | None, plan_name: str) -> None:
        game_path, tab_name = self._plan_target(plan_data)
        self._set_active_target(game_path, tab_name, plan_name)

        if tab_name:
            hwnd = self.game_launcher.find_window_by_tab(tab_name)
            if hwnd is not None:
                self.logger.info(
                    f"Attaching to window by tab_name={tab_name!r}"
                )
                self._attach(hwnd, tab_name)
                return
            if game_path:
                self.logger.warning(
                    "Target window not found; falling back to game launch"
                )
                self._launch(game_path, tab_name, plan_name)
                return
            self.logger.error("Target window not found")
            self._reset_state()
            return

        if game_path:
            self._launch(game_path, tab_name, plan_name)
            return

        self._run_headless()

    def _attach(self, hwnd: int, tab_name: str) -> None:
        self._hwnd = hwnd
        self.focus_watcher.set_target(tab_name, None, hwnd)
        self.focus_watcher.set_callback(self._on_focus_change)

        self.logger.info(f"Game HWND: {hwnd}")
        self.logger.info(
            f'Foreground window: "{self.focus_watcher.foreground_title}"'
        )

        if not self._focus_started:
            self.focus_watcher.start()
            self._focus_started = True

        if self.focus_watcher.is_focused:
            self.state_manager.state = BotState.RUNNING
            self.logger.state("RUNNING — game focused")
        else:
            self.state_manager.state = BotState.PAUSED
            self.logger.state("PAUSED — game unfocused")

        if self.screen_bot is not None:
            self.screen_bot.on_plan_done = self._on_plan_done
            self.screen_bot.on_frame = self._on_frame
            self.screen_bot.on_step = self._on_step
            self.screen_bot.start()
            self._kickoff_chain()
        self._monitor_process()

    def _launch(self, path: str, tab_name: str, plan_name: str) -> None:
        if not os.path.exists(path):
            self.logger.error(f"Path not found: {path}")
            self._reset_state()
            return

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

        title = self.game_launcher.get_window_title(hwnd)
        if title:
            self._autofill_tab_name(plan_name, title)
            self._set_active_target(path, title, plan_name)

        self._attach(hwnd, tab_name or title)

    def _autofill_tab_name(self, plan_name: str, title: str) -> None:
        try:
            data = get_plan(plan_name)
            if data is None:
                return
            config = data.get("config", {})
            if config.get("tab_name"):
                return
            config["tab_name"] = title
            data["config"] = config
            save_plan(plan_name, data)
            refresh_plans()
            self.logger.info(f"Autofilled tab_name '{title}' into plan '{plan_name}'")
        except Exception as e:
            self.logger.error(f"Failed to autofill tab_name: {e}")

    def _run_headless(self) -> None:
        self.logger.info(
            "No game path or tab target configured — bot running without focus monitoring"
        )
        self.state_manager.state = BotState.RUNNING
        self.logger.state("RUNNING — no target window")
        self.focus_watcher.set_target("", None, None)

        if self.screen_bot is not None:
            self.screen_bot.on_plan_done = self._on_plan_done
            self.screen_bot.on_frame = self._on_frame
            self.screen_bot.on_step = self._on_step
            self.screen_bot.start()
            self._kickoff_chain()
        self._monitor_process()

    def _kickoff_chain(self) -> None:
        if not self._chain:
            self.logger.warning("No plans configured")
            return
        self._build_and_start(self._chain[0], is_first=True)

    def _validate_plans(self, plans: Any) -> list[str]:
        if plans is None:
            return []
        if isinstance(plans, str):
            plans = [plans]
        if not isinstance(plans, list):
            self.logger.error(f"Invalid plans config: {plans!r}")
            return []

        valid: list[str] = []
        for name in plans:
            if name in PLANS:
                valid.append(name)
            else:
                self.logger.error(f"Unknown plan: {name}")
        return valid

    def _build_and_start(self, name: str, is_first: bool = False) -> None:
        builder = PLANS.get(name)
        if builder is None:
            self.logger.error(f"Cannot build unknown plan: {name}")
            return
        try:
            plan = builder(self.logger)
        except Exception as e:
            self.logger.error(f"Failed to build plan '{name}': {e}")
            return

        if plan is None:
            self.logger.error(f"PlanRunner '{name}' could not be built")
            return

        if not is_first:
            self._apply_plan_target(name, plan)

        if self.screen_bot is None:
            return
        self.screen_bot.start_plan(plan)
        self.logger.info(f"PlanRunner '{name}' started")

    def _apply_plan_target(self, name: str, plan: Any) -> None:
        if not hasattr(plan, "config"):
            return
        tab_name = plan.config.tab_name if hasattr(plan.config, "tab_name") else None
        game_path = plan.config.game_path if hasattr(plan.config, "game_path") else None

        if not tab_name and not game_path:
            return

        if tab_name:
            self.focus_watcher.set_target(tab_name, None, self._hwnd)
            self._set_active_target(
                self._active_target.get("game_path") if self._active_target else None,
                tab_name,
                name,
            )
            self.logger.info(f"PlanRunner '{name}' target switched to tab_name={tab_name!r}")
            return

        if game_path:
            self._set_active_target(
                game_path,
                self._active_target.get("tab_name") if self._active_target else None,
                name,
            )
            self.logger.info(f"PlanRunner '{name}' expects game_path={game_path!r} (launch ignored mid-chain)")

    def _on_plan_done(self, name: str) -> None:
        with self._chain_lock:
            self._chain_idx += 1

            if self._chain_idx < len(self._chain):
                next_name = self._chain[self._chain_idx]
                self._build_and_start(next_name, is_first=False)
                return

            self._play_count += 1
            if self._play_count < self._repeat:
                self._chain_idx = 0
                self._build_and_start(self._chain[0], is_first=False)
                return

        self.logger.state("Chain complete")
        threading.Thread(target=self._cleanup, daemon=True).start()

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
        self.focus_watcher.clear_target()
        self._active_target = None
        self._focus_started = False
        self._emit_config()

    def get_config(self) -> dict:
        config = self._load_config()
        plans = config.get("plans")
        if plans is None:
            plans = config.get("routines")
        if plans is None:
            legacy = config.get("routine", "team_trials")
            plans = [legacy] if legacy else []
        repeat = config.get("repeat", 1)
        try:
            repeat = int(repeat)
        except (TypeError, ValueError):
            repeat = 1
        if repeat < 1:
            repeat = 1
        check_interval = config.get("check_interval", 0.5)
        try:
            check_interval = float(check_interval)
        except (TypeError, ValueError):
            check_interval = 0.5
        check_interval = max(0.05, min(10.0, check_interval))
        return {
            "plans": plans,
            "repeat": repeat,
            "check_interval": check_interval,
        }

    def set_config(
        self,
        plans: Any = None,
        repeat: Any = None,
        check_interval: Any = None,
    ) -> None:
        existing = self._load_config()
        if plans is not None:
            if isinstance(plans, str):
                plans = [plans]
            if isinstance(plans, list):
                existing["plans"] = plans
        if repeat is not None:
            try:
                repeat_value = int(repeat)
            except (TypeError, ValueError):
                repeat_value = 0
            if repeat_value > 0:
                existing["repeat"] = repeat_value
        if check_interval is not None:
            try:
                interval_value = float(check_interval)
            except (TypeError, ValueError):
                interval_value = 0.5
            interval_value = max(0.05, min(10.0, interval_value))
            existing["check_interval"] = interval_value
            if self.screen_bot is not None:
                self.screen_bot.check_interval = interval_value
        self._save_config(existing)

    def get_plans(self) -> dict:
        config = self.get_config()
        return {
            "plans": list(PLANS.keys()),
            "labels": list_plan_labels(),
            "current": config["plans"][0] if config["plans"] else "",
            "chain": config["plans"],
            "repeat": config["repeat"],
        }

    def _save_config(self, config: dict) -> None:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f)
        except Exception as e:
            self.logger.error(f"Failed to save config: {e}")

    def _load_config(self) -> dict:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    @staticmethod
    def browse(path: str) -> dict:
        if not path:
            drives = []
            for letter in string.ascii_uppercase:
                drive = f"{letter}:/"
                if os.path.exists(drive):
                    drives.append(drive)
            return {"dirs": drives, "exes": [], "images": [], "parent": None}

        abs_path = os.path.abspath(path)
        if not os.path.isdir(abs_path):
            abs_path = os.path.dirname(abs_path) or abs_path

        try:
            entries = os.listdir(abs_path)
        except PermissionError:
            return {"dirs": [], "exes": [], "images": [], "parent": abs_path}

        IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}
        dirs: list[str] = []
        exes: list[str] = []
        images: list[str] = []
        for entry in sorted(entries, key=lambda e: e.lower()):
            full = os.path.join(abs_path, entry)
            if os.path.isdir(full):
                dirs.append(entry)
            elif entry.lower().endswith(".exe"):
                exes.append(entry)
            elif os.path.splitext(entry)[1].lower() in IMAGE_EXTS:
                images.append(entry)

        parent = os.path.dirname(abs_path)
        if parent == abs_path:
            parent = ""

        return {"dirs": dirs, "exes": exes, "images": images, "parent": parent}

    def shutdown(self) -> None:
        self.stop_flush()
        if self._recorder.state != "IDLE":
            self.stop_recording()
        self._overlay.stop()
        self._cleanup()
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass
