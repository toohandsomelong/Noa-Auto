from __future__ import annotations

import types

import core.focus_watcher as fw_mod
from core.focus_watcher import FocusWatcher


def test_is_focused_by_tab_name(fake_win32):
    fake_win32.add(1, "Game Window")
    fake_win32.foreground = 1
    watcher = FocusWatcher()
    watcher.set_target("Game")
    assert watcher.is_focused is True


def test_is_focused_by_game_keyword(fake_win32):
    fake_win32.add(2, "Umamusume")
    fake_win32.foreground = 2
    watcher = FocusWatcher()
    assert watcher.is_focused is True


def test_is_focused_false_for_other_window(fake_win32):
    fake_win32.add(3, "Notepad")
    fake_win32.foreground = 3
    watcher = FocusWatcher()
    watcher.set_target("Game")
    assert watcher.is_focused is False


def test_is_focused_by_hwnd(fake_win32):
    fake_win32.add(4, "Whatever")
    fake_win32.foreground = 4
    watcher = FocusWatcher()
    watcher.set_target("", None, hwnd=4)
    assert watcher.is_focused is True


def test_is_focused_by_child_window(fake_win32):
    fake_win32.add(5, "parent")
    fake_win32.add(6, "child")
    fake_win32.children = {5: {6}}
    fake_win32.foreground = 6
    watcher = FocusWatcher()
    watcher.set_target("", None, hwnd=5)
    assert watcher.is_focused is True


def test_is_window_alive_without_target_is_true(fake_win32):
    assert FocusWatcher().is_window_alive is True


def test_is_window_alive_by_tab(fake_win32):
    fake_win32.add(7, "Game Window")
    watcher = FocusWatcher()
    watcher.set_target("Game")
    assert watcher.is_window_alive is True


def test_is_window_alive_false_when_gone(fake_win32):
    watcher = FocusWatcher()
    watcher.set_target("Gone")
    assert watcher.is_window_alive is False


def test_foreground_title(fake_win32):
    fake_win32.add(8, "Hello")
    fake_win32.foreground = 8
    assert FocusWatcher().foreground_title == "Hello"


def test_clear_target_resets(fake_win32):
    fake_win32.add(1, "Game")
    watcher = FocusWatcher()
    watcher.set_target("Game", None, 1)
    watcher.clear_target()
    assert watcher.hwnd is None
    assert watcher.is_window_alive is True


def test_run_fires_callback_only_on_change(fake_win32, monkeypatch):
    fake_win32.add(1, "Game")
    fake_win32.add(2, "Other")
    fake_win32.foreground = 1

    watcher = FocusWatcher()
    watcher.set_target("Game")
    events: list[bool] = []
    watcher.set_callback(events.append)

    transitions = [(2, False), (1, True)]
    state = {"index": 0}

    def fake_sleep(_seconds):
        if state["index"] < len(transitions):
            fake_win32.foreground = transitions[state["index"]][0]
            state["index"] += 1
        else:
            watcher._stop_event.set()

    monkeypatch.setattr(fw_mod, "time", types.SimpleNamespace(sleep=fake_sleep))
    watcher._run()
    assert events == [False, True]
