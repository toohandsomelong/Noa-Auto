from __future__ import annotations

import pytest

from routines import base
from routines.click_action import ClickAction


class FakePyAutoGUI:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.raise_on_click = False

    def scroll(self, amount, x=None, y=None):
        self.calls.append(("scroll", amount, x, y))

    def click(self, x, y):
        self.calls.append(("click", x, y))
        if self.raise_on_click:
            raise RuntimeError("boom")

    def rightClick(self, x, y):
        self.calls.append(("rightClick", x, y))


@pytest.fixture
def fpag(monkeypatch) -> FakePyAutoGUI:
    fake = FakePyAutoGUI()
    monkeypatch.setattr(base, "pyautogui", fake)
    return fake


def test_left_click(fpag):
    assert base.do_click((5, 6)) is True
    assert fpag.calls == [("click", 5, 6)]


def test_right_click(fpag):
    assert base.do_click((5, 6), ClickAction=ClickAction.RIGHT_CLICK) is True
    assert fpag.calls == [("rightClick", 5, 6)]


def test_scroll_then_click(fpag):
    assert base.do_click((5, 6), scrollValue=-100) is True
    assert fpag.calls == [("scroll", -100, 5, 6), ("click", 5, 6)]


def test_zero_scroll_does_not_scroll(fpag):
    base.do_click((5, 6), scrollValue=0)
    assert fpag.calls == [("click", 5, 6)]


def test_unsupported_action_returns_false(fpag, fake_logger):
    assert base.do_click((1, 2), ClickAction=ClickAction.CONTINUE, logger=fake_logger) is False
    assert any("Unknown ClickAction" in msg for msg in fake_logger.messages("ERR"))


def test_non_enum_action_returns_false(fpag, fake_logger):
    assert base.do_click((1, 2), ClickAction="bogus", logger=fake_logger) is False
    assert fake_logger.messages("ERR")


def test_click_exception_returns_false_and_logs_label(fpag, fake_logger):
    fpag.raise_on_click = True
    assert base.do_click((1, 2), label="mybtn", logger=fake_logger) is False
    assert any("mybtn" in msg for msg in fake_logger.messages("ERR"))


def test_click_exception_without_logger_does_not_raise(fpag):
    fpag.raise_on_click = True
    assert base.do_click((1, 2)) is False


def test_print_log_error_without_logger_is_noop():
    base.printLogError("hello", None)
