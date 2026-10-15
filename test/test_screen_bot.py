from __future__ import annotations

import base64
import types

import cv2
import numpy as np
import pytest

from core.match_result import MatchResult
from core.screen_bot import ScreenBot, _load_template, _match, resolve_capture_region
from core.state_manager import BotState, StateManager


class StubStep:
    def __init__(self, match=None, label="L", last_match_label=None) -> None:
        self.index = 0
        self.label = label
        self.last_match = match
        self.last_match_label = last_match_label


class StubPlanRunner:
    def __init__(self, step=None, name="R", plan_key=None) -> None:
        self.done = False
        self._step = step
        self.name = name
        self.plan_key = plan_key

    def current_step(self):
        return self._step


def _bot(fake_logger=None, **kwargs) -> ScreenBot:
    """Build a ScreenBot with no focus watcher for isolated unit tests."""
    return ScreenBot(fake_logger, StateManager(), None, **kwargs)


class TestTemplateMatching:
    """Suite: low-level template matching and template caching."""

    @pytest.mark.positive
    def test_match_finds_exact_crop(self):
        """An exact crop matches at high confidence and the expected location."""
        rng = np.random.default_rng(1)
        screen = rng.integers(0, 256, (60, 60, 3), dtype=np.uint8)
        template = screen[20:35, 20:35].copy()
        result = _match(screen, template, 0.9, grayscale=False)
        assert result is not None
        assert result.location == (20, 20)
        assert result.size == (15, 15)
        assert result.confidence > 0.9

    @pytest.mark.negative
    def test_match_below_threshold_returns_none(self):
        """A real-but-imperfect match is rejected once the threshold exceeds its confidence."""
        screen = np.zeros((60, 60, 3), dtype=np.uint8)
        template = np.zeros((15, 15, 3), dtype=np.uint8)
        template[:, :7] = 255
        screen[20:35, 20:35] = template
        screen[22:25, 22:25] = 120

        found = _match(screen, template, 0.0, grayscale=False)
        assert found is not None
        assert 0.5 < found.confidence < 1.0

        assert _match(screen, template, found.confidence + 0.01, grayscale=False) is None
        assert _match(screen, template, 0.5, grayscale=False) is not None

    @pytest.mark.negative
    def test_load_template_missing_returns_none(self, tmp_path):
        """Loading a non-existent template yields None."""
        assert _load_template(str(tmp_path / "nope.png"), True) is None

    @pytest.mark.edge
    def test_load_template_is_cached(self, tmp_path):
        """Template loading is cached (same object returned)."""
        image = np.zeros((6, 6, 3), dtype=np.uint8)
        image[1:4, 1:4] = 255
        path = tmp_path / "tpl.png"
        cv2.imwrite(str(path), image)
        first = _load_template(str(path), True)
        second = _load_template(str(path), True)
        assert first is not None
        assert first is second


class TestFrameEncodingAndMatchKeys:
    """Suite: preview frame encoding, annotation, and match-key/box serialization."""

    @pytest.mark.positive
    def test_encode_frame_downsizes_wide_frames(self):
        """Wide frames are downscaled to the 1280px preview width."""
        bot = _bot()
        frame = np.zeros((200, 3000, 3), dtype=np.uint8)
        encoded = bot._encode_frame(frame)
        assert encoded is not None
        payload, width, height = encoded
        assert width == 1280
        assert height < 200
        assert base64.b64decode(payload)[:2] == b"\xff\xd8"

    @pytest.mark.positive
    def test_encode_frame_keeps_small_frames(self):
        """Small frames are encoded at their original size."""
        bot = _bot()
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        _, width, height = bot._encode_frame(frame)
        assert (width, height) == (200, 100)

    @pytest.mark.positive
    def test_match_key_and_boxes(self):
        """match_key/boxes reflect the step's last match and label."""
        bot = _bot()
        step = StubStep(MatchResult((10, 10), (10, 10), 0.9), last_match_label="Lbl")
        assert bot._match_key(step) == ("Lbl", (10, 10), (10, 10), 0.9)
        boxes = bot._boxes_for_step(step)
        assert boxes == [
            {"x": 10, "y": 10, "w": 10, "h": 10, "label": "Lbl", "confidence": 0.9}
        ]

    @pytest.mark.edge
    def test_match_key_none_without_match(self):
        """With no match (or no step) the match key is None."""
        bot = _bot()
        assert bot._match_key(StubStep()) is None
        assert bot._match_key(None) is None

    @pytest.mark.positive
    def test_annotate_draws_on_frame(self):
        """Annotation draws on a copy and leaves the source frame untouched."""
        bot = _bot()
        frame = np.zeros((50, 50, 3), dtype=np.uint8)
        step = StubStep(MatchResult((10, 10), (10, 10), 0.9), last_match_label="Lbl")
        annotated = bot._annotate(frame, step)
        assert annotated.shape == frame.shape
        assert int(annotated.sum()) > 0
        assert int(frame.sum()) == 0


class TestPreviewBroadcast:
    """Suite: preview frame broadcasting (snapshot dedupe, live fps, disabled)."""

    @pytest.mark.positive
    def test_snapshot_broadcast_dedupes_same_match(self, fake_screen, fake_logger):
        """Snapshot mode sends a frame only when the match key changes."""
        bot = _bot(fake_logger, preview=True, preview_mode="snapshot")
        frames = []
        bot.on_frame = frames.append
        bot._runner = StubPlanRunner(
            StubStep(MatchResult((10, 10), (10, 10), 0.9), last_match_label="Lbl")
        )
        shot = np.zeros((20, 20, 3), dtype=np.uint8)
        bot._maybe_broadcast_frame(shot)
        bot._maybe_broadcast_frame(shot)
        assert len(frames) == 1
        assert frames[0]["action"] == "frame"

        bot._runner._step = StubStep(MatchResult((30, 30), (5, 5), 0.8), last_match_label="Other")
        bot._maybe_broadcast_frame(shot)
        assert len(frames) == 2

    @pytest.mark.positive
    def test_live_broadcast_respects_fps(self, fake_screen, fake_logger):
        """Live mode throttles frames to the configured preview fps."""
        bot = _bot(fake_logger, preview=True, preview_mode="live", preview_fps=5.0)
        frames = []
        bot.on_frame = frames.append
        bot._runner = StubPlanRunner(
            StubStep(MatchResult((10, 10), (10, 10), 0.9), last_match_label="Lbl")
        )
        shot = np.zeros((20, 20, 3), dtype=np.uint8)
        fake_screen.clock.now = 0.5
        bot._maybe_broadcast_frame(shot)
        fake_screen.clock.now = 0.6
        bot._maybe_broadcast_frame(shot)
        fake_screen.clock.now = 0.8
        bot._maybe_broadcast_frame(shot)
        assert len(frames) == 2

    @pytest.mark.negative
    def test_preview_disabled_sends_nothing(self, fake_logger):
        """With preview disabled, no frames are broadcast."""
        bot = _bot(fake_logger, preview=False)
        frames = []
        bot.on_frame = frames.append
        bot._maybe_broadcast_frame(np.zeros((20, 20, 3), dtype=np.uint8))
        assert frames == []


class TestPlanRunningAndStepSignals:
    """Suite: plan-running state, thread lifecycle, and step-change signaling."""

    @pytest.mark.positive
    def test_is_plan_running_and_start_plan(self):
        """A plan counts as running until it reports done."""
        bot = _bot()
        assert bot.is_plan_running() is False
        plan = StubPlanRunner()
        bot.start_plan(plan)
        assert bot.is_plan_running() is True
        plan.done = True
        assert bot.is_plan_running() is False

    @pytest.mark.positive
    def test_start_stop_thread_lifecycle(self):
        """start()/stop() manage the loop thread."""
        bot = _bot()
        bot._run = lambda: bot._stop_event.wait(2)
        bot.start()
        assert bot._thread is not None
        assert bot._thread.is_alive()
        bot.stop()
        assert bot._thread is None

    @pytest.mark.positive
    def test_start_plan_clears_preview_when_enabled(self):
        """Starting a plan clears the preview when preview is enabled."""
        bot = _bot(preview=True)
        frames = []
        bot.on_frame = frames.append
        bot.start_plan(StubPlanRunner())
        assert frames == [{"action": "clear"}]

    @pytest.mark.edge
    def test_check_interval_is_mutable_at_runtime(self, fake_screen, monkeypatch):
        """check_interval can be changed mid-run and takes effect on the next cycle."""
        import core.screen_bot as sb

        class _Sct:
            monitors = [{"left": 0, "top": 0, "width": 1920, "height": 1080}]

            def close(self):
                pass

        monkeypatch.setattr(sb, "mss", types.SimpleNamespace(mss=lambda: _Sct()))
        bot = _bot(preview=False)
        bot.state_manager.state = BotState.RUNNING

        times: list[float] = []

        def capture(sct=None, region=None):
            times.append(round(fake_screen.clock.now, 3))
            fake_screen.clock.now += 0.02
            if len(times) == 2:
                bot.check_interval = 1.0
            if len(times) >= 4:
                bot._stop_event.set()
            return "screen"

        monkeypatch.setattr(sb, "_capture", capture)
        bot._run()

        gaps = [round(times[i + 1] - times[i], 2) for i in range(len(times) - 1)]
        assert len(times) == 4
        assert 0.5 <= gaps[0] <= 0.55
        assert all(1.0 <= g <= 1.05 for g in gaps[1:])

    @pytest.mark.positive
    def test_step_signal_emitted_once_per_step_change(self, fake_logger):
        """A step signal fires once per change and dedupes repeats."""
        bot = _bot(fake_logger, preview=False)
        steps = []
        bot.on_step = steps.append

        step = StubStep(label="S0")
        plan = StubPlanRunner(step, name="R")
        bot.start_plan(plan)
        bot._maybe_signal_step()
        assert len(steps) == 1
        assert steps[0]["action"] == "step"
        assert steps[0]["plan"] == "R"
        assert steps[0]["step_index"] == 0
        assert steps[0]["step_label"] == "S0"

        bot._maybe_signal_step()
        assert len(steps) == 1

        step.label = "S1"
        bot._maybe_signal_step()
        assert len(steps) == 2

    @pytest.mark.positive
    def test_step_signal_works_without_preview(self, fake_logger):
        """Step signals are independent of the preview toggle."""
        bot = _bot(fake_logger, preview=False)
        steps = []
        bot.on_step = steps.append
        bot.start_plan(StubPlanRunner(StubStep(), name="R"))
        bot._maybe_signal_step()
        assert len(steps) == 1

    @pytest.mark.positive
    def test_step_signal_resets_on_start_plan(self, fake_logger):
        """Starting a new plan resets the dedupe so the first step signals again."""
        bot = _bot(fake_logger)
        steps = []
        bot.on_step = steps.append

        bot.start_plan(StubPlanRunner(StubStep(), name="A"))
        bot._maybe_signal_step()
        assert steps[-1]["plan"] == "A"

        bot.start_plan(StubPlanRunner(StubStep(), name="B"))
        bot._maybe_signal_step()
        assert steps[-1]["plan"] == "B"

    @pytest.mark.edge
    def test_step_signal_prefers_plan_key_over_name(self, fake_logger):
        """The registry key is preferred over the display name in step signals."""
        bot = _bot(fake_logger, preview=False)
        steps = []
        bot.on_step = steps.append
        bot.start_plan(StubPlanRunner(StubStep(label="S0"), name="Monies", plan_key="recorded 2211"))
        bot._maybe_signal_step()
        assert steps[0]["plan"] == "recorded 2211"

    @pytest.mark.edge
    def test_step_signal_identifier_is_a_registry_key(self, tmp_plans, fake_logger):
        """A loaded plan's step signal uses its registry key."""
        import engine.plan_loader as pl
        from engine import list_plan_names

        pl.save_plan(
            "recorded 2211",
            {"name": "Monies", "steps": [{"type": "click", "label": "S0"}]},
        )
        plan = pl.build_plan_runner("recorded 2211", fake_logger)
        assert plan is not None

        bot = _bot(fake_logger, preview=False)
        emitted = []
        bot.on_step = emitted.append
        bot.start_plan(plan)
        bot._maybe_signal_step()

        assert emitted[0]["plan"] in list_plan_names()


class TestCaptureRegionResolution:
    """Suite: capture-region resolution from the focused window or full screen."""

    @pytest.mark.positive
    def test_resolve_capture_region_uses_focus_watcher_hwnd(self, fake_win32):
        """A focused window's client area becomes the capture region."""
        fake_win32.add(123, "Game")
        fake_win32.set_rect(123, 10, 20, 800, 600)
        fw = type("FW", (), {"hwnd": 123})()
        sct = type("Sct", (), {"monitors": [{"left": 0, "top": 0, "width": 1920, "height": 1080}]})()
        region, origin = resolve_capture_region(sct, fw)
        assert region == {"left": 10, "top": 20, "width": 800, "height": 600}
        assert origin == (10, 20)

    @pytest.mark.negative
    def test_resolve_capture_region_iconic_returns_none(self, fake_win32):
        """A minimized window yields no region (tick skipped)."""
        fake_win32.add(123, "Game")
        fake_win32.set_rect(123, 0, 0, 800, 600)
        fake_win32.set_iconic(123, True)
        fw = type("FW", (), {"hwnd": 123})()
        sct = type("Sct", (), {"monitors": [{"left": 0, "top": 0, "width": 1920, "height": 1080}]})()
        assert resolve_capture_region(sct, fw) is None

    @pytest.mark.positive
    def test_screenbot_resolve_region_delegates(self, fake_win32):
        """ScreenBot._resolve_region delegates to resolve_capture_region."""
        fake_win32.add(123, "Game")
        fake_win32.set_rect(123, 5, 5, 400, 300)
        bot = _bot()
        bot.focus_watcher = type("FW", (), {"hwnd": 123})()
        sct = type("Sct", (), {"monitors": [{"left": 0, "top": 0, "width": 1920, "height": 1080}]})()
        region, origin = bot._resolve_region(sct)
        assert region["width"] == 400
        assert origin == (5, 5)


class TestPlanFinishedDispatch:
    """Suite: plan completion dispatch — on_plan_done firing and error isolation."""

    @pytest.mark.positive
    def test_notify_plan_finished_calls_on_plan_done(self, fake_logger):
        """A finished plan calls on_plan_done with the plan name."""
        bot = _bot(fake_logger)
        calls = []
        bot.on_plan_done = calls.append
        bot._notify_plan_finished(StubPlanRunner(name="R"))
        assert calls == ["R"]

    @pytest.mark.negative
    def test_raising_on_plan_done_is_logged_not_propagated(self, fake_logger):
        """A raising on_plan_done callback is logged, not propagated."""
        bot = _bot(fake_logger)

        def boom(name):
            raise RuntimeError("boom")

        bot.on_plan_done = boom
        bot._notify_plan_finished(StubPlanRunner(name="R"))
        assert any("on_plan_done" in msg for msg in fake_logger.messages("ERR"))

    @pytest.mark.edge
    def test_no_callback_is_noop(self, fake_logger):
        """With no on_plan_done callback, finishing is a no-op."""
        bot = _bot(fake_logger)
        assert bot._notify_plan_finished(StubPlanRunner(name="R")) is None
