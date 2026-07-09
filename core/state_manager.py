from collections.abc import Callable
from enum import Enum


class BotState(Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


class StateManager:
    def __init__(self) -> None:
        self._state = BotState.IDLE
        self._listeners: list[Callable[[BotState], None]] = []

    @property
    def state(self) -> BotState:
        return self._state

    @state.setter
    def state(self, new_state: BotState) -> None:
        if new_state == self._state:
            return
        self._state = new_state
        for listener in self._listeners:
            try:
                listener(new_state)
            except Exception:
                pass

    def on_state_change(self, listener: Callable[[BotState], None]) -> None:
        self._listeners.append(listener)

    def is_active(self) -> bool:
        return self._state in (BotState.RUNNING, BotState.PAUSED)
