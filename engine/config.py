from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PlanConfig:
    delay: float = 0.0
    game_path: str | None = None
    tab_name: str | None = None
    capture_width: int | None = None  # reference capture width templates were recorded at
    capture_height: int | None = None  # reference capture height templates were recorded at
