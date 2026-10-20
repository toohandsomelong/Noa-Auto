from __future__ import annotations

import time
from typing import Any

import cv2
import numpy as np

from engine.base import WAIT, DONE, match_template
from engine.config import PlanConfig
from engine.step import Step


# --- screen-stability gate -------------------------------------------------
# Used only by the general hunt (after SEARCH_DELAY): the runner scans every
# step only once the screen has stopped changing, so loading fades, scroll-ins
# and one-frame flicker can't produce a wrong anchor. The expected next step is
# NOT gated by this — it is a known destination and is matched directly. Each
# tick the screenshot is reduced to a tiny grayscale signature and compared to
# the previous one.
STABLE_FRAME_SIZE = (80, 45)  # downscaled signature size (w, h)
STABLE_THRESHOLD = 0.02  # tolerated mean abs difference (0..1); tolerant on purpose
STABLE_FRAMES = 2  # consecutive settled comparisons required to be "stable"


# --- search delay ----------------------------------------------------------
# When the current step is lost the runner first gives the game time to show
# the expected next step. Only once the step has been lost for this long does
# it run the general nearest-step scan. Keeps normal transitions instant (the
# expected next step still advances immediately) while avoiding a premature
# hunt when the next screen is simply still loading.
SEARCH_DELAY = 30.0  # seconds to wait for the expected next step before scanning


# --- anchor selection weights ----------------------------------------------
# When several steps match on a stable screen the runner scores each candidate
# and picks the cheapest. Weights are internal constants (no plan keys); tune
# them here. Lower score wins.
W_DIST = 1.0  # cost of one step of distance from the current step
FORWARD_BONUS = -0.5  # subtracted for candidates ahead of the current step (progress)
BACKWARD_PENALTY = 1.0  # added for candidates behind the current step (avoids spurious rewinds)
W_CONF = 0.0  # (suggested: 1.0) weight of the strongest match confidence
W_EV = 0.0  # (suggested: 0.25) weight of the number of matching targets


def anchor_score(
    origin: int,
    index: int,
    *,
    confidence: float = 0.0,
    matched_targets: int = 0,
) -> float:
    """Cost of anchoring to ``index`` while the current step is ``origin``.

    Lower is better. Combines distance, a forward preference / backward penalty,
    and (currently disabled, see ``W_CONF`` / ``W_EV``) match strength.
    """
    distance = abs(index - origin)
    if index > origin:
        direction = FORWARD_BONUS
    elif index < origin:
        direction = BACKWARD_PENALTY
    else:
        direction = 0.0
    return (
        W_DIST * distance
        + direction
        - W_CONF * confidence
        - W_EV * matched_targets
    )


class PlanRunner:
    def __init__(
        self,
        name: str,
        steps: list[Step],
        logger: Any,
        config: PlanConfig,
        interrupt_steps: list[Step] | None = None,
        *,
        plan_key: str | None = None,
    ) -> None:
        self.name = name
        self.plan_key = plan_key
        self.steps = steps
        self.logger = logger
        self.config = config
        self.done = False

        for i, step in enumerate(steps):
            step.index = i
            step.logger = logger
            step.delay = config.delay

        self._interrupt_steps = interrupt_steps or []
        for i, step in enumerate(self._interrupt_steps):
            step.index = i
            step.logger = logger
            step.delay = config.delay

        self._index = 0
        self._mark_terminal_targets()
        self._reset_on_enter(0)

        self._interrupt_was_active = False
        self._match_cache: dict[tuple[str, float, bool], Any] | None = None
        self._prev_frame: Any | None = None
        self._stable_frames = 0
        self._pending_pick: int | None = None
        self._lost_since: float | None = None

    def _mark_terminal_targets(self) -> None:
        n = len(self.steps)
        for i, step in enumerate(self.steps):
            for rule in getattr(step, "_rules", []):
                next_idx = rule.goto if rule.goto is not None else i + 1
                if next_idx >= n:
                    rule.terminal = True

    def _reset_on_enter(self, idx: int) -> None:
        if 0 <= idx < len(self.steps):
            step = self.steps[idx]
            step.reset()
            if self.logger is not None:
                self.logger.info(
                    f'[plan "{self.name}"] entering step {idx} ({step.label or "step"}) '
                    f"targets: {self._targets_desc(step)}"
                )

    def _targets_desc(self, step: Step) -> str:
        names = [getattr(t, "label", None) or t.template for t in getattr(step, "_rules", [])]
        return ", ".join(names) or "none"

    def _cached_match(self, screenshot: Any, path: str, threshold: float, grayscale: bool) -> Any:
        key = (path, threshold, grayscale)
        cache = self._match_cache
        if cache is None:
            cache = {}
            self._match_cache = cache
        if key not in cache:
            cache[key] = match_template(screenshot, path, threshold=threshold, grayscale=grayscale)
        return cache[key]

    def _frame_signature(self, screenshot: Any) -> Any:
        gray = screenshot
        if len(gray.shape) == 3:
            gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, STABLE_FRAME_SIZE, interpolation=cv2.INTER_AREA)

    def _update_stability(self, screenshot: Any) -> None:
        """Update the settled-screen counter from the latest frame.

        Non-array screenshots (tests pass opaque placeholders) are treated as
        already settled so the gate stays out of the way.
        """
        if not isinstance(screenshot, np.ndarray):
            self._prev_frame = None
            self._stable_frames = STABLE_FRAMES
            return

        signature = self._frame_signature(screenshot)
        prev = self._prev_frame
        if prev is None or prev.shape != signature.shape:
            self._stable_frames = 0
        else:
            diff = float(
                np.mean(np.abs(signature.astype(np.int16) - prev.astype(np.int16)))
            ) / 255.0
            if diff <= STABLE_THRESHOLD:
                self._stable_frames += 1
            else:
                self._stable_frames = 0
        self._prev_frame = signature

    def _screen_stable(self) -> bool:
        return self._stable_frames >= STABLE_FRAMES

    def _step_visible(self, step: Step, screenshot: Any) -> bool:
        for target in getattr(step, "_rules", []):
            thresh = target.threshold if target.threshold is not None else step.threshold
            gs = target.grayscale if target.grayscale is not None else step.grayscale
            if all(
                self._cached_match(screenshot, path, threshold=thresh, grayscale=gs) is not None
                for path in getattr(target, "templates", [getattr(target, "template", "")])
            ):
                return True
        return False

    def _templates_for_target(self, target: Any) -> list[str]:
        return getattr(target, "templates", None) or [getattr(target, "template", "")]

    def _templates_for_step(self, step: Step) -> set[str]:
        paths: set[str] = set()
        for t in getattr(step, "_rules", []):
            paths.update(self._templates_for_target(t))
        return paths

    def _current_step_templates(self) -> set[str]:
        step = self.current_step()
        if step is None:
            return set()
        return self._templates_for_step(step)

    def _tick_interrupts(self, screenshot: Any) -> bool:
        """Tick the first visible interrupt (blocker) and short-circuit the plan.

        Interrupts are checked every cycle, regardless of the current step, and never
        advance the plan. Returns True while any blocker is on screen.
        """
        current_templates = self._current_step_templates()
        for step in self._interrupt_steps:
            step_templates = self._templates_for_step(step)
            if step_templates & current_templates:
                continue
            if self._step_visible(step, screenshot):
                self._interrupt_was_active = True
                step.tick(screenshot)
                return True

        if self._interrupt_was_active:
            for step in self._interrupt_steps:
                step.reset_click_state()
            self._interrupt_was_active = False
        return False

    def current_step(self) -> Step | None:
        if self.done:
            return None
        if 0 <= self._index < len(self.steps):
            return self.steps[self._index]
        return None

    def tick(self, screenshot: Any) -> None:
        self._match_cache = {}
        self._update_stability(screenshot)

        if self.done:
            return
        if self._tick_interrupts(screenshot):
            return
        if self._index < 0 or self._index >= len(self.steps):
            self.done = True
            return

        cur = self.steps[self._index]
        result = cur.tick(screenshot)
        log = self.logger

        if result == WAIT:
            if cur.lost:
                if self._lost_since is None:
                    self._lost_since = time.monotonic()
                self._anchor_tick(screenshot)
            else:
                self._lost_since = None
            return
        if result == DONE:
            # A missing target on a still-changing screen is not proof the click
            # landed (flicker/animation). Only finish once the screen is settled.
            if not self._screen_stable():
                if log:
                    log.info(
                        f'[plan "{self.name}"] step {self._index} reported DONE but '
                        f"screen not settled - deferring plan completion"
                    )
                return
            if log:
                log.info(f'[plan "{self.name}"] step {self._index} returned DONE - plan finished')
            self.done = True
            return

        if log:
            log.info(f'[plan "{self.name}"] step {self._index} returned result {result}, advancing')

        if result != self._index:
            self._advance_to(result)

    def _advance_to(self, new_idx: int, *, force_reset: bool = False) -> None:
        if self.logger is not None:
            self.logger.info(f'[plan "{self.name}"] advancing step {self._index} -> {new_idx}')
        if new_idx != self._index or force_reset:
            self._reset_on_enter(new_idx)
        self._index = new_idx
        # Entering a step means the screen is expected to change (normal advance,
        # explicit goto, or goto_step_if_not_found). Drop the stability history so
        # the previous screen's "settled" state never leaks into the new screen.
        self._prev_frame = None
        self._stable_frames = 0
        self._pending_pick = None
        self._lost_since = None

    def _expected_candidates(
        self, origin: int, *, clicked_target: Any | None = None
    ) -> set[int]:
        """Explicit destination the runner intends to reach from ``origin``.

        While confirming this is the clicked target's ``goto`` when it has one,
        otherwise the natural next step (``origin + 1``). It is a top-preference
        tier so an intended jump (e.g. ``goto: 14``) beats a nearer incidental
        match; it carries no uniqueness requirement.
        """
        n = len(self.steps)
        target: int | None = None
        if clicked_target is not None:
            target = getattr(clicked_target, "goto", None)
        if target is None:
            target = origin + 1
        return {target} if 0 <= target < n else set()

    def _expected_visible(self, expected: set[int], screenshot: Any) -> bool:
        """True if any of the expected candidate steps currently matches."""
        for idx in sorted(expected):
            if self._step_match_strength(self.steps[idx], screenshot)[1] > 0:
                return True
        return False

    def _expected_fallback(self, expected: set[int]) -> int | None:
        """Return an expected step's goto_step_if_not_found, if it has one."""
        for idx in sorted(expected):
            step = self.steps[idx]
            fallback = getattr(step, "_goto_step_if_not_found", None)
            if fallback is not None and 0 <= fallback < len(self.steps):
                return fallback
        return None

    def _is_terminal_step(self, idx: int) -> bool:
        """True when every target of the step finishes the plan.

        Terminal steps are reached by their own advance/``goto``; excluding them
        from seeking stops a global button (e.g. a Home icon that happens to live
        only on the last step) from ending the plan whenever the runner is lost.
        """
        rules = getattr(self.steps[idx], "_rules", [])
        return bool(rules) and all(getattr(r, "terminal", False) for r in rules)

    def _step_match_strength(self, step: Step, screenshot: Any) -> tuple[float, int]:
        """Return ``(best_confidence, matched_target_count)`` for a step.

        A target counts as matched only when all of its templates are visible
        (AND-match). Confidence is the weakest template of the strongest target.
        """
        best_conf = 0.0
        count = 0
        for target in getattr(step, "_rules", []):
            thresh = target.threshold if target.threshold is not None else step.threshold
            gs = target.grayscale if target.grayscale is not None else step.grayscale
            confs: list[float] = []
            for path in self._templates_for_target(target):
                mi = self._cached_match(screenshot, path, threshold=thresh, grayscale=gs)
                if mi is None:
                    confs = []
                    break
                confs.append(float(mi.confidence))
            if confs:
                count += 1
                best_conf = max(best_conf, min(confs))
        return best_conf, count

    def _matching_steps(self, screenshot: Any) -> dict[int, tuple[float, int]]:
        matches: dict[int, tuple[float, int]] = {}
        for i, step in enumerate(self.steps):
            strength = self._step_match_strength(step, screenshot)
            if strength[1] > 0:
                matches[i] = strength
        return matches

    def _best_by_score(self, origin: int, matches: dict[int, tuple[float, int]]) -> int | None:
        best_idx: int | None = None
        best_score: float | None = None
        for idx in sorted(matches):
            conf, count = matches[idx]
            score = anchor_score(origin, idx, confidence=conf, matched_targets=count)
            better = (
                best_score is None
                or score < best_score
                or (score == best_score and (best_idx is None or idx > best_idx))
            )
            if better:
                best_score = score
                best_idx = idx
        return best_idx

    def _select_anchor(self, screenshot: Any, *, searching: bool) -> int | None:
        """Pick the step to re-anchor to, or ``None``.

        Always prefers the explicit expected destination (clicked target's
        ``goto`` or ``origin + 1``) when it is visible. The general nearest-step
        scan only runs once ``searching`` is True, i.e. after :data:`SEARCH_DELAY`
        has elapsed without the expected next step showing up.
        """
        origin = self._index
        cur = self.current_step()
        clicked_target = getattr(cur, "_clicked_target", None) if cur is not None else None
        expected = self._expected_candidates(origin, clicked_target=clicked_target)
        for idx in sorted(expected):
            if self._step_match_strength(self.steps[idx], screenshot)[1] > 0:
                return idx

        if not searching:
            return None

        matches = self._matching_steps(screenshot)
        matches.pop(origin, None)
        candidates = {i: v for i, v in matches.items() if not self._is_terminal_step(i)}
        if not candidates:
            return None
        return self._best_by_score(origin, candidates)

    def _anchor_tick(self, screenshot: Any) -> None:
        lost_since = self._lost_since
        lost_for = 0.0 if lost_since is None else time.monotonic() - lost_since
        searching = lost_for >= SEARCH_DELAY

        origin = self._index
        cur = self.current_step()
        clicked_target = getattr(cur, "_clicked_target", None) if cur is not None else None
        expected = self._expected_candidates(origin, clicked_target=clicked_target)

        # After a click, if the expected next step is not visible, honor that
        # step's goto_step_if_not_found immediately instead of waiting.
        if clicked_target is not None and expected and not self._expected_visible(expected, screenshot):
            fallback = self._expected_fallback(expected)
            if fallback is not None:
                if self.logger is not None:
                    self.logger.info(
                        f'[plan "{self.name}"] anchor: expected step {sorted(expected)[0]} not found, '
                        f"using goto_step_if_not_found {fallback}"
                    )
                self._advance_to(fallback, force_reset=True)
                return

        # Only the general hunt waits for the screen to settle. The expected next
        # step is a known destination, matched directly on the current frame, so
        # normal transitions don't pay the settle cost.
        if searching and not self._screen_stable():
            return

        pick = self._select_anchor(screenshot, searching=searching)
        if pick is None:
            self._pending_pick = None
            if self.logger is not None:
                if searching:
                    self.logger.info(
                        f'[plan "{self.name}"] anchor: no matching step on the settled '
                        f"screen, staying lost"
                    )
                else:
                    remaining = max(SEARCH_DELAY - lost_for, 0.0)
                    self.logger.info(
                        f'[plan "{self.name}"] anchor: waiting for the next step '
                        f"({remaining:.1f}s before scanning)"
                    )
            return

        # Two-frame debounce: the same pick must be chosen again on the next tick
        # before committing. Unsettled frames don't discard it (see above).
        if self._pending_pick != pick:
            self._pending_pick = pick
            if self.logger is not None:
                self.logger.info(
                    f'[plan "{self.name}"] anchor: candidate step {pick} matched, verifying'
                )
            return

        origin = self._index
        self._pending_pick = None
        if self.logger is not None:
            self.logger.state(
                f"Plan '{self.name}' re-anchored to step {pick} (was at step {origin})"
            )
        self._advance_to(pick, force_reset=True)
