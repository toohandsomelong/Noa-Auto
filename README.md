<!-- TODO: replace this with your banner image -->
**[ BANNER IMAGE HERE ]**

# Noa Auto

[ badges: Python 3.10+ | Platform: Windows | License: MIT ]

**Noa Auto** is a Windows visual automation tool. It watches your screen,
finds UI elements by matching template images (OpenCV), and clicks them —
so you can automate repetitive flows in any desktop app or game, all from
a browser dashboard, with **no coding required**.

> Built as a game auto-clicker it
> works with anything that renders buttons on screen.

[ screenshot of the web dashboard here ]

---

## Table of Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Tutorial](#tutorial)
- [Plan JSON reference](#plan-json-reference)
- [Tuning & troubleshooting](#tuning--troubleshooting)
- [Project structure](#project-structure)
- [License](#license)

## Features

- 🖱️ **Visual automation** — OpenCV template matching (`TM_CCOEFF_NORMED`) with
  configurable threshold and grayscale matching.
- 🌐 **Web dashboard** — control everything from your browser at
  `http://127.0.0.1:6969` (opens automatically on launch). Live logs, live screen
  preview, and a visual routine editor.
- 🧩 **No-code routines ("plans")** — automations are simple JSON files. Create and
  edit them in the built-in editor, or by hand.
- 🔀 **Control flow** — jump between steps (`goto`), loop steps, fallback targets,
  and global **interrupt steps** that dismiss popups on any screen plus
  automatic screen re-anchoring (**resync**) when something unexpected happens.
- ⛓️ **Chaining & repeat** — queue multiple routines in a chain and repeat the
  whole chain N times.
- 🚀 **Auto game launch / window attach** — set a game path and window title;
  Noa Auto launches it or attaches to a running window (title auto-detected).
- 🔒 **Single instance** — a second launch won't fight the first.

## How it works

1. **Capture** — one `mss` screenshot of the screen per cycle.
2. **Match** — each step looks for its template images on screen.
3. **Act** — on a match, it clicks (left/right, with offsets) and advances to
   the next step or jumps via `goto`. Interrupt steps (popups) are checked first
   every cycle; a stuck step triggers resync to a visible screen.

A **routine** = ordered list of **steps**; a **step** = list of **targets**
(template image + what to do when found). Templates are just PNG crops of
buttons/UI elements you take yourself.

## Requirements

| | |
|---|---|
| OS | Windows 10/11 (uses Win32 APIs) |
| Python | 3.10+ |
| Screen | The app you automate must be **visible on screen** (not minimized/covered) |

## Installation

Download exe from https://github.com/toohandsomelong/Noa-Auto/releases
then extract it.

## Tutorial

### 1. Launch

Simply open exe if you download exe.

Your browser opens the dashboard automatically (fallback ports: 6967, 6767).

### 2. Record a routine (new)

The fastest way to build a plan is the overlay recorder.

1. In the dashboard, set **Tab Name** to the game window you want to capture, then click **Record** (or press **F8**). A small floating bar appears.
2. Navigate the game to the screen you want to capture and press **F9** (or **Add step** on the bar). The game client area freeze-frames into a crop overlay.
3. Drag a rectangle around the button/element you want to click (the **main** template). Optionally toggle **Add validation** and drag extra rectangles — they must all be visible for the step to match, but only the main one is clicked.
4. Pick the **action**: Left / Right / Continue / Scroll. For Scroll, click the anchor point where scrolling should happen, choose Up/Down, then **Confirm**.
5. Repeat for each screen, then press **F8** / **Stop**. The plan is saved and the editor opens pre-filled.

If two steps use the exact same template, the editor shows a "make goto" hint so you can turn the later step into a loop back without re-typing indices.

> ⚠️ Templates must be captured at the **same resolution & UI scale** you run at.

### 3. Capture template images manually (alternative)

Templates are small PNG crops of the buttons you want the bot to find.

1. In the dashboard, open **Capture Preview** and take a **Snapshot**.
2. Crop the button/UI element out of the snapshot in any image editor.
3. Save crops under `templates/` (e.g. `templates/mygame/start_button.png`).

### 4. Create a routine

Click **Create Routine** in the dashboard and add steps via the editor,
or drop a JSON file into `plans/` (see [Plan JSON reference](#plan-json-reference)).

Minimal example — wait for a start button, click it, then wait for the menu:

```json
{
  "name": "my_first_routine",
  "steps": [
    { "type": "click", "targets": [ { "template": "templates/mygame/start_button.png" } ] },
    { "type": "click", "targets": [ { "template": "templates/mygame/menu.png", "goto": 0 } ] }
  ],
  "config": { "game_path": null, "tab_name": null }
}
```

[ screenshot of the routine editor here ]

### 5. Configure the run

- **Tab Name** — title of the window to attach to (or leave empty).
- **Game Path** — exe to launch if no window is found (optional).
- **Active Chain** — ordered routines to run back-to-back.
- **Repeat** — how many times to run the whole chain.

### 6. Run

Hit **Start**. Watch the **Log** panel and **Live** preview to see matches
happening in real time. Hit **Stop** anytime.

## Plan JSON reference

`plans/<name>.json` — file stem = routine name.

**`config`**

| Key | Type | Default | Description |
|---|---|---|---|
| `delay` | float | `0.0` | Pause after each step's action |
| `timeout` | float | `15.0` | Seconds stuck on one step before resync (`null` = disabled) |
| `max_step_retry` | int | `15` | Retries before resync (`null` = disabled) |
| `resync_timeout` | float | `null` | Seconds to scan for a resume screen before aborting (`null` = poll forever) |
| `game_path` | string | `null` | Exe to launch when no window is found |
| `tab_name` | string | `null` | Window title to attach to (`null` = headless) |

**Steps** (`type: "click"` is the only type)

| Key | Type | Default | Description |
|---|---|---|---|
| `targets` | list | required | Templates to look for, in order — first match wins |
| `goto_step_if_not_found` | int | — | Step index to jump to when nothing matches |
| `ready_delay` | float | `0.0` | Extra wait after a match before acting |
| `threshold` | float | `0.85` | Match confidence for this step |
| `grayscale` | bool | `true` | Grayscale matching (faster, more tolerant) |
| `label` | string | — | Display name in logs/editor |

**Targets**

| Key | Type | Default | Description |
|---|---|---|---|
| `template` | string / list | required | PNG path(s). A list is AND-matched; click point uses the **first** item |
| `action` | string | `left_click` | `left_click` / `right_click` / `continue` (match only, no click) |
| `offset_x` / `offset_y` | int | `0` | Click offset from the match center |
| `goto` | int | next step | Step index to jump to after this target |
| `stay_on_confirm` | bool | `false` | Stay on this step (target can repeat) |
| `scrollValue` | int | `0` | For scroll-until-match: scroll amount per tick (positive = up) |
| `scroll_point` | `[x, y]` | — | For scroll-until-match: anchor point where scrolling happens |
| `threshold` | float | step's | Per-target match confidence |
| `grayscale` | bool | step's | Per-target grayscale |
| `label` | string | — | Display name in logs |

**Interrupt steps** — optional `interrupt_steps` list. Each entry is a normal
click step, but it is checked on **every tick regardless of the current step**
(use it for dialogs/popups that can appear anywhere). Interrupts never advance
the routine, and list order is priority — put network/retry first. A popup that
only ever appears on one screen is better modeled as a target inside that step.

When a step hits `timeout` / `max_step_retry`, the routine enters **resync**: it
scans for the next step whose targets are visible (forward successors first, the
stuck step only as a last resort) and resumes there after seeing it on two
consecutive frames. With `resync_timeout = null` it polls forever; set a value
to abort instead.

## Tuning & troubleshooting

| Problem | Fix |
|---|---|
| Bot never matches | Lower `threshold` (0.8 → 0.75); re-capture template at current resolution/scale |
| Bot clicks wrong spot | Template matched a similar element — raise `threshold` or use a tighter crop |
| Wrong window / nothing happens | The target window must be visible on screen, not minimized or covered |
| Flow gets stuck on random popups | Add the popup's button as a target, or as an interrupt step for popups that appear anywhere |
| Too fast / misses animations | Increase `delay` / `ready_delay` |
| Dashboard doesn't open | App already running (single-instance), or ports 6969/6967/6767 are busy |
| Routine stuck without resyncing | `timeout` / `max_step_retry` disabled (`null`)? Re-enable them |

## Project structure

```text
├── core/       # state, logging, screen capture + template matching, window management
├── routines/   # bot steps, enums, config, JSON plan loader
├── plans/      # your routine JSON files (created via the web UI)
├── templates/  # your template PNGs
├── web/        # FastAPI server + bot orchestrator
├── static/     # web dashboard (vanilla JS)
├── config.json # persisted dashboard config
└── main.py     # entry point
```

## License

[MIT](LICENSE)
