from enum import Enum


class BotState(Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


class StateManager:
    def __init__(self):
        self._state = BotState.IDLE

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, new_state):
        self._state = new_state

    def is_active(self):
        return self._state in (BotState.RUNNING, BotState.PAUSED)
