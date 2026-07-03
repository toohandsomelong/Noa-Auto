from __future__ import annotations

import math
import os
import random
import time
from typing import Any, Callable

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    pyautogui = None
    HAS_PYAUTOGUI = False

from screen_bot import MatchResult, _load_template, _match


WAIT = -1
DONE = -2
RECOVER = -3


def _human_move_to(target: tuple[int, int], duration: float = 0.2) -> None:
    if not HAS_PYAUTOGUI or pyautogui is None:
        return
    try:
        sx, sy = pyautogui.position()
        ex, ey = target
        dx, dy = ex - sx, ey - sy
        dist = math.hypot(dx, dy)
        if dist < 10:
            pyautogui.moveTo(ex, ey, duration=duration * 0.3)
            return
        ratio = random.uniform(0.1, 0.3)
        cx = (sx + ex) / 2 + (-dy / max(dist, 1)) * ratio * dist * 0.15
        cy = (sy + ey) / 2 + (dx / max(dist, 1)) * ratio * dist * 0.15
        n = 8
        for i in range(1, n + 1):
            t = i / n
            tweened = pyautogui.easeInOutQuad(t)
            x = (1 - tweened) ** 2 * sx + 2 * (1 - tweened) * tweened * cx + tweened ** 2 * ex
            y = (1 - tweened) ** 2 * sy + 2 * (1 - tweened) * tweened * cy + tweened ** 2 * ey
            pyautogui.moveTo(x, y, duration=duration / n)
    except Exception:
        pass


def _human_click(point: tuple[int, int]) -> None:
    _human_move_to(point)
    if HAS_PYAUTOGUI and pyautogui is not None:
        pyautogui.click()


def _human_right_click(point: tuple[int, int]) -> None:
    _human_move_to(point)
    if HAS_PYAUTOGUI and pyautogui is not None:
        pyautogui.rightClick()


class Step:
    index: int = 0
    logger = None
    pre_click_delay: float = 0.1
    max_click_retries: int = 5
    stuck_timeout: float = 15.0

    def tick(self, screenshot: Any) -> int:
        return WAIT

    def reset(self) -> None:
        pass


class ClickStep(Step):
    def __init__(
        self,
        template_path: str,
        threshold: float = 0.85,
        grayscale: bool = True,
        label: str | None = None,
        right_click: bool = False,
        on_click: Callable[[], None] | None = None,
    ) -> None:
        self.template_path = template_path
        self.threshold = threshold
        self.grayscale = grayscale
        self.label = label or os.path.basename(template_path)
        self.right_click = right_click
        self.on_click = on_click
        self.clicked = False
        self.click_count = 0
        self.seek_start_time = 0.0

    def reset(self) -> None:
        self.clicked = False
        self.click_count = 0
        self.seek_start_time = 0.0

    def tick(self, screenshot: Any) -> int:
        m = self._match(screenshot)
        if m is not None:
            if self.click_count < self.max_click_retries:
                time.sleep(self.pre_click_delay)
                self._click(m.center)
                if self.on_click is not None:
                    try:
                        self.on_click()
                    except Exception as e:
                        if self.logger is not None:
                            self.logger.error(f"on_click failed for {self.label}: {e}")
                self.click_count += 1
                self.clicked = True
                self.seek_start_time = 0.0
                return WAIT
            if self.logger is not None:
                self.logger.warning(
                    f"Step {self.label} retried {self.click_count}x without transition"
                )
            return RECOVER

        if self.clicked:
            return self.index + 1

        if self.seek_start_time == 0.0:
            self.seek_start_time = time.time()
        elif time.time() - self.seek_start_time > self.stuck_timeout:
            if self.logger is not None:
                self.logger.warning(
                    f"Step {self.label} not found for {self.stuck_timeout}s"
                )
            return RECOVER
        return WAIT

    def _match(self, screenshot: Any) -> MatchResult | None:
        template = _load_template(self.template_path, self.grayscale)
        if template is None:
            return None
        return _match(screenshot, template, self.threshold, self.grayscale)

    def _click(self, point: tuple[int, int]) -> None:
        if not HAS_PYAUTOGUI or pyautogui is None:
            return
        try:
            if self.right_click:
                pyautogui.rightClick(point[0], point[1])
            else:
                pyautogui.click(point[0], point[1])
        except Exception as e:
            if self.logger is not None:
                self.logger.error(f"Click failed for {self.label}: {e}")
            return
        btn = "Right-clicked" if self.right_click else "Clicked"
        if self.logger is not None:
            self.logger.info(f"{btn} {self.label} at {point}")


class OffsetClickStep(Step):
    def __init__(
        self,
        template_path: str,
        offset_x: int = 0,
        offset_below: int = 50,
        threshold: float = 0.85,
        grayscale: bool = True,
        label: str | None = None,
        right_click: bool = False,
    ) -> None:
        self.template_path = template_path
        self.offset_x = offset_x
        self.offset_below = offset_below
        self.threshold = threshold
        self.grayscale = grayscale
        self.label = label or os.path.basename(template_path)
        self.right_click = right_click
        self.clicked = False
        self.click_count = 0
        self.seek_start_time = 0.0

    def reset(self) -> None:
        self.clicked = False
        self.click_count = 0
        self.seek_start_time = 0.0

    def tick(self, screenshot: Any) -> int:
        template = _load_template(self.template_path, self.grayscale)
        if template is None:
            return WAIT
        m = _match(screenshot, template, self.threshold, self.grayscale)

        if m is not None:
            if self.click_count < self.max_click_retries:
                time.sleep(self.pre_click_delay)
                target_x = m.location[0] + m.size[0] // 2 + self.offset_x
                target_y = m.location[1] + m.size[1] + self.offset_below
                self._click((target_x, target_y))
                self.click_count += 1
                self.clicked = True
                self.seek_start_time = 0.0
                return WAIT
            if self.logger is not None:
                self.logger.warning(
                    f"Step {self.label} retried {self.click_count}x without transition"
                )
            return RECOVER

        if self.clicked:
            return self.index + 1

        if self.seek_start_time == 0.0:
            self.seek_start_time = time.time()
        elif time.time() - self.seek_start_time > self.stuck_timeout:
            if self.logger is not None:
                self.logger.warning(
                    f"Step {self.label} not found for {self.stuck_timeout}s"
                )
            return RECOVER
        return WAIT

    def _click(self, point: tuple[int, int]) -> None:
        if not HAS_PYAUTOGUI or pyautogui is None:
            return
        try:
            if self.right_click:
                pyautogui.rightClick(point[0], point[1])
            else:
                pyautogui.click(point[0], point[1])
        except Exception as e:
            if self.logger is not None:
                self.logger.error(f"Click failed for {self.label}: {e}")
            return
        btn = "Right-clicked" if self.right_click else "Clicked"
        if self.logger is not None:
            self.logger.info(f"{btn} below {self.label} at {point}")


class QuickToggleStep(Step):
    def __init__(
        self,
        yes_template: str,
        no_template: str,
        threshold: float = 0.85,
        grayscale: bool = True,
    ) -> None:
        self.yes_template = yes_template
        self.no_template = no_template
        self.threshold = threshold
        self.grayscale = grayscale
        self.clicked = False
        self.click_count = 0
        self.seek_start_time = 0.0

    def reset(self) -> None:
        self.clicked = False
        self.click_count = 0
        self.seek_start_time = 0.0

    def tick(self, screenshot: Any) -> int:
        yes_match = self._templ_match(screenshot, self.yes_template)
        if yes_match is not None:
            if self.logger is not None:
                self.logger.info("Quick mode already enabled (quickYes)")
            return self.index + 1

        no_match = self._templ_match(screenshot, self.no_template)
        if no_match is not None:
            if self.click_count < self.max_click_retries:
                time.sleep(self.pre_click_delay)
                self._click(no_match.center)
                self.click_count += 1
                self.clicked = True
                self.seek_start_time = 0.0
                if self.logger is not None:
                    self.logger.info(f"Clicked quickNo ({self.click_count})")
                return WAIT
            if self.logger is not None:
                self.logger.warning(
                    f"QuickNo retried {self.click_count}x without transition"
                )
            return RECOVER

        if self.clicked:
            if self.logger is not None:
                self.logger.info("QuickNo transition confirmed, advancing")
            return self.index + 1

        if self.seek_start_time == 0.0:
            self.seek_start_time = time.time()
        elif time.time() - self.seek_start_time > self.stuck_timeout:
            if self.logger is not None:
                self.logger.warning(
                    f"Quick toggle not found for {self.stuck_timeout}s"
                )
            return RECOVER
        return WAIT

    def _templ_match(self, screenshot: Any, template_path: str) -> MatchResult | None:
        template = _load_template(template_path, self.grayscale)
        if template is None:
            return None
        return _match(screenshot, template, self.threshold, self.grayscale)

    def _click(self, point: tuple[int, int]) -> None:
        if not HAS_PYAUTOGUI or pyautogui is None:
            return
        try:
            pyautogui.click(point[0], point[1])
        except Exception as e:
            if self.logger is not None:
                self.logger.error(f"Click failed on quickNo: {e}")


class PopupGuardedClickStep(Step):
    def __init__(
        self,
        main_template: str,
        popups: list[str] | None = None,
        alts: list[str] | None = None,
        threshold: float = 0.85,
        grayscale: bool = True,
        label: str | None = None,
    ) -> None:
        self.main_template = main_template
        self.popups = popups or []
        self.alts = alts or []
        self.threshold = threshold
        self.grayscale = grayscale
        self.label = label or os.path.basename(main_template)
        self.main_clicked = False
        self.main_click_count = 0
        self.popup_clicks: dict[str, int] = {}
        self.alt_clicks: dict[str, int] = {}
        self.seek_start_time = 0.0

    def reset(self) -> None:
        self.main_clicked = False
        self.main_click_count = 0
        self.popup_clicks.clear()
        self.alt_clicks.clear()
        self.seek_start_time = 0.0

    def tick(self, screenshot: Any) -> int:
        was_visible: set[str] = {k for k, v in self.popup_clicks.items() if v > 0}

        for pt in self.popups:
            m = self._templ_match(pt, screenshot)
            if m is not None:
                cnt = self.popup_clicks.get(pt, 0)
                if cnt < self.max_click_retries:
                    time.sleep(self.pre_click_delay)
                    pyautogui.rightClick(m.center[0], m.center[1])
                    self.popup_clicks[pt] = cnt + 1
                    if self.logger is not None:
                        self.logger.info(f"Right-clicked popup {os.path.basename(pt)} ({cnt + 1})")
                    return WAIT
                if self.logger is not None:
                    self.logger.warning(f"Popup {os.path.basename(pt)} retried {cnt}x")
                return RECOVER
            if pt in was_visible:
                self.popup_clicks[pt] = 0

        m = self._templ_match(self.main_template, screenshot)
        if m is not None:
            if self.main_click_count < self.max_click_retries:
                time.sleep(self.pre_click_delay)
                pyautogui.click(m.center[0], m.center[1])
                self.main_click_count += 1
                self.main_clicked = True
                self.seek_start_time = 0.0
                if self.logger is not None:
                    self.logger.info(f"Clicked main {self.label} ({self.main_click_count})")
                return WAIT
            if self.logger is not None:
                self.logger.warning(f"Main {self.label} retried {self.main_click_count}x")
            return RECOVER

        if not self.main_clicked:
            for at in self.alts:
                m = self._templ_match(at, screenshot)
                if m is not None:
                    cnt = self.alt_clicks.get(at, 0)
                    if cnt < self.max_click_retries:
                        time.sleep(self.pre_click_delay)
                        pyautogui.click(m.center[0], m.center[1])
                        self.alt_clicks[at] = cnt + 1
                        if self.logger is not None:
                            self.logger.info(f"Clicked alt {os.path.basename(at)} ({cnt + 1})")
                        return WAIT
                    if self.logger is not None:
                        self.logger.warning(f"Alt {os.path.basename(at)} retried {cnt}x")
                    return RECOVER

        if self.main_clicked:
            return self.index + 1

        if self.seek_start_time == 0.0:
            self.seek_start_time = time.time()
        elif time.time() - self.seek_start_time > self.stuck_timeout:
            if self.logger is not None:
                self.logger.warning(
                    f"Step {self.label} not found for {self.stuck_timeout}s"
                )
            return RECOVER
        return WAIT

    def _templ_match(self, template_path: str, screenshot: Any) -> MatchResult | None:
        template = _load_template(template_path, self.grayscale)
        if template is None:
            return None
        return _match(screenshot, template, self.threshold, self.grayscale)


class RightClickBranchStep(Step):
    def __init__(
        self,
        template_path: str,
        goto_not_found: int,
        threshold: float = 0.85,
        grayscale: bool = True,
        label: str | None = None,
    ) -> None:
        self.template_path = template_path
        self.goto_not_found = goto_not_found
        self.threshold = threshold
        self.grayscale = grayscale
        self.label = label or os.path.basename(template_path)
        self.clicked = False
        self.click_count = 0
        self.seek_start_time = 0.0

    def reset(self) -> None:
        self.clicked = False
        self.click_count = 0
        self.seek_start_time = 0.0

    def tick(self, screenshot: Any) -> int:
        m = self._match(screenshot)
        if m is not None:
            if self.click_count < self.max_click_retries:
                time.sleep(self.pre_click_delay)
                pyautogui.rightClick(m.center[0], m.center[1])
                self.click_count += 1
                self.clicked = True
                self.seek_start_time = 0.0
                if self.logger is not None:
                    self.logger.info(f"Right-clicked {self.label} ({self.click_count})")
                return WAIT
            if self.logger is not None:
                self.logger.warning(
                    f"Step {self.label} retried {self.click_count}x without transition"
                )
            return RECOVER

        if self.clicked:
            return self.index + 1

        return self.goto_not_found

    def _match(self, screenshot: Any) -> MatchResult | None:
        template = _load_template(self.template_path, self.grayscale)
        if template is None:
            return None
        return _match(screenshot, template, self.threshold, self.grayscale)


class EndGuardStep(Step):
    def __init__(
        self,
        end_template: str,
        main_template: str,
        goto_if_end: int,
        offset_below: int = 0,
        threshold: float = 0.85,
        grayscale: bool = True,
        label: str | None = None,
        on_end: Callable[[], None] | None = None,
    ) -> None:
        self.end_template = end_template
        self.main_template = main_template
        self.goto_if_end = goto_if_end
        self.offset_below = offset_below
        self.threshold = threshold
        self.grayscale = grayscale
        self.label = label or "endguard"
        self.on_end = on_end
        self.end_clicked = False
        self.end_click_count = 0
        self.main_clicked = False
        self.main_click_count = 0
        self.seek_start_time = 0.0

    def reset(self) -> None:
        self.end_clicked = False
        self.end_click_count = 0
        self.main_clicked = False
        self.main_click_count = 0
        self.seek_start_time = 0.0

    def tick(self, screenshot: Any) -> int:
        end_match = self._templ_match(self.end_template, screenshot)
        if end_match is not None:
            if self.end_click_count < self.max_click_retries:
                time.sleep(self.pre_click_delay)
                if HAS_PYAUTOGUI and pyautogui is not None:
                    pyautogui.rightClick(end_match.center[0], end_match.center[1])
                self.end_click_count += 1
                self.end_clicked = True
                self.seek_start_time = 0.0
                if self.logger is not None:
                    self.logger.info(f"Right-clicked end ({self.end_click_count})")
                return WAIT
            return RECOVER

        if self.end_clicked:
            if self.logger is not None:
                self.logger.info("End guard confirmed, finishing")
            if self.on_end is not None:
                try:
                    self.on_end()
                except Exception as e:
                    if self.logger is not None:
                        self.logger.error(f"on_end callback failed: {e}")
            return self.goto_if_end

        m = self._templ_match(self.main_template, screenshot)
        if m is not None:
            if self.main_click_count < self.max_click_retries:
                time.sleep(self.pre_click_delay)
                target_x = m.location[0] + m.size[0] // 2
                target_y = m.location[1] + m.size[1] + self.offset_below
                if HAS_PYAUTOGUI and pyautogui is not None:
                    pyautogui.click(target_x, target_y)
                self.main_click_count += 1
                self.main_clicked = True
                self.seek_start_time = 0.0
                if self.logger is not None:
                    self.logger.info(f"Clicked selectopponent from guard ({self.main_click_count})")
                return WAIT
            return RECOVER

        if self.main_clicked:
            return self.index + 1

        if self.seek_start_time == 0.0:
            self.seek_start_time = time.time()
        elif time.time() - self.seek_start_time > self.stuck_timeout:
            return RECOVER
        return WAIT

    def _templ_match(self, template_path: str, screenshot: Any) -> MatchResult | None:
        template = _load_template(template_path, self.grayscale)
        if template is None:
            return None
        return _match(screenshot, template, self.threshold, self.grayscale)


class BranchStep(Step):
    def __init__(
        self,
        template_path: str,
        goto_found: int,
        goto_not_found: int,
        threshold: float = 0.85,
        grayscale: bool = True,
        label: str | None = None,
    ) -> None:
        self.template_path = template_path
        self.goto_found = goto_found
        self.goto_not_found = goto_not_found
        self.threshold = threshold
        self.grayscale = grayscale
        self.label = label or os.path.basename(template_path)

    def tick(self, screenshot: Any) -> int:
        template = _load_template(self.template_path, self.grayscale)
        if template is None:
            return self.goto_not_found
        match = _match(screenshot, template, self.threshold, self.grayscale)
        if match is not None:
            if self.logger is not None:
                self.logger.info(f"{self.label} found; branching to {self.goto_found}")
            return self.goto_found
        return self.goto_not_found


class EndStep(Step):
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


class Routine:
    def __init__(
        self,
        name: str,
        steps: list[Step],
        logger,
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
            step.logger = logger
            step.pre_click_delay = pre_click_delay
            step.max_click_retries = max_click_retries
            step.stuck_timeout = stuck_timeout

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
            if home_match is not None and HAS_PYAUTOGUI and pyautogui is not None:
                try:
                    pyautogui.click(home_match.center[0], home_match.center[1])
                    self.logger.info("Clicked home.png during routine recovery")
                except Exception as e:
                    self.logger.error(f"Recovery home click failed: {e}")

        self.logger.state(f"Routine '{self.name}' aborted and restarted")
        self.done = True


def build_team_trials_routine(
    logger,
    on_done: Callable[[], None] | None = None,
) -> Routine:
    select_opponent_index = 2
    home_index = 12

    steps: list[Step] = [
        ClickStep("templates/racemenu/teamtrials.png"),
        ClickStep("templates/racemenu/teamtrials/1.png"),
        EndGuardStep(
            "templates/racemenu/teamtrials/end.png",
            "templates/racemenu/teamtrials/selectopponent.png",
            goto_if_end=home_index,
            offset_below=50,
            on_end=on_done,
        ),
        ClickStep("templates/racemenu/teamtrials/2-6.png"),
        ClickStep("templates/racemenu/teamtrials/3.png"),
        QuickToggleStep(
            "templates/racemenu/teamtrials/quickYes.png",
            "templates/racemenu/teamtrials/quickNo.png",
        ),
        ClickStep("templates/racemenu/teamtrials/4.png"),
        ClickStep("templates/racemenu/teamtrials/5.png"),
        ClickStep("templates/racemenu/teamtrials/2-6.png"),
        PopupGuardedClickStep(
            "templates/racemenu/teamtrials/7.png",
            popups=["templates/racemenu/teamtrials/shop.png"],
            alts=["templates/racemenu/teamtrials/smallnext.png"],
        ),
        RightClickBranchStep(
            "templates/racemenu/teamtrials/end.png",
            goto_not_found=select_opponent_index,
        ),
        ClickStep("templates/racemenu/teamtrials/smallnext.png"),
        ClickStep(
            "templates/main/home.png",
            on_click=on_done,
        ),
        EndStep(on_done=on_done),
    ]

    return Routine("team_trials", steps, logger)
