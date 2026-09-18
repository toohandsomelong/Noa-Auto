from __future__ import annotations

import pytest

from core.game_launcher import GameLauncher


def test_find_window_by_title_substring(fake_win32, fake_logger):
    fake_win32.add(1, "Umamusume Pretty Derby")
    launcher = GameLauncher(fake_logger)
    assert launcher.find_window_by_tab("Umamusume") == 1


def test_find_window_skips_hidden(fake_win32, fake_logger):
    fake_win32.add(2, "Game", visible=False)
    launcher = GameLauncher(fake_logger)
    assert launcher.find_window_by_tab("Game") is None


def test_find_window_by_pid(fake_win32, fake_logger):
    fake_win32.add(3, "Anything", pid=777)
    launcher = GameLauncher(fake_logger)
    assert launcher.find_window_by_tab(tab_pid=777) == 3


def test_find_window_none_when_absent(fake_win32, fake_logger):
    launcher = GameLauncher(fake_logger)
    assert launcher.find_window_by_tab("nope") is None


def test_find_existing_window_uses_game_keyword(fake_win32, fake_logger):
    fake_win32.add(9, "Umamusume x")
    launcher = GameLauncher(fake_logger)
    assert launcher.find_existing_window() == 9


def test_list_visible_windows_dedupes_and_sorts(fake_win32, fake_logger):
    fake_win32.add(1, "b", pid=1)
    fake_win32.add(2, "a", pid=2)
    fake_win32.add(3, "b", pid=1)
    fake_win32.add(4, "", pid=3)
    fake_win32.add(5, "hidden", pid=4, visible=False)
    launcher = GameLauncher(fake_logger)
    result = launcher.list_visible_windows()
    assert [w["title"] for w in result] == ["a", "b"]


def test_get_window_title(fake_win32, fake_logger):
    fake_win32.add(1, "Title")
    launcher = GameLauncher(fake_logger)
    assert launcher.get_window_title(1) == "Title"
    assert launcher.get_window_title(None) == ""


def test_launch_missing_path_raises(fake_logger, tmp_path):
    launcher = GameLauncher(fake_logger)
    with pytest.raises(FileNotFoundError):
        launcher.launch(str(tmp_path / "missing.exe"))
