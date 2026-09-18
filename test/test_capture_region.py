from __future__ import annotations

from collections.abc import Iterator

import pytest

from core import screen_bot as sb
from core.match_result import MatchResult
from core.state_manager import BotState, StateManager
from routines.click_step import ClickStep
from routines.config import RoutineConfig
from routines.routine import Routine
from routines.target import Target


@pytest.fixture(autouse=True)
def _reset_capture_origin() -> Iterator[None]:
    yield
    sb.set_capture_origin(0, 0)


class _FakeSct:
    def __init__(self, monitors: list[dict[str, int]]) -> None:
        self.monitors = monitors


def test_resolve_region_with_window(fake_logger, fake_focus_watcher, fake_win32, monkeypatch):
    monkeypatch.setattr(sb, "win32gui", fake_win32)

    fw = fake_focus_watcher
    fw.hwnd = 123
    fake_win32.add(123, "game")
    fake_win32.set_rect(123, 100, 200, 800, 600)

    bot = sb.ScreenBot(fake_logger, StateManager(), fw)
    sct = _FakeSct([{"left": -10, "top": 0, "width": 3000, "height": 1440}])
    resolved = bot._resolve_region(sct)

    assert resolved is not None
    region, origin = resolved
    assert region == {"left": 100, "top": 200, "width": 800, "height": 600}
    assert origin == (100, 200)


def test_resolve_region_minimized(fake_logger, fake_focus_watcher, fake_win32, monkeypatch):
    monkeypatch.setattr(sb, "win32gui", fake_win32)

    fw = fake_focus_watcher
    fw.hwnd = 123
    fake_win32.add(123, "game")
    fake_win32.set_rect(123, 100, 200, 800, 600)
    fake_win32.set_iconic(123, True)

    bot = sb.ScreenBot(fake_logger, StateManager(), fw)
    sct = _FakeSct([{"left": 0, "top": 0, "width": 1920, "height": 1080}])
    assert bot._resolve_region(sct) is None


def test_resolve_region_headless(fake_logger, monkeypatch):
    bot = sb.ScreenBot(fake_logger, StateManager(), None)
    sct = _FakeSct([{"left": -100, "top": 50, "width": 1920, "height": 1080}])
    resolved = bot._resolve_region(sct)

    assert resolved is not None
    region, origin = resolved
    assert region == {"left": -100, "top": 50, "width": 1920, "height": 1080}
    assert origin == (-100, 50)


def test_click_point_includes_origin(fake_logger, fake_win32, monkeypatch):
    monkeypatch.setattr(sb, "win32gui", fake_win32)

    sb.set_capture_origin(100, 200)
    m = MatchResult(location=(10, 10), size=(10, 10), confidence=0.97)
    point = ClickStep._target_point(m, Target("templates/x.png", offset_y=0))
    assert point == (115, 215)


def test_run_cycle_offsets_click(
    fake_logger, fake_screen, fake_focus_watcher, fake_win32, monkeypatch
):
    monkeypatch.setattr(sb, "win32gui", fake_win32)

    fw = fake_focus_watcher
    fw.hwnd = 42
    fake_win32.add(42, "game")
    fake_win32.set_rect(42, 300, 400, 800, 600)

    state_mgr = StateManager()
    bot = sb.ScreenBot(fake_logger, state_mgr, fw)

    step = ClickStep([Target("templates/x.png")])
    routine = Routine(
        "cap",
        [step],
        logger=fake_logger,
        config=RoutineConfig(),
    )
    bot.start_routine(routine)
    state_mgr.state = BotState.RUNNING

    fake_screen.visible.add("x.png")
    bot._run_cycle(_FakeSct([{"left": 0, "top": 0, "width": 1920, "height": 1080}]))

    assert fake_screen.captured_region == {"left": 300, "top": 400, "width": 800, "height": 600}
    assert fake_screen.clicks == [("x.png", 315, 415)]
