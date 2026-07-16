from __future__ import annotations
from enum import IntEnum


class StepStatus(IntEnum):
    WAIT = -1
    DONE = -2
    RECOVER = -3
