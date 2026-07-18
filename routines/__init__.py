from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any, Callable

from routines.plan_loader import build_routine_from_plan, list_plan_names

if TYPE_CHECKING:
    from routines.routine import Routine


ROUTINE_BUILDER = Callable[[Any], "Routine | None"]

ROUTINES: dict[str, ROUTINE_BUILDER] = {}


def refresh_routines() -> None:
    """Reload plan names from ``plans/*.json`` into :data:`ROUTINES` in place.

    This mutates the existing dict so imports that captured ``ROUTINES`` see
    new plans without restarting the process.
    """
    ROUTINES.clear()
    for name in list_plan_names():
        ROUTINES[name] = partial(build_routine_from_plan, name)


refresh_routines()
