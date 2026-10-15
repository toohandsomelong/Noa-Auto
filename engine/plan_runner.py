from __future__ import annotations

import time
from typing import Any

from engine.base import WAIT, DONE, match_template
from engine.config import PlanConfig
from engine.step import Step


ANCHOR_DEBOUNCE_FRAMES = 2


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
        self._anchor_candidate: int | None = None
        self._anchor_hits = 0
        self._match_cache: dict[tuple[str, float, bool], Any] | None = None

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

    def _steps_visible(self, idx: int, screenshot: Any) -> bool:
        if not (0 <= idx < len(self.steps)):
            return True
        return self._step_visible(self.steps[idx], screenshot)

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
                self._anchor_tick(screenshot)
            return
        if result == DONE:
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

    def _anchor_candidates(self) -> list[int]:
        """Return candidate step indices to scan while the current step is lost.

        Priority order mirrors the old resync heuristic: a clicked target's explicit
        ``goto`` successor first, then ``goto_step_if_not_found``, then the natural
        next step, then forward plan order, then earlier steps. The current step is
        excluded because it already reported itself lost.
        """
        n = len(self.steps)
        if n == 0:
            return []
        origin = min(max(self._index, 0), n - 1)
        order: list[int] = []
        seen: set[int] = set()

        def add(idx: int) -> None:
            if 0 <= idx < n and idx not in seen:
                seen.add(idx)
                order.append(idx)

        step = self.steps[origin]
        for rule in getattr(step, "_rules", []):
            goto = getattr(rule, "goto", None)
            if goto is not None:
                add(goto)
        fallback = getattr(step, "_goto_step_if_not_found", None)
        if fallback is not None:
            add(fallback)
        add(origin + 1)
        for idx in range(origin + 1, n):
            add(idx)
        for idx in range(0, origin):
            add(idx)
        return order

    def _anchor_tick(self, screenshot: Any) -> None:
        current_templates = self._current_step_templates()
        best: int | None = None
        for idx in self._anchor_candidates():
            candidate_templates = self._templates_for_step(self.steps[idx])
            if candidate_templates & current_templates:
                continue
            if self._steps_visible(idx, screenshot):
                best = idx
                break

        if best is None:
            self._anchor_candidate = None
            self._anchor_hits = 0
            if self.logger is not None:
                self.logger.info(
                    f'[plan "{self.name}"] anchor: no known step visible yet, staying lost'
                )
            return

        if best == self._anchor_candidate:
            self._anchor_hits += 1
        else:
            self._anchor_candidate = best
            self._anchor_hits = 1

        if self._anchor_hits < ANCHOR_DEBOUNCE_FRAMES:
            if self.logger is not None:
                self.logger.info(
                    f'[plan "{self.name}"] anchor: candidate step {best} seen '
                    f"{self._anchor_hits}/{ANCHOR_DEBOUNCE_FRAMES}, confirming"
                )
            return

        origin = self._index
        self._anchor_candidate = None
        self._anchor_hits = 0
        if self.logger is not None:
            self.logger.state(
                f"Plan '{self.name}' re-anchored to step {best} (was at step {origin})"
            )
        self._advance_to(best, force_reset=True)
