from logger import Logger
from state_manager import StateManager
from game_launcher import GameLauncher
from focus_watcher import FocusWatcher
from ui import App


def main():
    logger = Logger()
    state_manager = StateManager()
    game_launcher = GameLauncher(logger)
    focus_watcher = FocusWatcher()

    app = App(logger, state_manager, game_launcher, focus_watcher)
    app.run()


if __name__ == "__main__":
    main()
