from logger import Logger
from state_manager import StateManager
from game_launcher import GameLauncher
from focus_watcher import FocusWatcher
from routine import build_team_trials_routine
from screen_bot import ScreenBot, Validator
from bot_controller import BotController
from server import run_server


def build_screen_bot(logger, state_manager, focus_watcher):
    bot = ScreenBot(logger, state_manager, focus_watcher)

    def start_team_trials():
        if bot.is_flag_set("teamtrials_done") or bot._routine is not None:
            return
        routine = build_team_trials_routine(
            logger,
            on_done=lambda: bot.set_flag("teamtrials_done", True),
        )
        bot.start_routine(routine)
        logger.info("Team trials routine started")

    def log_active(match):
        logger.info("Race menu active")
        start_team_trials()

    def click_race_menu(match):
        if bot.is_flag_set("teamtrials_done"):
            logger.info("Race menu inactive but team trials done; skipping click")
            return
        try:
            import pyautogui
            pyautogui.click(match.center[0], match.center[1])
            logger.info(f"Clicked race menu button at {match.center}")
        except ImportError:
            logger.warning("pyautogui not installed; cannot click race menu")

    bot.register(Validator("templates/main/raceMenuActive.png", action=log_active))
    bot.register(Validator("templates/main/raceMenuNoActive.png", action=click_race_menu))
    return bot


def main():
    logger = Logger()
    state_manager = StateManager()
    game_launcher = GameLauncher(logger)
    focus_watcher = FocusWatcher()
    screen_bot = build_screen_bot(logger, state_manager, focus_watcher)

    controller = BotController(logger, state_manager, game_launcher, focus_watcher, screen_bot)
    run_server(controller)


if __name__ == "__main__":
    main()
