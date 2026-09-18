from __future__ import annotations

import os
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

collect_ignore = ["test_pynput.py"]


class RecordingLogger:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []
        self._callbacks: list = []

    def _record(self, level: str, message: object) -> None:
        self.lines.append((level, str(message)))

    def info(self, message: object) -> None:
        self._record("INFO", message)

    def warning(self, message: object) -> None:
        self._record("WARN", message)

    def error(self, message: object) -> None:
        self._record("ERR", message)

    def state(self, message: object) -> None:
        self._record("STATE", message)

    def on_log(self, callback) -> None:
        self._callbacks.append(callback)

    def flush(self) -> None:
        pass

    def messages(self, level: str | None = None) -> list[str]:
        return [msg for lv, msg in self.lines if level is None or lv == level]


@pytest.fixture
def fake_logger() -> RecordingLogger:
    return RecordingLogger()


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


class _FakeSct:
    def __init__(self, monitors: list[dict[str, int]] | None = None) -> None:
        self.monitors = monitors or [{"left": 0, "top": 0, "width": 1920, "height": 1080}]

    def close(self) -> None:
        pass


class FakeScreen:
    def __init__(self) -> None:
        self.clock = FakeClock()
        self.visible: set[str] = set()
        self.clicks: list[tuple[str, int, int]] = []
        self.captured = 0
        self.captured_region: dict[str, int] | None = None

    def match(self, screenshot, path, threshold=0.85, grayscale=True):
        from core.match_result import MatchResult

        if os.path.basename(path) in self.visible:
            return MatchResult(location=(10, 10), size=(10, 10), confidence=0.97)
        return None

    def click(self, point, *args, **kwargs):
        self.clicks.append((str(kwargs.get("label")), point[0], point[1]))
        return True

    def capture(self, sct=None, region=None):
        self.captured += 1
        self.captured_region = region
        return "screen"


@pytest.fixture
def fake_screen(monkeypatch) -> FakeScreen:
    import core.screen_bot as sb
    import routines.click_step as cs
    import routines.step as step_mod
    import routines.routine as routine_mod

    fs = FakeScreen()
    monkeypatch.setattr(sb, "time", fs.clock)
    monkeypatch.setattr(cs, "time", fs.clock)
    monkeypatch.setattr(step_mod, "time", fs.clock)
    monkeypatch.setattr(routine_mod, "time", fs.clock)
    monkeypatch.setattr(sb, "_capture", fs.capture)
    monkeypatch.setattr(sb, "mss", types.SimpleNamespace(mss=lambda: _FakeSct()))
    monkeypatch.setattr(cs, "match_template", fs.match)
    monkeypatch.setattr(routine_mod, "match_template", fs.match)
    monkeypatch.setattr(cs, "do_click", fs.click)
    return fs


@pytest.fixture
def tmp_plans(tmp_path) -> Iterator[Path]:
    import routines
    import routines.plan_loader as pl

    original = pl.PLANS_DIR
    plans = tmp_path / "plans"
    plans.mkdir()
    pl.PLANS_DIR = str(plans)
    try:
        yield plans
    finally:
        pl.PLANS_DIR = original
        routines.refresh_routines()


@pytest.fixture
def tmp_config(tmp_path) -> Iterator[Path]:
    import web.bot_controller as bc

    original = bc.CONFIG_FILE
    cfg = tmp_path / "config.json"
    bc.CONFIG_FILE = str(cfg)
    try:
        yield cfg
    finally:
        bc.CONFIG_FILE = original


class FakeGameLauncher:
    def list_visible_windows(self):
        return []

    def find_window_by_tab(self, *args, **kwargs):
        return None

    def get_window_title(self, hwnd):
        return ""

    def launch(self, path):
        raise RuntimeError("game launch is not available in tests")


class FakeFocusWatcher:
    def __init__(self) -> None:
        self.hwnd: int | None = None
        self._cb = None

    def set_target(self, *args, **kwargs) -> None:
        pass

    def clear_target(self) -> None:
        self.hwnd = None

    def set_callback(self, callback) -> None:
        self._cb = callback

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    @property
    def is_window_alive(self) -> bool:
        return True

    @property
    def foreground_title(self) -> str:
        return ""

    @property
    def is_focused(self) -> bool:
        return True


class FakeScreenBot:
    def __init__(self) -> None:
        self.check_interval = 0.5
        self.preview = False
        self.preview_mode = "snapshot"
        self.on_routine_done = None
        self.on_routine_abort = None
        self.on_frame = None

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def start_routine(self, routine) -> None:
        pass


@pytest.fixture
def fake_game_launcher() -> FakeGameLauncher:
    return FakeGameLauncher()


@pytest.fixture
def fake_focus_watcher() -> FakeFocusWatcher:
    return FakeFocusWatcher()


@pytest.fixture
def fake_screen_bot() -> FakeScreenBot:
    return FakeScreenBot()


@pytest.fixture
def controller(fake_logger, fake_game_launcher, fake_focus_watcher, fake_screen_bot):
    from core.state_manager import StateManager
    from web.bot_controller import BotController

    return BotController(
        fake_logger,
        StateManager(),
        fake_game_launcher,
        fake_focus_watcher,
        fake_screen_bot,
    )


class FakeWin32:
    def __init__(self) -> None:
        self.windows: list[dict] = []
        self.foreground = 0
        self.children: dict = {}
        self._rects: dict[int, dict[str, int]] = {}
        self._iconic: set[int] = set()

    def add(self, hwnd: int, title: str, pid: int = 0, visible: bool = True) -> None:
        self.windows.append(
            {"hwnd": hwnd, "title": title, "pid": pid, "visible": visible}
        )

    def set_rect(self, hwnd: int, left: int, top: int, width: int, height: int) -> None:
        self._rects[hwnd] = {"left": left, "top": top, "width": width, "height": height}

    def set_iconic(self, hwnd: int, iconic: bool) -> None:
        if iconic:
            self._iconic.add(hwnd)
        else:
            self._iconic.discard(hwnd)

    def _by_hwnd(self, hwnd):
        return next((w for w in self.windows if w["hwnd"] == hwnd), None)

    def get_thread_process_id(self, hwnd):
        w = self._by_hwnd(hwnd)
        return (0, w["pid"] if w else 0)

    def EnumWindows(self, callback, lparam) -> None:
        for w in list(self.windows):
            callback(w["hwnd"], lparam)

    def IsWindowVisible(self, hwnd) -> bool:
        w = self._by_hwnd(hwnd)
        return bool(w and w["visible"])

    def GetWindowText(self, hwnd) -> str:
        w = self._by_hwnd(hwnd)
        return w["title"] if w else ""

    def IsWindow(self, hwnd) -> bool:
        return self._by_hwnd(hwnd) is not None

    def IsChild(self, parent, child) -> bool:
        return child in self.children.get(parent, set())

    def GetForegroundWindow(self):
        return self.foreground

    def ClientToScreen(self, hwnd: int, point: tuple[int, int]) -> tuple[int, int]:
        rect = self._rects.get(hwnd, {"left": 0, "top": 0})
        return (point[0] + rect["left"], point[1] + rect["top"])

    def GetClientRect(self, hwnd: int) -> tuple[int, int, int, int]:
        rect = self._rects.get(hwnd, {"width": 0, "height": 0})
        return (0, 0, rect["width"], rect["height"])

    def IsIconic(self, hwnd: int) -> bool:
        return hwnd in self._iconic


@pytest.fixture
def fake_win32(monkeypatch) -> FakeWin32:
    import core.game_launcher as gl
    import core.focus_watcher as fw

    fake = FakeWin32()
    win32process = types.SimpleNamespace(
        GetWindowThreadProcessId=fake.get_thread_process_id
    )
    monkeypatch.setattr(gl, "win32gui", fake)
    monkeypatch.setattr(gl, "win32process", win32process)
    monkeypatch.setattr(fw, "win32gui", fake)
    monkeypatch.setattr(fw, "win32process", win32process)
    return fake
