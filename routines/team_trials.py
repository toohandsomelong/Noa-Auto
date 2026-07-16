from __future__ import annotations

# LEGACY / REFERENCE ONLY
# This Python builder is no longer registered or used at runtime.
# The active plan is now ``plans/team_trials.json``.

from typing import Any

from routines.click_action import ClickAction
from routines.click_step import ClickStep
from routines.config import RoutineConfig
from routines.routine import Routine
from routines.step import Step
from routines.target import Target


CONFIG = RoutineConfig(delay=0.5, max_step_retry=15, timeout=15.0, max_recover=3)

def build_team_trials_routine(logger: Any) -> Routine:
    select_opponent_index = 4
    home_index = 14

    steps: list[Step] = [
        ClickStep([Target("templates/main/raceMenuNoActive.png")]),
        ClickStep([Target("templates/main/raceMenuActive.png", action=ClickAction.CONTINUE)]),
        ClickStep([Target("templates/racemenu/teamtrials.png")]),
        ClickStep([Target("templates/racemenu/teamtrials/1.png")]),
        ClickStep(
            [
                Target(
                    "templates/racemenu/teamtrials/end.png",
                    action=ClickAction.RIGHT_CLICK,
                    goto=home_index,
                ),
                Target(
                    "templates/racemenu/teamtrials/selectopponent.png",
                    offset_y=50,
                ),
            ],
            ready_delay=3.0,
        ),
        ClickStep([Target("templates/racemenu/teamtrials/next.png")]),
        ClickStep([Target("templates/racemenu/teamtrials/3.png")]),
        ClickStep(
            [
                Target(
                    "templates/racemenu/teamtrials/quickYes.png",
                    action=ClickAction.CONTINUE,
                ),
                Target("templates/racemenu/teamtrials/quickNo.png"),
            ],
        ),
        ClickStep([Target("templates/racemenu/teamtrials/4.png")]),
        ClickStep([Target("templates/racemenu/teamtrials/5.png")]),
        ClickStep([Target("templates/racemenu/teamtrials/2-6.png")]),
        ClickStep(
            [
                Target(
                    "templates/racemenu/teamtrials/highscore.png",
                    stay_on_confirm=True,
                ),
                Target(
                    "templates/racemenu/teamtrials/shop.png",
                    action=ClickAction.RIGHT_CLICK,
                    stay_on_confirm=True,
                ),
                Target("templates/racemenu/teamtrials/7.png"),
            ],
            alt_chain=[ #problem here, alt chain should not use string
                "templates/racemenu/teamtrials/smallnext.png",
                "templates/racemenu/teamtrials/2-6.png",
            ],
        ),
        ClickStep(
            [Target("templates/racemenu/teamtrials/end.png", action=ClickAction.RIGHT_CLICK)],
            goto_step_not_found=select_opponent_index,
        ),
        ClickStep([Target("templates/racemenu/teamtrials/smallnext.png")]),
        ClickStep([Target("templates/main/home.png")]),
    ]

    recover_steps: list[Step] = [
        ClickStep([Target("templates/main/home.png")]),
    ]

    return Routine("team_trials", steps, logger, config=CONFIG, recover_steps=recover_steps)
