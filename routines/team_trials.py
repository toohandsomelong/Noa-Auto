from __future__ import annotations

from typing import Any

from routines.click_rule import ClickRule
from routines.click_step import ClickStep
from routines.end_step import EndStep
from routines.routine import Routine
from routines.step import Step


def build_team_trials_routine(logger: Any) -> Routine:
    select_opponent_index = 4
    home_index = 14

    steps: list[Step] = [
        ClickStep([ClickRule("templates/main/raceMenuNoActive.png")]),
        ClickStep([ClickRule("templates/main/raceMenuActive.png", action="advance")]),
        ClickStep([ClickRule("templates/racemenu/teamtrials.png")]),
        ClickStep([ClickRule("templates/racemenu/teamtrials/1.png")]),
        ClickStep(
            [
                ClickRule(
                    "templates/racemenu/teamtrials/end.png",
                    action="right_click",
                    goto=home_index,
                ),
                ClickRule(
                    "templates/racemenu/teamtrials/selectopponent.png",
                    offset_y=50,
                ),
            ],
            ready_delay=2.0,
        ),
        ClickStep([ClickRule("templates/racemenu/teamtrials/2-6.png")]),
        ClickStep([ClickRule("templates/racemenu/teamtrials/3.png")]),
        ClickStep(
            [
                ClickRule(
                    "templates/racemenu/teamtrials/quickYes.png",
                    action="advance",
                ),
                ClickRule("templates/racemenu/teamtrials/quickNo.png"),
            ],
        ),
        ClickStep([ClickRule("templates/racemenu/teamtrials/4.png")]),
        ClickStep([ClickRule("templates/racemenu/teamtrials/5.png")]),
        ClickStep([ClickRule("templates/racemenu/teamtrials/2-6.png")]),
        ClickStep(
            [
                ClickRule(
                    "templates/racemenu/teamtrials/highscore.png",
                    stay_on_confirm=True,
                ),
                ClickRule(
                    "templates/racemenu/teamtrials/shop.png",
                    action="right_click",
                    stay_on_confirm=True,
                ),
                ClickRule("templates/racemenu/teamtrials/7.png"),
            ],
            alt_chain=[
                "templates/racemenu/teamtrials/smallnext.png",
                "templates/racemenu/teamtrials/2-6.png",
            ],
        ),
        ClickStep(
            [ClickRule("templates/racemenu/teamtrials/end.png", action="right_click")],
            goto_step_not_found=select_opponent_index,
        ),
        ClickStep([ClickRule("templates/racemenu/teamtrials/smallnext.png")]),
        ClickStep([ClickRule("templates/main/home.png")]),
        EndStep(),
    ]

    return Routine("team_trials", steps, logger)
