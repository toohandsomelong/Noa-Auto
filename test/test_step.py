from __future__ import annotations

import pytest

from core.match_result import MatchResult
from engine.base import WAIT
from engine.step import Step


class TestStepBaseContract:
    """Suite: minimal Step base — logging prefix, lost-flag lifecycle, reset semantics."""

    @pytest.mark.positive
    def test_log_prefix_default(self):
        """Default prefix is the step index with a generic label."""
        assert Step().log_prefix() == '[step 0 "step"]'

    @pytest.mark.positive
    def test_log_prefix_uses_label_and_index(self):
        """Prefix reflects both the step index and its label."""
        step = Step()
        step.index = 3
        step.label = "go"
        assert step.log_prefix() == '[step 3 "go"]'

    @pytest.mark.positive
    def test_stuck_or_wait_sets_lost_and_returns_wait(self):
        """Seeking with nothing found marks the step lost and returns WAIT."""
        step = Step()
        assert step.lost is False
        assert step.stuck_or_wait() == WAIT
        assert step.lost is True

    @pytest.mark.negative
    def test_reset_clears_lost_and_match_cache(self, fake_logger):
        """reset() clears the lost flag, cached match, and match label."""
        step = Step()
        step.logger = fake_logger
        step.lost = True
        step.last_match = MatchResult((1, 1), (1, 1), 0.9)
        step.last_match_label = "x"
        step.reset()
        assert step.lost is False
        assert step.last_match is None
        assert step.last_match_label is None

    @pytest.mark.edge
    def test_tick_default_returns_wait_without_lost(self):
        """Base Step.tick stays WAIT and never marks itself lost (subclasses decide)."""
        step = Step()
        assert step.tick("screen") == WAIT
        assert step.lost is False

    @pytest.mark.edge
    def test_reset_without_logger_is_safe(self):
        """reset() must not crash when the step has no logger attached."""
        step = Step()
        step.lost = True
        step.reset()
        assert step.lost is False

    @pytest.mark.edge
    def test_reset_click_state_resets_count_only(self):
        """reset_click_state clears the click counter and leaves matches untouched."""
        step = Step()
        step.click_count = 2
        step.reset_click_state()
        assert step.click_count == 0
