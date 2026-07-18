from __future__ import annotations

import json
import os
from typing import Any

from routines.branch_step import BranchStep
from routines.click_action import ClickAction
from routines.click_step import ClickStep
from routines.config import RoutineConfig
from routines.target import Target
from routines.routine import Routine
from routines.step import Step


PLANS_DIR = "plans"


def list_plan_names() -> list[str]:
    """Return sorted plan names discovered from ``PLANS_DIR/*.json``."""
    if not os.path.isdir(PLANS_DIR):
        return []
    return sorted(
        os.path.splitext(entry)[0]
        for entry in os.listdir(PLANS_DIR)
        if entry.endswith(".json") and os.path.isfile(os.path.join(PLANS_DIR, entry))
    )


def list_plan_labels() -> dict[str, str]:
    """Return ``{file_stem: plan_name}`` for every ``PLANS_DIR/*.json``.

    The plan ``name`` field is used verbatim. Missing/null ``name`` falls back
    to the literal ``"plan"``. Corrupt plans are skipped silently to keep the
    UI list responsive.
    """
    if not os.path.isdir(PLANS_DIR):
        return {}

    labels: dict[str, str] = {}
    for entry in os.listdir(PLANS_DIR):
        if not entry.endswith(".json"):
            continue
        full = os.path.join(PLANS_DIR, entry)
        if not os.path.isfile(full):
            continue
        stem = os.path.splitext(entry)[0]
        try:
            with open(full, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        name = data.get("name")
        labels[stem] = name if isinstance(name, str) and name else "plan"
    return labels


def _plan_path(name: str) -> str:
    """Return the validated filesystem path for a plan file.

    Allows spaces, unicode, and any character the filesystem accepts. Only
    path traversal attempts and NUL bytes are rejected.
    """
    if not name or not isinstance(name, str):
        raise ValueError(f"Invalid plan name: {name!r} — name must be a non-empty string")
    if "/" in name:
        raise ValueError(f"Invalid plan name: {name!r} — name must not contain '/'")
    if "\\" in name:
        raise ValueError(f"Invalid plan name: {name!r} — name must not contain '\\'")
    if name in (".", ".."):
        raise ValueError(f"Invalid plan name: {name!r} — name must not be '.' or '..'")
    if "\x00" in name:
        raise ValueError(f"Invalid plan name: {name!r} — name must not contain NUL bytes")
    return os.path.join(PLANS_DIR, f"{name}.json")


def get_plan(name: str) -> dict[str, Any] | None:
    """Return the raw parsed JSON for an existing plan."""
    path = _plan_path(name)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        raise ValueError(f"Failed to read plan '{name}': {e}")


def save_plan(name: str, data: dict[str, Any]) -> str:
    """Validate and write a plan JSON file.

    The output path is ``plans/<name>.json`` — ``name`` is the file stem
    supplied by the caller (the URL on edit, the plan's ``name`` field on
    create). Changing the plan's ``name`` field does NOT move the file.

    Returns the saved path. Raises :class:`ValueError` on invalid input.
    """
    path = _plan_path(name)
    safe_name = os.path.basename(path)[:-5]

    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Plan must contain a non-empty 'steps' list")

    for i, raw_step in enumerate(steps):
        try:
            _build_step(raw_step)
        except Exception as e:
            raise ValueError(f"Invalid step at index {i}: {e}")

    recover_steps = data.get("recover_steps", [])
    if isinstance(recover_steps, list):
        for i, raw_step in enumerate(recover_steps):
            try:
                _build_step(raw_step)
            except Exception as e:
                raise ValueError(f"Invalid recover step at index {i}: {e}")

    config = data.get("config", {})
    try:
        _build_config(config)
    except Exception as e:
        raise ValueError(f"Invalid config: {e}")

    output = {
        "name": data.get("name") or safe_name,
        "steps": steps,
    }
    if recover_steps:
        output["recover_steps"] = recover_steps
    if config:
        output["config"] = config

    os.makedirs(PLANS_DIR, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
    except Exception as e:
        raise ValueError(f"Failed to write plan '{name}': {e}")

    return path


def delete_plan(name: str) -> bool:
    """Delete a plan file. Returns True if deleted, False if missing."""
    path = _plan_path(name)
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False


def build_routine_from_plan(name: str, logger: Any) -> Routine | None:
    """Load ``plans/<name>.json`` and build a :class:`Routine`."""
    try:
        data = get_plan(name)
    except Exception as e:
        if logger is not None:
            logger.error(f"Failed to load plan '{name}': {e}")
        return None

    if data is None:
        if logger is not None:
            logger.error(f"Plan '{name}' not found")
        return None

    config = _build_config(data.get("config", {}))
    steps = _build_steps(data.get("steps", []), logger)
    recover_steps = _build_steps(data.get("recover_steps", []), logger)

    return Routine(
        data.get("name") or name,
        steps,
        logger,
        config=config,
        recover_steps=recover_steps or None,
    )


def _build_config(raw: dict[str, Any]) -> RoutineConfig:
    """Construct a :class:`RoutineConfig` from a JSON config object."""
    allowed = ("delay", "max_step_retry", "timeout", "max_recover", "game_path", "tab_name")
    kwargs = {k: raw[k] for k in allowed if k in raw and raw[k] is not None}
    for key in ("game_path", "tab_name"):
        if key in kwargs and isinstance(kwargs[key], str):
            kwargs[key] = kwargs[key].strip() or None
    return RoutineConfig(**kwargs)


def _build_steps(raw_steps: list[dict[str, Any]], logger: Any) -> list[Step]:
    """Build a list of Step instances from JSON step descriptors."""
    steps: list[Step] = []
    for raw in raw_steps:
        try:
            steps.append(_build_step(raw))
        except Exception as e:
            if logger is not None:
                logger.error(f"Failed to build step: {e}")
    return steps


def _build_step(raw: dict[str, Any]) -> Step:
    """Dispatch step JSON to the correct Step subclass."""
    kind = raw.get("type", "click")
    if kind == "click":
        return _build_click_step(raw)
    if kind == "branch":
        return _build_branch_step(raw)
    raise ValueError(f"Unknown step type: {kind!r}")


def _build_click_step(raw: dict[str, Any]) -> ClickStep:
    """Build a :class:`ClickStep` from JSON."""
    targets = [Target(**_target_kwargs(target)) for target in raw.get("targets", [])]

    return ClickStep(
        targets,
        goto_step_not_found=raw.get("goto_step_not_found"),
        ready_delay=raw.get("ready_delay", 0.0),
        threshold=raw.get("threshold", 0.85),
        grayscale=raw.get("grayscale", True),
        label=raw.get("label"),
    )


def _target_kwargs(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a JSON target into keyword arguments for :class:`Target`."""
    kwargs: dict[str, Any] = {"template": raw["template"]}

    if "action" in raw:
        kwargs["action"] = ClickAction(raw["action"])

    for key in (
        "offset_x",
        "offset_y",
        "goto",
        "stay_on_confirm",
        "threshold",
        "grayscale",
        "label",
    ):
        if key in raw and raw[key] is not None:
            kwargs[key] = raw[key]

    return kwargs


def _build_branch_step(raw: dict[str, Any]) -> BranchStep:
    """Build a :class:`BranchStep` from JSON."""
    return BranchStep(
        raw["template"],
        raw["goto_found"],
        raw["goto_step_not_found"],
        threshold=raw.get("threshold", 0.85),
        grayscale=raw.get("grayscale", True),
        label=raw.get("label"),
    )
