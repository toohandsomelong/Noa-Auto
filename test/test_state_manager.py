from __future__ import annotations

from core.state_manager import BotState, StateManager


def test_change_notifies_listeners():
    manager = StateManager()
    seen = []
    manager.on_state_change(seen.append)
    manager.state = BotState.RUNNING
    assert seen == [BotState.RUNNING]


def test_same_state_is_not_notified():
    manager = StateManager()
    seen = []
    manager.on_state_change(seen.append)
    manager.state = BotState.IDLE
    assert seen == []


def test_multiple_transitions_fire_in_order():
    manager = StateManager()
    seen = []
    manager.on_state_change(seen.append)
    manager.state = BotState.RUNNING
    manager.state = BotState.PAUSED
    manager.state = BotState.RUNNING
    assert seen == [BotState.RUNNING, BotState.PAUSED, BotState.RUNNING]


def test_is_active():
    manager = StateManager()
    assert manager.is_active() is False
    manager.state = BotState.RUNNING
    assert manager.is_active() is True
    manager.state = BotState.PAUSED
    assert manager.is_active() is True
    manager.state = BotState.STOPPED
    assert manager.is_active() is False


def test_listener_exception_is_isolated():
    manager = StateManager()
    good = []

    def bad(_state):
        raise RuntimeError("boom")

    manager.on_state_change(bad)
    manager.on_state_change(good.append)
    manager.state = BotState.RUNNING
    assert good == [BotState.RUNNING]
