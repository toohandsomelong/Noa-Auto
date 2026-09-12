from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RoutineConfig:
    max_step_retry: int | None = None  # if None, step retries will not trigger recover and timeout
    timeout: float | None = None  # if None, timeout will not trigger recover
    resync_timeout: float | None = None  # if None, resync polls forever (never aborts)
    delay: float = 0.0
    game_path: str | None = None
    tab_name: str | None = None
