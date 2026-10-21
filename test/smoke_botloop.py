from __future__ import annotations

"""Smoke test for ScreenBot._run capture pacing and self-anchoring -- no real screen.

The real ``ScreenBot._run`` loop is driven in-thread with a fake clock (``time``),
a fake ``mss`` capture, and simulated template matching, so we can verify the
actual loop semantics: 500ms minimum cycle measured AFTER the work, additive
``delay``/``ready_delay``, and how the plan reacts to screen changes.

Run as part of pytest, or standalone:
    "C:\\Users\\trucn\\miniconda3\\python.exe" test\\smoke_botloop.py
"""

import os
import sys
import types
from collections.abc import Callable

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine.click_step as cs_mod
import engine.plan_runner as plan_runner_mod
import core.screen_bot as sb_mod
from core.match_result import MatchResult
from core.state_manager import BotState, StateManager
from engine.click_step import ClickStep
from engine.config import PlanConfig
from engine.plan_runner import PlanRunner
from engine.target import Target


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
    """Advance the fake clock, expose the timeline's templates, and stop at the limit."""
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
    """Install fake clock/capture/matching/clicking for the loop."""
    set_attr(sb_mod, "time", FC)
    set_attr(cs_mod, "time", FC)
    set_attr(plan_runner_mod, "time", FC)
    set_attr(sb_mod, "_capture", fake_capture)
    set_attr(sb_mod, "mss", types.SimpleNamespace(mss=lambda: _FakeSct()))
    set_attr(cs_mod, "match_template", fake_match)
    set_attr(plan_runner_mod, "match_template", fake_match)
    set_attr(cs_mod, "do_click", fake_click)


@pytest.fixture(autouse=True)
def _patch_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply_patches(monkeypatch.setattr)


def run(
    name: str,
    *,
    delay: float = 0.0,
    ready: float = 0.0,
    num_steps: int = 1,
    timeline: list[set[str]] | None = None,
    limit: int = 30,
) -> dict:
    """Drive the real ScreenBot loop over a timeline and report the outcome."""
    FC.now = 0.0
    visible.clear()
    clicks.clear()

    state_mgr = StateManager()
    bot = sb_mod.ScreenBot(FakeLogger(), state_mgr, None, check_interval=0.5)
    events: list[tuple[str, str]] = []
    bot.on_plan_done = lambda n: events.append(("done", n))

    steps = [ClickStep([Target("templates/x/B.png")], ready_delay=ready)]
    if num_steps >= 2:
        steps.append(ClickStep([Target("templates/x/C.png")]))
    if num_steps >= 3:
        steps.append(ClickStep([Target("templates/x/D.png")]))
    plan = PlanRunner(
        name,
        steps,
        logger=None,
        config=PlanConfig(delay=delay),
    )
    bot.start_plan(plan)

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
        "index": plan._index,
        "done": plan.done,
        "now": FC.now,
    }


class TestScreenBotLoop:
    """Suite: end-to-end ScreenBot loop — pacing, delays, and self-anchoring reactions."""

    @pytest.mark.positive
    def test_pacing_reclicks(self):
        """A persistent target is re-clicked once per ~500ms cycle, never faster."""
        r = run("a", timeline=[{"B.png"}], limit=5)
        labels = [c[0] for c in r["clicks"]]
        times = [c[1] for c in r["clicks"]]
        assert labels == ["B.png"] * 5, f"expected 5 B clicks, got {labels}"
        gaps = [round(times[i + 1] - times[i], 2) for i in range(len(times) - 1)]
        assert all(0.49 <= g <= 0.55 for g in gaps), f"expected ~0.5s gaps, got {gaps}"
        assert r["index"] == 0

    @pytest.mark.positive
    def test_delay_additive(self):
        """delay=0.2 sits on top of the 500ms cadence (spacing ~0.72s)."""
        r = run("b", delay=0.2, timeline=[{"B.png"}], limit=5)
        times = [c[1] for c in r["clicks"]]
        gaps = [round(times[i + 1] - times[i], 2) for i in range(len(times) - 1)]
        assert all(0.70 <= g <= 0.75 for g in gaps), f"expected ~0.72s gaps, got {gaps}"

    @pytest.mark.positive
    def test_verified_advance(self):
        """Target vanished and next step visible anchors the runner forward exactly once."""
        r = run("c", num_steps=2, timeline=[{"B.png"}, {"C.png"}, {"C.png"}], limit=8)
        labels = [c[0] for c in r["clicks"]]
        assert labels.count("B.png") == 1, f"expected exactly one B click, got {labels}"
        assert labels[0] == "B.png"
        assert labels[1] == "C.png"
        assert r["index"] == 1

    @pytest.mark.positive
    def test_runner_completes(self):
        """A single terminal step finishes and fires on_plan_done."""
        r = run("f", num_steps=1, timeline=[{"B.png"}, set()], limit=8)
        assert [c[0] for c in r["clicks"]] == ["B.png"]
        assert r["done"] is True
        assert r["events"] == [("done", "f")]

    @pytest.mark.positive
    def test_ready_delay_honored(self):
        """ready_delay=1.2 delays the first action to at least 1.2s."""
        r = run("h", ready=1.2, timeline=[{"B.png"}], limit=12)
        first = r["clicks"][0][1]
        assert first >= 1.2, f"first click at {first}s is before ready_delay"
        assert first <= 2.0, f"first click at {first}s too late"

    @pytest.mark.edge
    def test_loading_waits_then_anchors(self):
        """A loading frame with nothing visible is waited out, then the next step is anchored."""
        r = run("d", num_steps=2, timeline=[{"B.png"}, set(), {"C.png"}, {"C.png"}], limit=10)
        labels = [c[0] for c in r["clicks"]]
        assert labels[0] == "B.png"
        assert labels.count("B.png") == 1
        assert "C.png" in labels
        assert r["index"] == 1

    @pytest.mark.edge
    def test_flicker_does_not_advance(self):
        """A target that vanishes for one frame then returns is not treated as a transition."""
        r = run("fl", num_steps=2, timeline=[{"B.png"}, set(), {"B.png"}, {"B.png"}], limit=8)
        labels = [c[0] for c in r["clicks"]]
        assert r["index"] == 0, f"flicker must not advance, index={r['index']}"
        assert "C.png" not in labels, f"next step must not be clicked, got {labels}"
        assert labels.count("B.png") >= 2, f"expected a re-click after flicker, got {labels}"

    @pytest.mark.edge
    def test_misclick_back_reanchors(self):
        """After SEARCH_DELAY the general hunt re-anchors back to an earlier step."""
        r = run(
            "mb",
            num_steps=3,
            timeline=[
                {"B.png"},
                {"C.png"},
                {"C.png"},
                {"C.png"},
                {"B.png"},
                {"B.png"},
                {"B.png"},
            ],
            # ~0.52s fake seconds per cycle; SEARCH_DELAY is 30s, so the hunt
            # cannot run until well past the old 10-cycle limit.
            limit=100,
        )
        labels = [c[0] for c in r["clicks"]]
        assert "B.png" in labels and "C.png" in labels
        assert r["index"] == 0, f"expected to re-anchor back to step 0, got {r['index']}"

    @pytest.mark.negative
    def test_nothing_visible_makes_no_clicks(self):
        """With nothing matched the loop waits and never clicks blindly."""
        r = run("e", num_steps=2, timeline=[set()], limit=6)
        assert r["clicks"] == []
        assert r["index"] == 0

    @pytest.mark.negative
    def test_unknown_screen_stays_lost(self):
        """An unknown screen after a click keeps scanning without finishing or aborting."""
        r = run("g", num_steps=2, timeline=[{"B.png"}, set(), set(), set()], limit=20)
        assert r["done"] is False
        assert len(r["clicks"]) >= 1
        assert r["events"] == []


def main() -> None:
    _apply_patches(setattr)
    print("=" * 78)
    print("ScreenBot loop smoke test  (fake clock, simulated capture/matching)")
    print("check_interval=0.5, capture cost=0.02 per iteration")
    print("=" * 78)
    suite = TestScreenBotLoop()
    for name in (
        "test_pacing_reclicks",
        "test_delay_additive",
        "test_verified_advance",
        "test_runner_completes",
        "test_ready_delay_honored",
        "test_loading_waits_then_anchors",
        "test_flicker_does_not_advance",
        "test_misclick_back_reanchors",
        "test_nothing_visible_makes_no_clicks",
        "test_unknown_screen_stays_lost",
    ):
        getattr(suite, name)()
        print(f"    PASS: {name}")
    print()
    print("All assertions passed.")


if __name__ == "__main__":
    main()
