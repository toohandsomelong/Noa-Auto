from __future__ import annotations

import math
import os
import random
import time
from typing import Any, Callable

import pyautogui

from screen_bot import MatchResult, _load_template, _match


WAIT = -1
DONE = -2
RECOVER = -3


# def _human_move_to(target: tuple[int, int], duration: float = 0.2) -> None:
#     try:
#         sx, sy = pyautogui.position()
#         ex, ey = target
#         dx, dy = ex - sx, ey - sy
#         dist = math.hypot(dx, dy)
#         if dist < 10:
#             pyautogui.moveTo(ex, ey, duration=duration * 0.3)
#             return
#         ratio = random.uniform(0.1, 0.3)
#         cx = (sx + ex) / 2 + (-dy / max(dist, 1)) * ratio * dist * 0.15
#         cy = (sy + ey) / 2 + (dx / max(dist, 1)) * ratio * dist * 0.15
#         n = 8
#         for i in range(1, n + 1):
#             t = i / n
#             tweened = pyautogui.easeInOutQuad(t)
#             x = (1 - tweened) ** 2 * sx + 2 * (1 - tweened) * tweened * cx + tweened ** 2 * ex
#             y = (1 - tweened) ** 2 * sy + 2 * (1 - tweened) * tweened * cy + tweened ** 2 * ey
#             pyautogui.moveTo(x, y, duration=duration / n)
#     except Exception:
#         pass


# def _human_click(point: tuple[int, int]) -> None:
#     _human_move_to(point)
#     pyautogui.click()


# def _human_right_click(point: tuple[int, int]) -> None:
#     _human_move_to(point)
#     pyautogui.rightClick()


def match_template(
    screenshot: Any,
    path: str,
    *,
    threshold: float = 0.85,
    grayscale: bool = True,
) -> MatchResult | None:
    template = _load_template(path, grayscale)
    if template is None:
        return None
    return _match(screenshot, template, threshold, grayscale)


def do_click(
    point: tuple[int, int],
    *,
    right: bool = False,
    label: str | None = None,
    logger: Any = None,
) -> bool:
    try:
        if right:
            pyautogui.rightClick(point[0], point[1])
        else:
            pyautogui.click(point[0], point[1])
    except Exception as e:
        if logger is not None:
            logger.error(f"Click failed for {label or 'step'}: {e}")
        return False
    return True


class Step:
    index: int = 0
    logger: Any = None
    pre_click_delay: float = 0.1
    max_click_retries: int = 5
    stuck_timeout: float = 15.0
    threshold: float = 0.85
    grayscale: bool = True
    label: str | None = None

    clicked: bool = False
    click_count: int = 0
    seek_start_time: float = 0.0

    def tick(self, screenshot: Any) -> int:
        return WAIT

    def reset(self) -> None:
        self.reset_click_state()

    def reset_click_state(self) -> None:
        self.clicked = False
        self.click_count = 0
        self.seek_start_time = 0.0

    def match(self, screenshot: Any, path: str) -> MatchResult | None:
        return match_template(
            screenshot, path, threshold=self.threshold, grayscale=self.grayscale
        )

    def click(self, point: tuple[int, int], *, right: bool = False) -> bool:
        return do_click(point, right=right, label=self.label, logger=self.logger)

    def stuck_or_wait(self, label: str | None = None) -> int:
        lbl = label or self.label
        if self.seek_start_time == 0.0:
            self.seek_start_time = time.time()
        elif time.time() - self.seek_start_time > self.stuck_timeout:
            if self.logger is not None:
                self.logger.warning(f"Step {lbl} not found for {self.stuck_timeout}s")
            return RECOVER
        return WAIT


class AdvanceStep(Step):
    """No-op step that immediately succeeds. Used as an ``if_found`` action when
    the parent should advance without performing any click."""

    def __init__(self, label: str | None = None) -> None:
        self.label = label

    def tick(self, screenshot: Any) -> int:
        if self.logger is not None:
            self.logger.info(f"{self.label or 'advance'}: satisfied immediately")
        return DONE

    def reset(self) -> None:
        pass


class ClickStep(Step):
    """Match a primary template, act on it, confirm via its disappearance, then advance.

    Composable mechanisms (each accepts a Step, so behavior lives in the sub-step):

      * ``if_found`` — a priority Step that preempts the main click. Each tick the
        parent runs the sub-step first; when it returns ``DONE`` the parent fires
        ``on_if_found`` and jumps to ``goto_step_if_found`` (or ``index + 1``).
      * ``blockers`` — Steps to dismiss before attempting the primary click. Each
        tick, every blocker is run; a blocker returning ``WAIT`` pauses the parent,
        ``RECOVER`` aborts, and any other result (blocker cleared) lets the parent
        fall through to the primary click this cycle.
      * ``alt_chain`` — a fallback Step sequence used only while the primary has
        never matched. Items run in order; when the final item clears, the chain
        resets and the parent waits for the primary next cycle.
      * ``goto_step_not_found`` — if set, never-clicked-and-no-match branches immediately
        instead of waiting out ``stuck_timeout``.
      * ``offset_below`` / ``offset_x`` / ``right_click`` — main click geometry.
      * ``on_click`` / ``on_if_found`` — side-effect callbacks.
      * ``ready_delay`` — grace period after (re)entry before any action.
    """

    def __init__(
        self,
        template: str,
        *,
        offset_x: int = 0,
        offset_below: int = 0,
        right_click: bool = False,
        on_click: Callable[[], None] | None = None,
        goto_step_not_found: int | None = None,
        if_found: Step | None = None,
        on_if_found: Callable[[], None] | None = None,
        goto_step_if_found: int | None = None,
        blockers: list[Step] | None = None,
        alt_chain: list[Step] | None = None,
        ready_delay: float = 0.0,
        threshold: float = 0.85,
        grayscale: bool = True,
        label: str | None = None,
    ) -> None:
        self.template = template
        self.offset_x = offset_x
        self.offset_below = offset_below
        self.right_click = right_click
        self.on_click = on_click
        self.goto_step_not_found = goto_step_not_found
        self.if_found = if_found
        self.on_if_found = on_if_found
        self.goto_step_if_found = goto_step_if_found
        self.blockers = list(blockers) if blockers else []
        self.alt_chain = list(alt_chain) if alt_chain else []
        self.ready_delay = ready_delay
        self.threshold = threshold
        self.grayscale = grayscale
        self.label = label or os.path.basename(template)

        self.clicked = False
        self.click_count = 0
        self.seek_start_time = 0.0

        self.alt_idx = 0
        self._ready_until = 0.0

    def reset(self) -> None:
        self.reset_click_state()
        if self.if_found is not None:
            self.if_found.reset()
        for b in self.blockers:
            b.reset()
        for a in self.alt_chain:
            a.reset()
        self.alt_idx = 0
        self._ready_until = time.time() + self.ready_delay

    def tick(self, screenshot: Any) -> int:
        if time.time() < self._ready_until:
            return WAIT

        if self.if_found is not None:
            r = self.if_found.tick(screenshot)
            if r == WAIT:
                return WAIT
            if r == RECOVER:
                return RECOVER
            # DONE or any int: if_found satisfied.
            self._fire_on_if_found()
            return self.goto_step_if_found if self.goto_step_if_found is not None else self.index + 1

        if self.blockers:
            for b in self.blockers:
                r = b.tick(screenshot)
                if r == WAIT:
                    return WAIT
                if r == RECOVER:
                    return RECOVER
                # any other result: blocker cleared this cycle, fall through.

        m = self.match(screenshot, self.template)
        if m is not None:
            self.alt_idx = 0
            for a in self.alt_chain:
                a.reset()
            if self.click_count < self.max_click_retries:
                time.sleep(self.pre_click_delay)
                target = self._target_point(m)
                self.click(target, right=self.right_click)
                self.click_count += 1
                self.clicked = True
                self.seek_start_time = 0.0
                if self.logger is not None:
                    btn = "Right-clicked" if self.right_click else "Clicked"
                    where = f" below {self.label}" if self.offset_below else ""
                    self.logger.info(f"{btn}{where} {self.label} ({self.click_count}) at {target}")
                if self.on_click is not None:
                    try:
                        self.on_click()
                    except Exception as e:
                        if self.logger is not None:
                            self.logger.error(f"on_click failed for {self.label}: {e}")
                return WAIT
            if self.logger is not None:
                self.logger.warning(
                    f"Step {self.label} retried {self.click_count}x without transition"
                )
            return RECOVER

        if not self.clicked and self.alt_chain:
            r = self._tick_alt_chain(screenshot)
            if r is not None:
                return r

        if self.clicked:
            return self.index + 1

        if self.goto_step_not_found is not None:
            return self.goto_step_not_found

        return self.stuck_or_wait()

    def _target_point(self, m: MatchResult) -> tuple[int, int]:
        x = m.location[0] + m.size[0] // 2 + self.offset_x
        if self.offset_below:
            y = m.location[1] + m.size[1] + self.offset_below
        else:
            y = m.location[1] + m.size[1] // 2
        return (x, y)

    def _fire_on_if_found(self) -> None:
        if self.on_if_found is not None:
            try:
                self.on_if_found()
            except Exception as e:
                if self.logger is not None:
                    self.logger.error(f"on_if_found failed for {self.label}: {e}")

    def _tick_alt_chain(self, screenshot: Any) -> int | None:
        if self.alt_idx >= len(self.alt_chain):
            return None
        cur = self.alt_chain[self.alt_idx]
        r = cur.tick(screenshot)
        if r == WAIT:
            return WAIT
        if r == RECOVER:
            return RECOVER
        # DONE or int: this chain item cleared; advance chain.
        self.alt_idx += 1
        if self.alt_idx >= len(self.alt_chain):
            self.alt_idx = 0
            for a in self.alt_chain:
                a.reset()
            if self.logger is not None:
                self.logger.info("Alt chain complete")
        else:
            cur.reset()
        return WAIT


class BranchStep(Step):
    """Pure conditional jump on template presence. No click, no state."""

    def __init__(
        self,
        template_path: str,
        goto_found: int,
        goto_step_not_found: int,
        threshold: float = 0.85,
        grayscale: bool = True,
        label: str | None = None,
    ) -> None:
        self.template_path = template_path
        self.goto_found = goto_found
        self.goto_step_not_found = goto_step_not_found
        self.threshold = threshold
        self.grayscale = grayscale
        self.label = label or os.path.basename(template_path)

    def tick(self, screenshot: Any) -> int:
        m = self.match(screenshot, self.template_path)
        if m is not None:
            if self.logger is not None:
                self.logger.info(f"{self.label} found; branching to {self.goto_found}")
            return self.goto_found
        return self.goto_step_not_found


class EndStep(Step):
    """Terminal step. Fires ``on_done`` and returns DONE."""

    def __init__(self, on_done: Callable[[], None] | None = None) -> None:
        self.on_done = on_done

    def tick(self, screenshot: Any) -> int:
        if self.on_done is not None:
            try:
                self.on_done()
            except Exception as e:
                if self.logger is not None:
                    self.logger.error(f"End callback failed: {e}")
        if self.logger is not None:
            self.logger.state("Team trials routine complete")
        return DONE


def _configure_substeps(
    step: Step,
    logger: Any,
    pre_click_delay: float,
    max_click_retries: int,
    stuck_timeout: float,
) -> None:
    step.logger = logger
    step.pre_click_delay = pre_click_delay
    step.max_click_retries = max_click_retries
    step.stuck_timeout = stuck_timeout
    if isinstance(step, ClickStep):
        subs: list[Step] = []
        if step.if_found is not None:
            subs.append(step.if_found)
        subs.extend(step.blockers)
        subs.extend(step.alt_chain)
        for sub in subs:
            _configure_substeps(sub, logger, pre_click_delay, max_click_retries, stuck_timeout)


class Routine:
    def __init__(
        self,
        name: str,
        steps: list[Step],
        logger: Any,
        pre_click_delay: float = 0.1,
        max_click_retries: int = 5,
        stuck_timeout: float = 15.0,
    ) -> None:
        self.name = name
        self.steps = steps
        self.logger = logger
        self.done = False

        for i, step in enumerate(steps):
            step.index = i
            _configure_substeps(step, logger, pre_click_delay, max_click_retries, stuck_timeout)

        self._index = 0
        self._reset_on_enter(0)

    def _reset_on_enter(self, idx: int) -> None:
        if 0 <= idx < len(self.steps):
            self.steps[idx].reset()

    def tick(self, screenshot: Any) -> None:
        if self.done:
            return
        if self._index < 0 or self._index >= len(self.steps):
            self.done = True
            return

        cur = self.steps[self._index]
        result = cur.tick(screenshot)

        if result == WAIT:
            return
        if result == DONE:
            self.done = True
            return
        if result == RECOVER:
            self._recover(screenshot)
            return

        if result != self._index:
            self._advance_to(result)

    def _advance_to(self, new_idx: int) -> None:
        if new_idx != self._index:
            self._reset_on_enter(new_idx)
        self._index = new_idx

    def _recover(self, screenshot: Any) -> None:
        home_template = _load_template("templates/main/home.png", True)
        if home_template is not None:
            home_match = _match(screenshot, home_template, 0.85, True)
            if home_match is not None:
                try:
                    pyautogui.click(home_match.center[0], home_match.center[1])
                    self.logger.info("Clicked home.png during routine recovery")
                except Exception as e:
                    self.logger.error(f"Recovery home click failed: {e}")

        self.logger.state(f"Routine '{self.name}' aborted and restarted")
        self.done = True


def build_team_trials_routine(
    logger: Any,
    on_done: Callable[[], None] | None = None,
) -> Routine:
    select_opponent_index = 2
    home_index = 12

    steps: list[Step] = [
        ClickStep("templates/racemenu/teamtrials.png"),
        ClickStep("templates/racemenu/teamtrials/1.png"),
        ClickStep(
            "templates/racemenu/teamtrials/selectopponent.png",
            offset_below=50,
            ready_delay=2.0,
            if_found=ClickStep(
                "templates/racemenu/teamtrials/end.png",
                right_click=True,
                on_click=on_done,
            ),
            goto_step_if_found=home_index,
        ),
        ClickStep("templates/racemenu/teamtrials/2-6.png"),
        ClickStep("templates/racemenu/teamtrials/3.png"),
        ClickStep(
            "templates/racemenu/teamtrials/quickNo.png",
            if_found=AdvanceStep(),
        ),
        ClickStep("templates/racemenu/teamtrials/4.png"),
        ClickStep("templates/racemenu/teamtrials/5.png"),
        ClickStep("templates/racemenu/teamtrials/2-6.png"),
        ClickStep(
            "templates/racemenu/teamtrials/7.png",
            blockers=[
                ClickStep(
                    "templates/racemenu/teamtrials/shop.png",
                    right_click=True,
                )
            ],
            alt_chain=[
                ClickStep("templates/racemenu/teamtrials/smallnext.png"),
                ClickStep("templates/racemenu/teamtrials/2-6.png"),
            ],
        ),
        ClickStep(
            "templates/racemenu/teamtrials/end.png",
            right_click=True,
            goto_step_not_found=select_opponent_index,
        ),
        ClickStep("templates/racemenu/teamtrials/smallnext.png"),
        ClickStep(
            "templates/main/home.png",
            on_click=on_done,
        ),
        EndStep(on_done=on_done),
    ]

    return Routine("team_trials", steps, logger)