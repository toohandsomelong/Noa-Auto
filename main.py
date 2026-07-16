from core.logger import Logger
from core.state_manager import StateManager
from core.game_launcher import GameLauncher
from core.focus_watcher import FocusWatcher
from core.screen_bot import ScreenBot
from web.bot_controller import BotController
from web.server import run_server


def build_screen_bot(logger, state_manager, focus_watcher):
    return ScreenBot(logger, state_manager, focus_watcher)


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
