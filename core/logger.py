import os
import datetime
import queue
import threading


class Logger:
    def __init__(self, log_dir="logs"):
        self.log_dir = log_dir
        self.callbacks = []
        self._pending = queue.Queue()
        self._lock = threading.Lock()
        os.makedirs(log_dir, exist_ok=True)

    def on_log(self, callback):
        with self._lock:
            self.callbacks.append(callback)

    def info(self, message):
        self._log("INFO", message)

    def error(self, message):
        self._log("ERROR", message)

    def warning(self, message):
        self._log("WARN", message)

    def state(self, message):
        self._log("STATE", message)

    def _log(self, level, message):
        now = datetime.datetime.now()
        timestamp = now.strftime("%H:%M:%S")
        line = f"[{timestamp}] {level:<5} {message}"

        file_path = os.path.join(self.log_dir, now.strftime("%Y-%m-%d.log"))
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

        with self._lock:
            callbacks = list(self.callbacks)
        for cb in callbacks:
            self._pending.put((cb, line))

    def flush(self):
        while True:
            try:
                cb, line = self._pending.get_nowait()
            except queue.Empty:
                break
            try:
                cb(line)
            except Exception:
                pass
