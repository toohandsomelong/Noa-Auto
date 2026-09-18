from __future__ import annotations

"""Smoke test for ScreenBot._run capture pacing -- no real screen, no templates.

The real ``ScreenBot._run`` loop is driven in-thread with a fake clock (``time``),
a fake ``mss`` capture, and simulated template matching, so we can verify the
actual loop semantics: 500ms minimum cycle measured AFTER the work, additive
``delay``/``ready_delay``, and reaction to screen changes between captures.

Run from anywhere:
    "C:\\Users\\trucn\\miniconda3\\python.exe" test\\smoke_botloop.py
"""

import os
import sys
import types
from collections.abc import Callable

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routines.click_step as cs_mod
import routines.step as step_mod
import routines.routine as routine_mod
import core.screen_bot as sb_mod
from core.match_result import MatchResult
from core.state_manager import BotState, StateManager
from routines.click_step import ClickStep
from routines.config import RoutineConfig
from routines.routine import Routine
from routines.target import Target


class FakeLogger:
    def info(self, message: str, *args: object) -> None:
        pass

    def warning(self, message: str, *args: object) -> None:
        pass

    def error(self, message: str, *args: object) -> None:
        pass

    def state(self, message: str, *args: object) -> None:
        pass


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)


FC = FakeClock()

visible: set[str] = set()
clicks: list[tuple[str, float]] = []


def fake_match(screenshot: object, path: str, threshold: float = 0.85, grayscale: bool = True) -> MatchResult | None:
    if os.path.basename(path) in visible:
        return MatchResult(location=(10, 10), size=(10, 10), confidence=0.97)
    return None


def fake_click(point: tuple[int, int], *args: object, **kwargs: object) -> bool:
    clicks.append((str(kwargs.get("label")), round(FC.now, 3)))
    return True


class _FakeSct:
    def __init__(self) -> None:
        self.monitors = [{"left": 0, "top": 0, "width": 1920, "height": 1080}]

    def close(self) -> None:
        pass


CTRL = {
    "bot": None,
    "limit": 500,
    "timeline": None,
    "step_idx": 0,
    "count": 0,
}


def fake_capture(sct: object | None = None, region: object | None = None) -> object:
    FC.now += 0.02
    visible.clear()
    if CTRL["timeline"] is not None:
        idx = min(CTRL["step_idx"], len(CTRL["timeline"]) - 1)
        visible.update(CTRL["timeline"][idx])
    CTRL["step_idx"] += 1
    CTRL["count"] += 1
    if CTRL["count"] >= CTRL["limit"] and CTRL["bot"] is not None:
        CTRL["bot"]._stop_event.set()
    return "screen"


def _apply_patches(set_attr: Callable[..., None]) -> None:
    set_attr(sb_mod, "time", FC)
    set_attr(cs_mod, "time", FC)
    set_attr(step_mod, "time", FC)
    set_attr(routine_mod, "time", FC)
    set_attr(sb_mod, "_capture", fake_capture)
    set_attr(sb_mod, "mss", types.SimpleNamespace(mss=lambda: _FakeSct()))
    set_attr(cs_mod, "match_template", fake_match)
    set_attr(routine_mod, "match_template", fake_match)
    set_attr(cs_mod, "do_click", fake_click)


@pytest.fixture(autouse=True)
def _patch_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply_patches(monkeypatch.setattr)


def run(
    name: str,
    *,
    delay: float = 0.0,
    ready: float = 0.0,
    max_step_retry: int = 1000,
    num_steps: int = 1,
    timeline: list[set[str]] | None = None,
    limit: int = 30,
) -> dict:
    FC.now = 0.0
    visible.clear()
    clicks.clear()

    state_mgr = StateManager()
    bot = sb_mod.ScreenBot(FakeLogger(), state_mgr, None, check_interval=0.5)
    events: list[tuple[str, str]] = []
    bot.on_routine_done = lambda n: events.append(("done", n))
    bot.on_routine_abort = lambda n: events.append(("abort", n))

    steps = [ClickStep([Target("templates/x/B.png")], ready_delay=ready)]
    if num_steps >= 2:
        steps.append(ClickStep([Target("templates/x/C.png")]))
    routine = Routine(
        name,
        steps,
        logger=None,
        config=RoutineConfig(
            delay=delay,
            max_step_retry=max_step_retry,
            timeout=None,
        ),
    )
    bot.start_routine(routine)

    CTRL["bot"] = bot
    CTRL["limit"] = limit
    CTRL["timeline"] = timeline
    CTRL["step_idx"] = 0
    CTRL["count"] = 0
    state_mgr.state = BotState.RUNNING

    bot._run()

    return {
        "clicks": list(clicks),
        "events": events,
        "index": routine._index,
        "done": routine.done,
        "aborted": routine.aborted,
        "now": FC.now,
    }


def scenario_persist_reclicks() -> None:
    print("A: target stays on screen -> re-clicks once per ~500ms (no faster)")
    r = run("a", timeline=[{"B.png"}], limit=5)
    labels = [c[0] for c in r["clicks"]]
    times = [c[1] for c in r["clicks"]]
    assert labels == ["B.png"] * 5, f"expected 5 B clicks, got {labels}"
    gaps = [round(times[i + 1] - times[i], 2) for i in range(len(times) - 1)]
    assert all(0.49 <= g <= 0.55 for g in gaps), f"expected ~0.5s gaps, got {gaps}"
    assert r["index"] == 0, f"expected to stay on step 0, got {r['index']}"
    print(f"    PASS: clicks every {gaps} (capture pace = 500ms)")


def scenario_delay_additive() -> None:
    print("B: delay=0.2 ADDS on top of 500ms (spacing ~0.72s)")
    r = run("b", delay=0.2, timeline=[{"B.png"}], limit=5)
    times = [c[1] for c in r["clicks"]]
    gaps = [round(times[i + 1] - times[i], 2) for i in range(len(times) - 1)]
    assert all(0.70 <= g <= 0.75 for g in gaps), f"expected ~0.72s gaps, got {gaps}"
    print(f"    PASS: gaps {gaps} = 0.2 delay + ~0.02 capture + 0.5 interval")


def scenario_vanish_verified_advance() -> None:
    print("C: target vanished, next step visible -> verified advance, no stale click")
    r = run("c", num_steps=2, timeline=[{"B.png"}, {"C.png"}, {"C.png"}], limit=6)
    labels = [c[0] for c in r["clicks"]]
    assert labels.count("B.png") == 1, f"expected exactly one B click, got {labels}"
    assert labels[0] == "B.png", f"expected B first, got {labels}"
    assert labels[1] == "C.png", f"expected C after advance, got {labels}"
    assert r["index"] == 1, f"expected index 1, got {r['index']}"
    print("    PASS: B clicked once, advanced to C (C re-clicked while visible)")


def scenario_vanish_loading_advance() -> None:
    print("D: target vanished + next NOT visible (loading) -> advance anyway, no click")
    r = run("d", num_steps=2, timeline=[{"B.png"}, set(), set()], limit=6)
    assert [c[0] for c in r["clicks"]] == ["B.png"], f"got {[c[0] for c in r['clicks']]}"
    assert r["index"] == 1, f"expected index 1 (loading advance), got {r['index']}"
    print("    PASS: no second click during transition; advanced on 'both gone'")


def scenario_nothing_visible() -> None:
    print("E: nothing visible -> zero clicks, is wait-and-watch")
    r = run("e", num_steps=2, timeline=[set()], limit=6)
    assert r["clicks"] == [], f"expected no clicks, got {r['clicks']}"
    assert r["index"] == 0, f"expected to stay at step 0, got {r['index']}"
    print("    PASS: no blind click when nothing matched")


def scenario_routine_completes() -> None:
    print("F: single step finished -> on_routine_done fired, routine ends")
    r = run("f", num_steps=1, timeline=[{"B.png"}, set(), set()], limit=8)
    assert [c[0] for c in r["clicks"]] == ["B.png"], f"got {[c[0] for c in r['clicks']]}"
    assert r["done"] is True, "expected done=True"
    assert r["aborted"] is False, "expected aborted=False"
    assert r["events"] == [("done", "f")], f"expected on_routine_done, got {r['events']}"
    print("    PASS: normal completion dispatched on_routine_done")


def scenario_never_abort_resync() -> None:
    print("G: target never transitions -> RECOVER -> resync loops without aborting")
    r = run("g", max_step_retry=3, timeline=[{"B.png"}], limit=20)
    assert r["aborted"] is False, "expected never-abort"
    assert r["done"] is False, "expected routine to keep running"
    assert len(r["clicks"]) >= 3, f"expected continued retries, got {len(r['clicks'])}"
    assert r["events"] == [], f"expected no done/abort event, got {r['events']}"
    print("    PASS: routine kept re-clicking/polling instead of aborting")


def scenario_ready_delay_honored() -> None:
    print("H: ready_delay=1.2 -> first action waited at least 1.2s")
    r = run("h", ready=1.2, timeline=[{"B.png"}], limit=12)
    first = r["clicks"][0][1]
    assert first >= 1.2, f"first click at {first}s is before ready_delay"
    assert first <= 2.0, f"first click at {first}s too late"
    print(f"    PASS: first click at {first}s (ready_delay honored, snapped to 500ms grid)")


def main() -> None:
    _apply_patches(setattr)
    print("=" * 78)
    print("ScreenBot loop smoke test  (fake clock, simulated capture/matching)")
    print("check_interval=0.5, capture cost=0.02 per iteration")
    print("=" * 78)
    scenario_persist_reclicks()
    print()
    scenario_delay_additive()
    print()
    scenario_vanish_verified_advance()
    print()
    scenario_vanish_loading_advance()
    print()
    scenario_nothing_visible()
    print()
    scenario_routine_completes()
    print()
    scenario_never_abort_resync()
    print()
    scenario_ready_delay_honored()
    print()
    print("All assertions passed.")


if __name__ == "__main__":
    main()