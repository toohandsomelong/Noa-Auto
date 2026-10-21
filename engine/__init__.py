from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any, Callable

from engine.plan_loader import build_plan_runner, list_plan_names

if TYPE_CHECKING:
    from engine.plan_runner import PlanRunner


PLAN_BUILDER = Callable[[Any], "PlanRunner | None"]

PLANS: dict[str, PLAN_BUILDER] = {}


def refresh_plans() -> None:
    """Reload plan names from ``plans/*.json`` into :data:`PLANS` in place.

    This mutates the existing dict so imports that captured ``PLANS`` see
    new plans without restarting the process.
    """
    PLANS.clear()
    for name in list_plan_names():
        PLANS[name] = partial(build_plan_runner, name)


refresh_plans()
