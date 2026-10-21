from __future__ import annotations

import pytest

from engine.config import PlanConfig


class TestPlanConfigDefaults:
    """Suite: the trimmed PlanConfig surface (delay/paths/capture reference only)."""

    @pytest.mark.positive
    def test_defaults(self):
        """A fresh config has zero delay, no target, and no capture reference size."""
        cfg = PlanConfig()
        assert cfg.delay == 0.0
        assert cfg.game_path is None
        assert cfg.tab_name is None
        assert cfg.capture_width is None
        assert cfg.capture_height is None

    @pytest.mark.edge
    def test_fields_are_mutable(self):
        """PlanConfig is a mutable dataclass (not frozen)."""
        cfg = PlanConfig()
        cfg.delay = 0.5
        cfg.tab_name = "Game"
        assert cfg.delay == 0.5
        assert cfg.tab_name == "Game"
