from __future__ import annotations

from core.match_result import MatchResult
from routines.base import RECOVER, WAIT
from routines.step import Step


def test_log_prefix_default():
    assert Step().log_prefix() == '[step 0 "step"]'


def test_log_prefix_uses_label_and_index():
    step = Step()
    step.index = 3
    step.label = "go"
    assert step.log_prefix() == '[step 3 "go"]'


def test_first_call_initializes_seek_and_waits(fake_screen):
    fake_screen.clock.now = 100.0
    step = Step()
    step.timeout = 1.0
    assert step.seek_start_time == 0.0
    assert step.stuck_or_wait() == WAIT
    assert step.seek_start_time == 100.0


def test_timeout_triggers_recover(fake_screen):
    fake_screen.clock.now = 100.0
    step = Step()
    step.timeout = 1.0
    step.stuck_or_wait()
    fake_screen.clock.now = 102.0
    assert step.stuck_or_wait() == RECOVER


def test_none_timeout_never_recovers(fake_screen):
    fake_screen.clock.now = 100.0
    step = Step()
    step.timeout = None
    step.stuck_or_wait()
    fake_screen.clock.now = 10_000.0
    assert step.stuck_or_wait() == WAIT


def test_reset_click_state():
    step = Step()
    step.click_count = 2
    step.seek_start_time = 5.0
    step.reset_click_state()
    assert step.click_count == 0
    assert step.seek_start_time == 0.0


def test_reset_clears_match_cache(fake_logger):
    step = Step()
    step.logger = fake_logger
    step.last_match = MatchResult((1, 1), (1, 1), 0.9)
    step.last_match_label = "x"
    step.reset()
    assert step.last_match is None
    assert step.last_match_label is None
