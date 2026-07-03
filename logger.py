import os
import datetime


class Logger:
    def __init__(self, log_dir="logs"):
        self.log_dir = log_dir
        self.callbacks = []
        os.makedirs(log_dir, exist_ok=True)

    def on_log(self, callback):
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

        for cb in self.callbacks:
            cb(line)
