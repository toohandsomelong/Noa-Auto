from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchResult:
    location: tuple[int, int]
    size: tuple[int, int]
    confidence: float

    @property
    def center(self) -> tuple[int, int]:
        x, y = self.location
        w, h = self.size
        return x + w // 2, y + h // 2
