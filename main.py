import json

from core.logger import Logger
from core.state_manager import StateManager
from core.game_launcher import GameLauncher
from core.focus_watcher import FocusWatcher
from core.screen_bot import ScreenBot
from web.bot_controller import BotController
from web.server import run_server

def build_screen_bot(logger, state_manager, focus_watcher):
    check_interval = 0.5
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
        check_interval = float(cfg.get("check_interval", 0.5))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        check_interval = 0.5
    check_interval = max(0.05, min(10.0, check_interval))
    return ScreenBot(logger, state_manager, focus_watcher, check_interval=check_interval)


def main():
    logger = Logger()
    state_manager = StateManager()
    game_launcher = GameLauncher(logger)
    focus_watcher = FocusWatcher()
    controller = BotController(logger, state_manager, game_launcher, focus_watcher)
    screen_bot = build_screen_bot(logger, state_manager, focus_watcher)
    controller.screen_bot = screen_bot

    run_server(controller)


if __name__ == "__main__":
    main()
