from __future__ import annotations

import queue
import types
from typing import Any

import numpy as np
import pytest

from core.recorder_overlay import (
    ACTION_CONTINUE,
    ACTION_LEFT,
    ACTION_RIGHT,
    ACTION_SCROLL,
    OverlayController,
    RecorderOverlayTk,
)
import core.recorder_overlay as recorder_overlay


@pytest.fixture
def controller():
    return OverlayController()


@pytest.fixture
def frame():
    return np.zeros((100, 100, 3), dtype=np.uint8)


def test_show_resets_state(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    assert controller.state == "VISIBLE"
    assert controller.frame is frame
    assert controller.action == ACTION_LEFT


def test_add_rect_normalizes_and_stores(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    controller.add_rect((10, 20, 30, 15))
    assert controller.rects == [(10, 15, 30, 20)]


def test_add_tiny_rect_is_ignored(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    controller.add_rect((0, 0, 2, 2))
    assert controller.rects == []


def test_remove_rect(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    controller.add_rect((10, 10, 20, 20))
    controller.add_rect((30, 30, 40, 40))
    controller.remove_rect(0)
    assert len(controller.rects) == 1
    assert controller.rects[0] == (30, 30, 40, 40)


def test_clear_rects(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    controller.add_rect((10, 10, 20, 20))
    controller.set_scroll_anchor((50, 50))
    controller.clear_rects()
    assert controller.rects == []
    assert controller.scroll_anchor is None


def test_set_action_scroll_clears_anchor(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    controller.set_scroll_anchor((50, 50))
    controller.set_action(ACTION_LEFT)
    assert controller.scroll_anchor is None


def test_can_confirm_requires_rect(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    assert controller.can_confirm() is False
    controller.add_rect((10, 10, 20, 20))
    assert controller.can_confirm() is True


def test_get_crops(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    controller.add_rect((10, 10, 20, 25))
    crops = controller.get_crops()
    assert len(crops) == 1
    assert crops[0].shape == (15, 10, 3)


def test_get_crops_clamps_to_bounds(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    controller.add_rect((-5, 90, 110, 120))
    crops = controller.get_crops()
    assert crops[0].shape == (10, 100, 3)


def test_scroll_info_only_when_action_scroll(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    controller.set_action(ACTION_SCROLL)
    controller.set_scroll_dir(-1)
    controller.set_scroll_anchor((40, 50))
    assert controller.get_scroll_info() == (-1, (40, 50))
    controller.set_action(ACTION_CONTINUE)
    assert controller.get_scroll_info() == (None, None)


def test_offset_defaults_to_center_and_resets(controller, frame):
    region = {"left": 0, "top": 0, "width": 100, "height": 100}
    controller.show(frame, region)
    assert controller.get_offset() == (0, 0)
    controller.add_rect((10, 10, 30, 30))
    assert controller.crosshair_point() == (20, 20)
    controller.set_offset(5, -3)
    assert controller.get_offset() == (5, -3)
    assert controller.crosshair_point() == (25, 17)
    controller.show(frame, region)
    assert controller.get_offset() == (0, 0)


def test_crosshair_point_none_without_rect(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    assert controller.crosshair_point() is None


def test_crosshair_point_clamps_to_frame(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    controller.add_rect((90, 90, 98, 98))
    controller.set_offset(50, 50)
    assert controller.crosshair_point() == (99, 99)


def test_hit_test_rect_returns_topmost(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    controller.add_rect((10, 10, 40, 40))
    controller.add_rect((20, 20, 50, 50))
    assert controller.hit_test_rect(25, 25) == 1
    assert controller.hit_test_rect(12, 12) == 0
    assert controller.hit_test_rect(80, 80) is None


def test_hit_test_edge_detects_corner(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    controller.add_rect((10, 10, 40, 40))
    hit = controller.hit_test_edge(11, 11)
    assert hit is not None
    assert hit[0] == 0
    assert hit[1] == frozenset({"left", "top"})
    assert controller.hit_test_edge(25, 25) is None


def test_move_rect_translates_and_clamps(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    controller.add_rect((10, 10, 30, 30))
    controller.move_rect(0, 5, 5)
    assert controller.rects[0] == (15, 15, 35, 35)
    controller.move_rect(0, 1000, 1000)
    assert controller.rects[0] == (80, 80, 100, 100)


def test_resize_rect_moves_edge(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    controller.add_rect((10, 10, 30, 30))
    controller.resize_rect(0, frozenset({"right"}), 50, 0)
    assert controller.rects[0] == (10, 10, 50, 30)


def test_resize_rect_rejects_too_small(controller, frame):
    controller.show(frame, {"left": 0, "top": 0, "width": 100, "height": 100})
    controller.add_rect((10, 10, 30, 30))
    controller.resize_rect(0, frozenset({"right"}), 11, 0)
    assert controller.rects[0] == (10, 10, 30, 30)


def _make_fake_tk(*, toplevel_raises: bool = False) -> Any:
    class FakeRoot:
        def __init__(self) -> None:
            self.exists = True
            self.after_calls: list[tuple[int, Any]] = []
            self._after_id = 0

        def withdraw(self) -> None:
            pass

        def mainloop(self) -> None:
            pass

        def winfo_exists(self) -> bool:
            return self.exists

        def after(self, ms: int, cmd: Any) -> str:
            self._after_id += 1
            self.after_calls.append((ms, cmd))
            return str(self._after_id)

        def after_cancel(self, after_id: str | None) -> None:
            pass

        def quit(self) -> None:
            pass

    class FakeToplevel:
        def __init__(self, parent: Any) -> None:
            if toplevel_raises:
                raise RuntimeError("toplevel failed")
            self.parent = parent

        def overrideredirect(self, value: bool) -> None:
            pass

        def attributes(self, *args: Any, **kwargs: Any) -> None:
            pass

        def configure(self, **kwargs: Any) -> None:
            pass

        def geometry(self, value: str) -> None:
            pass

        def destroy(self) -> None:
            pass

        def withdraw(self) -> None:
            pass

        def deiconify(self) -> None:
            pass

        def update_idletasks(self) -> None:
            pass

        def winfo_screenwidth(self) -> int:
            return 1920

        def winfo_reqwidth(self) -> int:
            return 320

        def winfo_reqheight(self) -> int:
            return 40

        def bind(self, *args: Any, **kwargs: Any) -> None:
            pass

    class FakeFrame:
        def __init__(self, parent: Any, **kwargs: Any) -> None:
            pass

        def pack(self, **kwargs: Any) -> None:
            pass

        def pack_propagate(self, value: bool) -> None:
            pass

    class FakeLabel:
        def __init__(self, parent: Any, **kwargs: Any) -> None:
            self.kwargs = dict(kwargs)

        def pack(self, **kwargs: Any) -> None:
            pass

        def config(self, **kwargs: Any) -> None:
            self.kwargs.update(kwargs)

    class FakeButton:
        def __init__(self, parent: Any, **kwargs: Any) -> None:
            pass

        def pack(self, **kwargs: Any) -> None:
            pass

    class FakeCanvas:
        def __init__(self, parent: Any, **kwargs: Any) -> None:
            pass

        def pack(self, **kwargs: Any) -> None:
            pass

        def create_image(self, *args: Any, **kwargs: Any) -> int:
            return 1

        def create_rectangle(self, *args: Any, **kwargs: Any) -> int:
            return 2

        def create_oval(self, *args: Any, **kwargs: Any) -> int:
            return 3

        def create_line(self, *args: Any, **kwargs: Any) -> int:
            return 4

        def delete(self, item: Any) -> None:
            pass

        def coords(self, item: Any, *coords: Any) -> None:
            pass

        def find_closest(self, x: int, y: int) -> tuple:
            return ()

        def bind(self, *args: Any, **kwargs: Any) -> None:
            pass

    class FakeStringVar:
        def __init__(self, value: str = "") -> None:
            self._value = value

        def get(self) -> str:
            return self._value

        def set(self, value: str) -> None:
            self._value = value

    class FakeRadiobutton:
        def __init__(self, parent: Any, **kwargs: Any) -> None:
            pass

        def pack(self, **kwargs: Any) -> None:
            pass

    return types.SimpleNamespace(
        Tk=FakeRoot,
        Toplevel=FakeToplevel,
        Frame=FakeFrame,
        Label=FakeLabel,
        Button=FakeButton,
        Canvas=FakeCanvas,
        StringVar=FakeStringVar,
        Radiobutton=FakeRadiobutton,
        TOP="top",
        LEFT="left",
        RIGHT="right",
        BOTH="both",
        X="x",
        NW="nw",
    )


@pytest.fixture
def fake_tk(monkeypatch):
    fake = _make_fake_tk()
    monkeypatch.setattr(recorder_overlay, "tk", fake)
    monkeypatch.setattr(recorder_overlay, "ImageTk", types.SimpleNamespace(PhotoImage=lambda **kwargs: object()))
    monkeypatch.setattr(recorder_overlay, "Image", types.SimpleNamespace(fromarray=lambda arr: object()))
    return fake


def test_show_crop_failure_logs_and_clears(fake_tk, fake_logger, monkeypatch):
    fake = _make_fake_tk(toplevel_raises=True)
    monkeypatch.setattr(recorder_overlay, "tk", fake)

    view = RecorderOverlayTk(queue.Queue(), OverlayController(), logger=fake_logger)
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    view._show_crop(frame, {"left": 0, "top": 0, "width": 10, "height": 10})

    assert any("Failed to open crop overlay" in msg for msg in fake_logger.messages("ERR"))
    assert view._crop_win is None
    assert view._ctrl.state == "IDLE"


def test_poll_failure_logs_and_reschedules(fake_tk, fake_logger):
    view = RecorderOverlayTk(queue.Queue(), OverlayController(), logger=fake_logger)

    def failing_handle(item: dict[str, Any]) -> None:
        raise RuntimeError("poll boom")

    view._handle_command = failing_handle
    view._cmd_q.put({"cmd": "destroy"})
    view._schedule_poll()

    assert any("Recorder overlay poll error" in msg for msg in fake_logger.messages("ERR"))
    assert len(view._root.after_calls) == 1
    assert view._root.after_calls[0][0] == 50


def test_do_capture_calls_callback(fake_tk, fake_logger):
    captured = []
    view = RecorderOverlayTk(
        queue.Queue(), OverlayController(), on_capture=lambda: captured.append(True), logger=fake_logger
    )
    view._do_capture()
    assert captured == [True]


def test_do_capture_logs_failure(fake_tk, fake_logger):
    def boom() -> None:
        raise RuntimeError("capture boom")

    view = RecorderOverlayTk(queue.Queue(), OverlayController(), on_capture=boom, logger=fake_logger)
    view._do_capture()
    assert any("capture failed" in msg for msg in fake_logger.messages("ERR"))


def test_request_crop_schedules_capture(fake_tk, fake_logger):
    view = RecorderOverlayTk(queue.Queue(), OverlayController(), logger=fake_logger)
    view._request_crop()
    assert view._root.after_calls[-1][0] == 120
    assert view._root.after_calls[-1][1] == view._do_capture


def test_set_counts_updates_label(fake_tk, fake_logger):
    view = RecorderOverlayTk(queue.Queue(), OverlayController(), logger=fake_logger)
    view._show_bar(1, 0)
    view._set_counts(2, 3)
    assert view._count_label is not None
    assert view._count_label.kwargs["text"] == "step 2 · targets 3"
