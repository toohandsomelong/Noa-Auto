import json
import os
import queue
import time
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from state_manager import BotState

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    pystray = None
    Image = None
    ImageDraw = None
    HAS_TRAY = False


CONFIG_FILE = "config.json"


class App:
    def __init__(self, logger, state_manager, game_launcher, focus_watcher, screen_bot=None):
        self.logger = logger
        self.state_manager = state_manager
        self.game_launcher = game_launcher
        self.focus_watcher = focus_watcher
        self.screen_bot = screen_bot
        self._process = None
        self._hwnd = None
        self._tray_icon = None
        self._ui_queue: queue.Queue = queue.Queue()
        self._running = True

        self.root = tk.Tk()
        self.root.title("Auto Trainer")
        self.root.geometry("640x400")
        self.root.minsize(500, 300)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        logger.on_log(self._append_log)
        self._load_config()

    def _build_ui(self):
        path_frame = tk.Frame(self.root)
        path_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        tk.Label(path_frame, text="Game Path:").pack(side=tk.LEFT)
        self.path_var = tk.StringVar()
        self.path_entry = tk.Entry(path_frame, textvariable=self.path_var)
        self.path_entry.pack(side=tk.LEFT, padx=(5, 5), fill=tk.X, expand=True)
        tk.Button(path_frame, text="Browse", command=self._browse).pack(side=tk.RIGHT)

        control_frame = tk.Frame(self.root)
        control_frame.pack(fill=tk.X, padx=10, pady=(0, 5))

        tk.Label(control_frame, text="Status:").pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="IDLE")
        self.status_label = tk.Label(
            control_frame, textvariable=self.status_var,
            fg="gray", font=("", 10, "bold")
        )
        self.status_label.pack(side=tk.LEFT, padx=(5, 15))

        self.start_btn = tk.Button(
            control_frame, text="\u25b6  Start", command=self._start, width=10
        )
        self.start_btn.pack(side=tk.LEFT, padx=(0, 5))
        self.stop_btn = tk.Button(
            control_frame, text="\u25a0  Stop", command=self._stop,
            state=tk.DISABLED, width=10
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 5))

        log_frame = tk.Frame(self.root)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        tk.Label(log_frame, text="Log", anchor=tk.W).pack(fill=tk.X)

        text_frame = tk.Frame(log_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            text_frame, state=tk.DISABLED, wrap=tk.WORD,
            font=("Consolas", 9)
        )
        scrollbar = tk.Scrollbar(text_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _load_config(self):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return

        path = config.get("game_path", "")
        if path:
            self.path_var.set(path)

    def _save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"game_path": self.path_var.get().strip()}, f)
        except Exception as e:
            self.logger.error(f"Failed to save config: {e}")

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select Game Executable",
            filetypes=[("Executable files", "*.exe"), ("All files", "*.*")]
        )
        if path:
            self.path_var.set(path)
            self._save_config()

    def _start(self):
        if self.state_manager.is_active():
            self.logger.warning("Game already running")
            return

        path = self.path_var.get().strip()
        if not path:
            messagebox.showwarning("No Path", "Please select a game executable first.")
            return
        if not os.path.exists(path):
            self.logger.error(f"Path not found: {path}")
            return

        self._save_config()

        existing_hwnd = self.game_launcher.find_existing_window()
        if existing_hwnd is not None:
            self.logger.warning("Game already running; reusing existing window")
            self.state_manager.state = BotState.RUNNING
            self._update_ui_state()
            threading.Thread(
                target=self._attach, args=(existing_hwnd,), daemon=True
            ).start()
            return

        self.logger.info(f"Starting game: {path}")
        self.state_manager.state = BotState.RUNNING
        self._update_ui_state()

        threading.Thread(target=self._launch, args=(path,), daemon=True).start()

    def _attach(self, hwnd):
        self._hwnd = hwnd
        self.focus_watcher.hwnd = hwnd
        self.focus_watcher.set_callback(self._on_focus_change)

        self.logger.info(f"Game HWND: {hwnd}")
        self.logger.info(f"Foreground window: \"{self.focus_watcher.foreground_title}\"")

        if self.focus_watcher.is_focused:
            self.state_manager.state = BotState.RUNNING
            self.logger.state("RUNNING \u2014 game focused")
        else:
            self.state_manager.state = BotState.PAUSED
            self.logger.state("PAUSED \u2014 game unfocused")
        self._ui_queue.put(self._update_ui_state)

        self.focus_watcher.start()
        if self.screen_bot is not None:
            self.screen_bot.start()
        self._monitor_process()

    def _launch(self, path):
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
        self.logger.info(f"Foreground window: \"{self.focus_watcher.foreground_title}\"")

        if self.focus_watcher.is_focused:
            self.state_manager.state = BotState.RUNNING
            self.logger.state("RUNNING \u2014 game focused")
        else:
            self.state_manager.state = BotState.PAUSED
            self.logger.state("PAUSED \u2014 game unfocused")
        self._ui_queue.put(self._update_ui_state)

        self.focus_watcher.start()
        if self.screen_bot is not None:
            self.screen_bot.start()
        self._monitor_process()

    def _monitor_process(self):
        def monitor():
            while self.state_manager.state != BotState.IDLE:
                if not self.focus_watcher.is_window_alive:
                    self.logger.state("STOPPED \u2014 game window closed")
                    self.state_manager.state = BotState.STOPPED
                    self._ui_queue.put(self._cleanup)
                    break
                time.sleep(1)
        threading.Thread(target=monitor, daemon=True).start()

    def _on_focus_change(self, focused):
        if focused:
            self.state_manager.state = BotState.RUNNING
            self.logger.state("RESUMED \u2014 game focused")
        else:
            self.state_manager.state = BotState.PAUSED
            self.logger.state("PAUSED \u2014 game unfocused")
        self._ui_queue.put(self._update_ui_state)

    def _stop(self):
        self.logger.info("User requested stop")
        self._cleanup()

    def _cleanup(self):
        if self.screen_bot is not None:
            self.screen_bot.stop()
        self.focus_watcher.stop()
        self._reset_state()

    def _reset_state(self):
        self.state_manager.state = BotState.IDLE
        self._process = None
        self._hwnd = None
        self.focus_watcher.hwnd = None
        self._ui_queue.put(self._update_ui_state)

    def _update_ui_state(self):
        s = self.state_manager.state.value
        self.status_var.set(s)
        color_map = {
            "RUNNING": "green",
            "PAUSED": "orange",
            "STOPPED": "red",
            "IDLE": "gray",
        }
        self.status_label.config(fg=color_map.get(s, "gray"))
        is_active = self.state_manager.is_active()
        self.start_btn.config(state=tk.DISABLED if is_active else tk.NORMAL)
        self.stop_btn.config(state=tk.NORMAL if is_active else tk.DISABLED)

    def _append_log(self, line):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _flush_ui_queue(self):
        while True:
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except tk.TclError:
                pass

    def _on_close(self):
        self._exit()

    def _show_tray(self):
        if not HAS_TRAY:
            self._exit()
            return
        if self._tray_icon:
            return

        image = Image.new("RGB", (64, 64), (0, 120, 215))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((12, 20, 52, 44), radius=4, fill=(255, 255, 255))
        draw.ellipse((24, 12, 40, 28), fill=(255, 200, 0))

        menu = (
            pystray.MenuItem("Show", self._restore),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._exit),
        )
        self._tray_icon = pystray.Icon(
            "uma_trainer", image, "Auto Trainer", menu
        )
        self._tray_icon.run_detached()

    def _restore(self):
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
        self.root.deiconify()
        self.root.lift()

    def _exit(self):
        self._running = False
        self._restore()
        if self.screen_bot is not None:
            self.screen_bot.stop()
        self.focus_watcher.stop()
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        try:
            while self._running:
                self.root.update()
                self.logger.flush()
                self._flush_ui_queue()
                time.sleep(0.05)
        except tk.TclError:
            pass
        except KeyboardInterrupt:
            self._exit()
