from __future__ import annotations

import os
import types
from datetime import datetime

import numpy as np
import pytest

from core.recorder import Recorder


class _FakeKey:
    f6 = object()
    f7 = object()
    f8 = object()
    f9 = object()
    f10 = object()


class _FakeListener:
    def __init__(self, on_press=None, on_release=None):
        self.on_press_cb = on_press
        self.on_release_cb = on_release
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


@pytest.fixture
def fake_recorder_deps(monkeypatch, tmp_path):
    fake_keyboard = types.SimpleNamespace(Listener=_FakeListener, Key=_FakeKey)
    monkeypatch.setattr("core.recorder.keyboard", fake_keyboard)
    monkeypatch.setattr("core.recorder.TOGGLE_KEY", _FakeKey.f8)
    monkeypatch.setattr("core.recorder.CROP_KEY", _FakeKey.f9)
    monkeypatch.setattr("core.recorder.NEXT_KEY", _FakeKey.f10)
    monkeypatch.setattr("core.recorder.PREV_KEY", _FakeKey.f7)
    monkeypatch.setattr("core.recorder.UNDO_KEY", _FakeKey.f6)
    monkeypatch.setattr("core.recorder.RECORDED_DIR", str(tmp_path / "recorded"))

    def fake_resolve(sct, fw):
        return {"left": 0, "top": 0, "width": 100, "height": 100}, (0, 0)

    monkeypatch.setattr("core.recorder.resolve_capture_region", fake_resolve)

    def fake_capture(sct, region):
        return np.zeros((100, 100, 3), dtype=np.uint8)

    monkeypatch.setattr("core.recorder._capture", fake_capture)

    fixed_now = datetime(2026, 9, 20, 12, 0)
    monkeypatch.setattr(
        "core.recorder.datetime",
        type("dt", (), {"now": staticmethod(lambda: fixed_now)})(),
    )
    return tmp_path


@pytest.fixture
def recorder(fake_recorder_deps):
    return Recorder()


def test_start_stop_with_no_steps_returns_none(recorder):
    assert recorder.start() is True
    assert recorder.state == "RECORDING"
    assert recorder.stop() is None
    assert recorder.state == "IDLE"


def test_accept_target_writes_crop_and_returns_target(recorder, fake_recorder_deps):
    recorder.start(name="my flow")
    crop = np.full((20, 20, 3), 128, dtype=np.uint8)
    target = recorder.accept_target([crop], "left_click")
    assert target is not None
    assert target["action"] == "left_click"
    assert target["template"].startswith("templates/recorded/my flow/")
    assert os.path.exists(os.path.join(fake_recorder_deps, "recorded", "my flow"))
    assert recorder.status()["name"] == "my flow"


def test_dedupe_identical_crops_reuses_file(recorder, fake_recorder_deps):
    recorder.start()
    crop = np.full((10, 10, 3), 64, dtype=np.uint8)
    target1 = recorder.accept_target([crop], "left_click")
    target2 = recorder.accept_target([crop], "left_click")
    assert target1["template"] == target2["template"]
    files = [
        f
        for f in os.listdir(os.path.join(fake_recorder_deps, "recorded", recorder._slug))
        if f.endswith(".png")
    ]
    assert len(files) == 1


def test_multi_crop_main_and_validation(recorder, fake_recorder_deps):
    recorder.start()
    main = np.full((10, 10, 3), 1, dtype=np.uint8)
    val = np.full((10, 10, 3), 2, dtype=np.uint8)
    target = recorder.accept_target([main, val], "left_click")
    template = target["template"]
    assert isinstance(template, list)
    assert len(template) == 2
    assert template[0].endswith("_main.png")
    assert template[1].endswith("_val1.png")


def test_scroll_target_includes_scroll_fields(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 7, dtype=np.uint8)
    target = recorder.accept_target([crop], "left_click", scroll_dir=-1, scroll_anchor=(50, 50))
    assert target["scrollValue"] == -5
    assert target["scroll_point"] == [50, 50]


def test_accept_target_stores_offset(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 3, dtype=np.uint8)
    target = recorder.accept_target([crop], "left_click", offset=(5, -3))
    assert target["offset_x"] == 5
    assert target["offset_y"] == -3


def test_accept_target_defaults_offset_to_zero(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 4, dtype=np.uint8)
    target = recorder.accept_target([crop], "left_click")
    assert target["offset_x"] == 0
    assert target["offset_y"] == 0


def test_accept_targets_accumulate_into_current_step(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 5, dtype=np.uint8)
    recorder.accept_target([crop], "left_click")
    recorder.accept_target([crop], "right_click")
    status = recorder.status()
    assert status["target_count"] == 2
    assert status["step_count"] == 0
    assert len(status["current_targets"]) == 2
    assert status["current_targets"][0]["action"] == "left_click"
    assert status["current_targets"][1]["action"] == "right_click"


def test_next_step_builds_step_with_targets(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 6, dtype=np.uint8)
    recorder.accept_target([crop], "left_click")
    recorder.accept_target([crop], "right_click")
    step = recorder.next_step()
    assert step is not None
    assert step["label"] == "step 1"
    assert len(step["targets"]) == 2
    status = recorder.status()
    assert status["step_count"] == 1
    assert status["target_count"] == 0
    assert status["step_index"] == 2
    assert len(status["steps"]) == 1
    assert status["steps"][0]["label"] == "step 1"
    assert len(status["steps"][0]["targets"]) == 2


def test_next_step_without_targets_returns_none(recorder):
    recorder.start()
    assert recorder.next_step() is None
    assert recorder.status()["step_count"] == 0


def test_begin_crop_returns_frame_region(recorder):
    recorder.start()
    frame, region = recorder.begin_crop()
    assert frame.shape == (100, 100, 3)
    assert region["width"] == 100


def test_begin_crop_captures_full_screen(recorder, monkeypatch):
    recorder.start()
    seen = {}

    def fake_resolve(sct, fw):
        seen["fw"] = fw
        return {"left": 0, "top": 0, "width": 10, "height": 10}, (0, 0)

    monkeypatch.setattr("core.recorder.resolve_capture_region", fake_resolve)
    recorder.begin_crop()
    assert seen["fw"] is None


def test_hotkey_toggle_crop_and_next(recorder):
    toggles = []
    crops = []
    nexts = []
    rec = Recorder(
        on_toggle=lambda: toggles.append(True),
        on_crop_request=lambda: crops.append(True),
        on_next_step=lambda: nexts.append(True),
    )
    rec.start()
    listener = rec._listener
    assert listener is not None
    assert listener.started
    listener.on_press_cb(_FakeKey.f8)
    listener.on_press_cb(_FakeKey.f9)
    listener.on_press_cb(_FakeKey.f10)
    assert len(toggles) == 1
    assert len(crops) == 1
    assert len(nexts) == 1


def test_stop_returns_plan_dict(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 9, dtype=np.uint8)
    recorder.accept_target([crop], "right_click")
    data = recorder.stop()
    assert data is not None
    assert data["name"] == "recorded 2026-09-20 1200"
    assert len(data["steps"]) == 1
    assert data["steps"][0]["targets"][0]["action"] == "right_click"


def test_previous_step_reopens_last_step(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 9, dtype=np.uint8)
    recorder.accept_target([crop], "left_click")
    recorder.next_step()
    assert recorder.status()["step_index"] == 2
    reopened = recorder.previous_step()
    assert reopened is not None
    assert reopened["label"] == "step 1"
    status = recorder.status()
    assert status["step_count"] == 1
    assert status["step_index"] == 1
    assert status["target_count"] == 1


def test_previous_step_saves_current_then_rewinds(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 9, dtype=np.uint8)
    recorder.accept_target([crop], "left_click")
    recorder.next_step()
    recorder.accept_target([crop], "right_click")
    reopened = recorder.previous_step()
    assert reopened is not None
    assert reopened["label"] == "step 1"
    status = recorder.status()
    assert status["step_count"] == 2
    assert status["step_index"] == 1
    assert status["target_count"] == 1
    assert status["current_targets"][0]["action"] == "left_click"


def test_previous_step_noop_when_no_steps(recorder):
    recorder.start()
    assert recorder.previous_step() is None
    assert recorder.status()["step_index"] == 1


def test_previous_step_walks_back_multiple_steps(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 9, dtype=np.uint8)
    recorder.accept_target([crop], "left_click")
    recorder.next_step()
    recorder.accept_target([crop], "right_click")
    recorder.next_step()
    recorder.accept_target([crop], "scroll")

    back_to_2 = recorder.previous_step()
    assert back_to_2 is not None
    assert back_to_2["label"] == "step 2"
    status = recorder.status()
    assert status["step_count"] == 3
    assert status["step_index"] == 2
    assert status["current_targets"][0]["action"] == "right_click"

    back_to_1 = recorder.previous_step()
    assert back_to_1 is not None
    assert back_to_1["label"] == "step 1"
    status = recorder.status()
    assert status["step_count"] == 3
    assert status["step_index"] == 1
    assert status["current_targets"][0]["action"] == "left_click"

    assert recorder.previous_step() is None
    assert recorder.status()["step_index"] == 1


def test_next_step_after_previous_moves_forward(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 9, dtype=np.uint8)
    recorder.accept_target([crop], "left_click")
    recorder.next_step()
    recorder.accept_target([crop], "right_click")
    recorder.next_step()
    recorder.accept_target([crop], "scroll")

    recorder.previous_step()  # to step 2
    forward_to_3 = recorder.next_step()
    assert forward_to_3 is not None
    assert forward_to_3["label"] == "step 3"
    status = recorder.status()
    assert status["step_count"] == 3
    assert status["step_index"] == 3
    assert status["current_targets"][0]["action"] == "scroll"


def test_previous_step_at_first_step_keeps_targets(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 9, dtype=np.uint8)
    recorder.accept_target([crop], "left_click")
    recorder.next_step()
    recorder.accept_target([crop], "right_click")
    recorder.previous_step()
    assert recorder.status()["step_index"] == 1

    assert recorder.previous_step() is None
    status = recorder.status()
    assert status["step_index"] == 1
    assert status["target_count"] == 1

    forward = recorder.next_step()
    assert forward is not None
    assert forward["label"] == "step 2"
    assert recorder.status()["step_index"] == 2


def test_remove_target_persists_across_navigation(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 9, dtype=np.uint8)
    recorder.accept_target([crop], "left_click")
    recorder.next_step()
    recorder.accept_target([crop], "right_click")
    recorder.next_step()

    recorder.previous_step()
    assert recorder.remove_target(-1) is not None

    recorder.previous_step()
    forward = recorder.next_step()
    assert forward is not None
    assert recorder.status()["step_index"] == 2
    assert recorder.status()["target_count"] == 0


def test_stop_drops_empty_steps(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 9, dtype=np.uint8)
    recorder.accept_target([crop], "left_click")
    recorder.next_step()
    recorder.accept_target([crop], "right_click")
    recorder.next_step()
    recorder.previous_step()
    recorder.remove_target(-1)

    data = recorder.stop()
    assert data is not None
    assert len(data["steps"]) == 1
    assert data["steps"][0]["label"] == "step 1"


def test_stop_commits_pending_step(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 9, dtype=np.uint8)
    recorder.accept_target([crop], "left_click")
    data = recorder.stop()
    assert data is not None
    assert len(data["steps"]) == 1


def test_remove_target_by_index(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 9, dtype=np.uint8)
    recorder.accept_target([crop], "left_click")
    recorder.accept_target([crop], "right_click")
    removed = recorder.remove_target(0)
    assert removed is not None
    assert removed["action"] == "left_click"
    status = recorder.status()
    assert status["target_count"] == 1
    assert status["current_targets"][0]["action"] == "right_click"


def test_remove_target_last(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 9, dtype=np.uint8)
    recorder.accept_target([crop], "left_click")
    recorder.accept_target([crop], "right_click")
    removed = recorder.remove_target(-1)
    assert removed is not None
    assert removed["action"] == "right_click"
    assert recorder.status()["target_count"] == 1


def test_remove_target_relabels_remaining(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 9, dtype=np.uint8)
    recorder.accept_target([crop], "left_click")
    recorder.accept_target([crop], "right_click")
    recorder.remove_target(0)
    labels = [t["label"] for t in recorder.status()["current_targets"]]
    assert labels == ["step 1 target 1"]


def test_remove_target_out_of_range_returns_none(recorder):
    recorder.start()
    crop = np.full((10, 10, 3), 9, dtype=np.uint8)
    recorder.accept_target([crop], "left_click")
    assert recorder.remove_target(5) is None
    assert recorder.remove_target(-5) is None


def test_hotkey_prev_and_undo(recorder):
    prevs = []
    undos = []
    rec = Recorder(
        on_prev_step=lambda: prevs.append(True),
        on_remove_target=lambda: undos.append(True),
    )
    rec.start()
    listener = rec._listener
    assert listener is not None
    listener.on_press_cb(_FakeKey.f7)
    listener.on_press_cb(_FakeKey.f6)
    assert len(prevs) == 1
    assert len(undos) == 1


def test_hotkey_repeats_are_ignored_until_release(recorder):
    prevs = []
    rec = Recorder(on_prev_step=lambda: prevs.append(True))
    rec.start()
    listener = rec._listener
    assert listener is not None
    listener.on_press_cb(_FakeKey.f7)
    listener.on_press_cb(_FakeKey.f7)
    assert len(prevs) == 1
    listener.on_release_cb(_FakeKey.f7)
    listener.on_press_cb(_FakeKey.f7)
    assert len(prevs) == 2


class TestEditRecording:
    """Suite: seeding the recorder from an existing plan."""

    @pytest.mark.positive
    def test_start_edit_loads_steps_and_targets(self, recorder):
        """start_edit copies the plan's steps and lands on the last step."""
        plan = {
            "name": "existing plan",
            "steps": [
                {
                    "type": "click",
                    "label": "step 1",
                    "targets": [
                        {
                            "template": "templates/recorded/existing/0001_01_main.png",
                            "action": "left_click",
                            "offset_x": 1,
                            "offset_y": 2,
                        }
                    ],
                },
                {
                    "type": "click",
                    "label": "step 2",
                    "targets": [
                        {
                            "template": "templates/recorded/existing/0002_01_main.png",
                            "action": "right_click",
                        }
                    ],
                },
            ],
        }
        assert recorder.start_edit("existing", plan) is True
        status = recorder.status()
        assert status["editing"] is True
        assert status["plan_name"] == "existing"
        assert status["step_count"] == 2
        assert status["step_index"] == 2
        assert status["target_count"] == 1
        assert status["current_targets"][0]["action"] == "right_click"

    @pytest.mark.positive
    def test_start_edit_derives_slug_from_template_paths(self, recorder):
        """The recording slug is derived from templates/recorded/<slug>/ paths."""
        plan = {
            "steps": [
                {
                    "type": "click",
                    "targets": [
                        {
                            "template": [
                                "templates/recorded/my slug/0001_01_main.png",
                                "templates/recorded/my slug/0001_01_val1.png",
                            ],
                            "action": "left_click",
                        }
                    ],
                }
            ],
        }
        recorder.start_edit("existing", plan)
        assert recorder._slug == "my slug"

    @pytest.mark.positive
    def test_start_edit_falls_back_to_name_slug_when_no_recorded_templates(self, recorder):
        """Plans without recorded-mode templates get a slug based on the plan name."""
        plan = {
            "name": "hand made",
            "steps": [
                {
                    "type": "click",
                    "targets": [
                        {"template": "templates/foo.png", "action": "left_click"}
                    ],
                }
            ],
        }
        recorder.start_edit("hand made", plan)
        assert recorder._slug == "hand made"

    @pytest.mark.positive
    def test_edit_navigation_adds_targets_to_existing_step(self, recorder):
        """Accepting a crop while editing an existing step appends a target to it."""
        plan = {
            "steps": [
                {
                    "type": "click",
                    "label": "step 1",
                    "targets": [
                        {
                            "template": "templates/recorded/existing/0001_01_main.png",
                            "action": "left_click",
                        }
                    ],
                }
            ],
        }
        recorder.start_edit("existing", plan)
        crop = np.full((10, 10, 3), 9, dtype=np.uint8)
        target = recorder.accept_target([crop], "continue")
        assert target is not None
        status = recorder.status()
        assert status["target_count"] == 2
        assert status["step_count"] == 1
        assert len(status["steps"][0]["targets"]) == 2
        assert status["steps"][0]["targets"][1]["action"] == "continue"

    @pytest.mark.positive
    def test_edit_next_step_appends_new_step(self, recorder):
        """Next step from the last existing step creates a brand-new step."""
        plan = {
            "steps": [
                {
                    "type": "click",
                    "label": "step 1",
                    "targets": [
                        {
                            "template": "templates/recorded/existing/0001_01_main.png",
                            "action": "left_click",
                        }
                    ],
                }
            ],
        }
        recorder.start_edit("existing", plan)
        recorder.next_step()
        status = recorder.status()
        assert status["step_count"] == 1
        assert status["step_index"] == 2
        crop = np.full((10, 10, 3), 9, dtype=np.uint8)
        recorder.accept_target([crop], "left_click")
        recorder.next_step()
        status = recorder.status()
        assert status["step_count"] == 2
        assert status["step_index"] == 3

    @pytest.mark.positive
    def test_stop_edit_returns_original_plan_name(self, recorder):
        """Stopping an edit session reports the original plan name for overwrite."""
        plan = {
            "steps": [
                {
                    "type": "click",
                    "targets": [
                        {
                            "template": "templates/recorded/existing/0001_01_main.png",
                            "action": "left_click",
                        }
                    ],
                }
            ],
        }
        recorder.start_edit("existing", plan)
        data = recorder.stop()
        assert data is not None
        assert data.get("editing") is True
        assert data.get("plan_name") == "existing"
