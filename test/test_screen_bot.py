from __future__ import annotations

import base64

import cv2
import numpy as np

from core.match_result import MatchResult
from core.screen_bot import ScreenBot, _load_template, _match
from core.state_manager import StateManager


class StubStep:
    def __init__(self, match=None, label="L", last_match_label=None) -> None:
        self.index = 0
        self.label = label
        self.last_match = match
        self.last_match_label = last_match_label


class StubRoutine:
    def __init__(self, step=None) -> None:
        self.done = False
        self._step = step

    def current_step(self):
        return self._step


def _bot(fake_logger=None, **kwargs) -> ScreenBot:
    return ScreenBot(fake_logger, StateManager(), None, **kwargs)


def test_match_finds_exact_crop():
    rng = np.random.default_rng(1)
    screen = rng.integers(0, 256, (60, 60, 3), dtype=np.uint8)
    template = screen[20:35, 20:35].copy()
    result = _match(screen, template, 0.9, grayscale=False)
    assert result is not None
    assert result.location == (20, 20)
    assert result.size == (15, 15)
    assert result.confidence > 0.9


def test_match_below_threshold_returns_none():
    rng = np.random.default_rng(1)
    screen = rng.integers(0, 256, (60, 60, 3), dtype=np.uint8)
    template = screen[20:35, 20:35].copy()
    assert _match(screen, template, 1.1, grayscale=False) is None


def test_load_template_missing_returns_none(tmp_path):
    assert _load_template(str(tmp_path / "nope.png"), True) is None


def test_load_template_is_cached(tmp_path):
    image = np.zeros((6, 6, 3), dtype=np.uint8)
    image[1:4, 1:4] = 255
    path = tmp_path / "tpl.png"
    cv2.imwrite(str(path), image)
    first = _load_template(str(path), True)
    second = _load_template(str(path), True)
    assert first is not None
    assert first is second


def test_encode_frame_downsizes_wide_frames():
    bot = _bot()
    frame = np.zeros((200, 3000, 3), dtype=np.uint8)
    encoded = bot._encode_frame(frame)
    assert encoded is not None
    payload, width, height = encoded
    assert width == 1280
    assert height < 200
    assert base64.b64decode(payload)[:2] == b"\xff\xd8"


def test_encode_frame_keeps_small_frames():
    bot = _bot()
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    _, width, height = bot._encode_frame(frame)
    assert (width, height) == (200, 100)


def test_match_key_and_boxes():
    bot = _bot()
    step = StubStep(MatchResult((10, 10), (10, 10), 0.9), last_match_label="Lbl")
    assert bot._match_key(step) == ("Lbl", (10, 10), (10, 10), 0.9)
    boxes = bot._boxes_for_step(step)
    assert boxes == [
        {"x": 10, "y": 10, "w": 10, "h": 10, "label": "Lbl", "confidence": 0.9}
    ]


def test_match_key_none_without_match():
    bot = _bot()
    assert bot._match_key(StubStep()) is None
    assert bot._match_key(None) is None


def test_annotate_draws_on_frame():
    bot = _bot()
    frame = np.zeros((50, 50, 3), dtype=np.uint8)
    step = StubStep(MatchResult((10, 10), (10, 10), 0.9), last_match_label="Lbl")
    annotated = bot._annotate(frame, step)
    assert annotated.shape == frame.shape
    assert int(annotated.sum()) > 0
    assert int(frame.sum()) == 0


def test_snapshot_broadcast_dedupes_same_match(fake_screen, fake_logger):
    bot = _bot(fake_logger, preview=True, preview_mode="snapshot")
    frames = []
    bot.on_frame = frames.append
    bot._routine = StubRoutine(
        StubStep(MatchResult((10, 10), (10, 10), 0.9), last_match_label="Lbl")
    )
    shot = np.zeros((20, 20, 3), dtype=np.uint8)
    bot._maybe_broadcast_frame(shot)
    bot._maybe_broadcast_frame(shot)
    assert len(frames) == 1
    assert frames[0]["action"] == "frame"

    bot._routine._step = StubStep(
        MatchResult((30, 30), (5, 5), 0.8), last_match_label="Other"
    )
    bot._maybe_broadcast_frame(shot)
    assert len(frames) == 2


def test_live_broadcast_respects_fps(fake_screen, fake_logger):
    bot = _bot(fake_logger, preview=True, preview_mode="live", preview_fps=5.0)
    frames = []
    bot.on_frame = frames.append
    bot._routine = StubRoutine(
        StubStep(MatchResult((10, 10), (10, 10), 0.9), last_match_label="Lbl")
    )
    shot = np.zeros((20, 20, 3), dtype=np.uint8)
    fake_screen.clock.now = 0.5
    bot._maybe_broadcast_frame(shot)
    fake_screen.clock.now = 0.6  # inside the 0.2s window -> skipped
    bot._maybe_broadcast_frame(shot)
    fake_screen.clock.now = 0.8  # past the window -> sent
    bot._maybe_broadcast_frame(shot)
    assert len(frames) == 2


def test_preview_disabled_sends_nothing(fake_logger):
    bot = _bot(fake_logger, preview=False)
    frames = []
    bot.on_frame = frames.append
    bot._maybe_broadcast_frame(np.zeros((20, 20, 3), dtype=np.uint8))
    assert frames == []


def test_is_routine_running_and_start_routine():
    bot = _bot()
    assert bot.is_routine_running() is False
    routine = StubRoutine()
    bot.start_routine(routine)
    assert bot.is_routine_running() is True
    routine.done = True
    assert bot.is_routine_running() is False


def test_start_stop_thread_lifecycle():
    bot = _bot()
    bot._run = lambda: bot._stop_event.wait(2)
    bot.start()
    assert bot._thread is not None
    assert bot._thread.is_alive()
    bot.stop()
    assert bot._thread is None


def test_start_routine_clears_preview_when_enabled():
    bot = _bot(preview=True)
    frames = []
    bot.on_frame = frames.append
    bot.start_routine(StubRoutine())
    assert frames == [{"action": "clear"}]


def test_check_interval_is_mutable_at_runtime():
    bot = _bot()
    assert bot.check_interval == 0.5
    bot.check_interval = 1.25
    assert bot.check_interval == 1.25
