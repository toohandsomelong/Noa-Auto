from __future__ import annotations

import pytest

from engine import base
from engine.click_action import ClickAction


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
    """Patch pyautogui with a call-recording fake."""
    fake = FakePyAutoGUI()
    monkeypatch.setattr(base, "pyautogui", fake)
    return fake


class TestDoClickWrapper:
    """Suite: engine.base.do_click — click/right-click/scroll dispatch and error handling."""

    @pytest.mark.positive
    def test_left_click(self, fpag):
        """A left click maps to pyautogui.click at the point."""
        assert base.do_click((5, 6)) is True
        assert fpag.calls == [("click", 5, 6)]

    @pytest.mark.positive
    def test_right_click(self, fpag):
        """A right click maps to pyautogui.rightClick."""
        assert base.do_click((5, 6), ClickAction=ClickAction.RIGHT_CLICK) is True
        assert fpag.calls == [("rightClick", 5, 6)]

    @pytest.mark.positive
    def test_scroll_then_click(self, fpag):
        """A non-zero scrollValue scrolls before the click."""
        assert base.do_click((5, 6), scrollValue=-100) is True
        assert fpag.calls == [("scroll", -100, 5, 6), ("click", 5, 6)]

    @pytest.mark.edge
    def test_zero_scroll_does_not_scroll(self, fpag):
        """A zero scrollValue skips scrolling entirely."""
        base.do_click((5, 6), scrollValue=0)
        assert fpag.calls == [("click", 5, 6)]

    @pytest.mark.negative
    def test_unsupported_action_returns_false(self, fpag, fake_logger):
        """An unsupported ClickAction logs an error and returns False."""
        assert base.do_click((1, 2), ClickAction=ClickAction.CONTINUE, logger=fake_logger) is False
        assert any("Unknown ClickAction" in msg for msg in fake_logger.messages("ERR"))

    @pytest.mark.negative
    def test_non_enum_action_returns_false(self, fpag, fake_logger):
        """A non-enum action value is rejected with an error."""
        assert base.do_click((1, 2), ClickAction="bogus", logger=fake_logger) is False
        assert fake_logger.messages("ERR")

    @pytest.mark.negative
    def test_click_exception_returns_false_and_logs_label(self, fpag, fake_logger):
        """A raising pyautogui call returns False and logs the target label."""
        fpag.raise_on_click = True
        assert base.do_click((1, 2), label="mybtn", logger=fake_logger) is False
        assert any("mybtn" in msg for msg in fake_logger.messages("ERR"))

    @pytest.mark.negative
    def test_click_exception_without_logger_does_not_raise(self, fpag):
        """A raising click without a logger still returns False quietly."""
        fpag.raise_on_click = True
        assert base.do_click((1, 2)) is False

    @pytest.mark.positive
    def test_print_log_error_logs_with_logger(self, fake_logger):
        """printLogError forwards to the logger when one is provided."""
        assert base.printLogError("hello", fake_logger) is None
        assert fake_logger.messages("ERR") == ["hello"]

    @pytest.mark.edge
    def test_print_log_error_without_logger_is_noop(self):
        """printLogError is a no-op when no logger is provided."""
        assert base.printLogError("hello", None) is None


class TestMatchTemplateWrapper:
    """Suite: engine.base.match_template — template loading, delegation, and flag passthrough."""

    @pytest.mark.positive
    def test_match_template_delegates_and_finds(self, monkeypatch):
        """match_template loads the template then returns the matcher result."""
        sentinel = object()
        monkeypatch.setattr(base, "_load_template", lambda path, grayscale: "TPL")
        monkeypatch.setattr(
            base, "_match", lambda screenshot, template, threshold, grayscale: sentinel
        )
        assert base.match_template("screen", "p.png") is sentinel

    @pytest.mark.negative
    def test_match_template_missing_file_returns_none(self):
        """A template path that does not exist yields None instead of raising."""
        assert base.match_template("screen", "templates/does_not_exist_xyz.png") is None

    @pytest.mark.edge
    def test_flags_passed_through(self, monkeypatch):
        """threshold/grayscale flags reach both _load_template and _match unchanged."""
        seen: dict[str, object] = {}

        def fake_load(path, grayscale):
            seen["load_gs"] = grayscale
            return "TPL"

        def fake_match(screenshot, template, threshold, grayscale):
            seen["threshold"] = threshold
            seen["match_gs"] = grayscale
            return None

        monkeypatch.setattr(base, "_load_template", fake_load)
        monkeypatch.setattr(base, "_match", fake_match)
        base.match_template("screen", "p.png", threshold=0.7, grayscale=False)
        assert seen == {"load_gs": False, "threshold": 0.7, "match_gs": False}
