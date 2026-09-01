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
  and automatic **recover steps** that bring the app back to a known state when
  something unexpected happens.
- ⛓️ **Chaining & repeat** — queue multiple routines in a chain and repeat the
  whole chain N times.
- 🚀 **Auto game launch / window attach** — set a game path and window title;
  Noa Auto launches it or attaches to a running window (title auto-detected).
- 🔒 **Single instance** — a second launch won't fight the first.

## How it works

1. **Capture** — one `mss` screenshot of the screen per cycle.
2. **Match** — each step looks for its template images on screen.
3. **Act** — on a match, it clicks (left/right, with offsets) and advances to
   the next step, jumps via `goto`, or runs recover steps if things go wrong.

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

```bash
git clone https://github.com/toohandsomelong/Noa-Auto.git
cd Noa-Auto
pip install -r requirements.txt
```

## Tutorial

### 1. Launch

```bash
python main.py
```

Your browser opens the dashboard automatically (fallback ports: 6967, 6767).

### 2. Capture template images

Templates are small PNG crops of the buttons you want the bot to find.

1. In the dashboard, open **Capture Preview** and take a **Snapshot**.
2. Crop the button/UI element out of the snapshot in any image editor.
3. Save crops under `templates/` (e.g. `templates/mygame/start_button.png`).

[ screenshot of capture preview / template cropping here ]

> ⚠️ Templates must be captured at the **same resolution & UI scale** you run at.

### 3. Create a routine

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

### 4. Configure the run

- **Tab Name** — title of the window to attach to (or leave empty).
- **Game Path** — exe to launch if no window is found (optional).
- **Active Chain** — ordered routines to run back-to-back.
- **Repeat** — how many times to run the whole chain.

### 5. Run

Hit **Start**. Watch the **Log** panel and **Live** preview to see matches
happening in real time. Hit **Stop** anytime.

## Plan JSON reference

`plans/<name>.json` — file stem = routine name.

**`config`**

| Key | Type | Default | Description |
|---|---|---|---|
| `delay` | float | `0.0` | Pause after each step's action |
| `timeout` | float | `15.0` | Seconds stuck on one step before recover (`null` = disabled) |
| `max_step_retry` | int | `15` | Retries before recover (`null` = disabled) |
| `max_recover` | int | `3` | Recover attempts before the routine aborts |
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
| `template` | string | required | PNG path (relative to repo root) |
| `action` | string | `left_click` | `left_click` / `right_click` / `continue` (match only, no click) |
| `offset_x` / `offset_y` | int | `0` | Click offset from the match center |
| `goto` | int | next step | Step index to jump to after this target |
| `stay_on_confirm` | bool | `false` | Stay on this step (target can repeat) |
| `threshold` | float | step's | Per-target match confidence |
| `grayscale` | bool | step's | Per-target grayscale |
| `label` | string | — | Display name in logs |

**Recover steps** — optional `recover_steps` list. When a step hits
`timeout` / `max_step_retry`, recover steps run (e.g. click the Home button to
reset the UI), then the routine restarts from step 0. Aborts after `max_recover`.

## Tuning & troubleshooting

| Problem | Fix |
|---|---|
| Bot never matches | Lower `threshold` (0.8 → 0.75); re-capture template at current resolution/scale |
| Bot clicks wrong spot | Template matched a similar element — raise `threshold` or use a tighter crop |
| Wrong window / nothing happens | The target window must be visible on screen, not minimized or covered |
| Flow gets stuck on random popups | Add the popup's button as an extra target or a recover step |
| Too fast / misses animations | Increase `delay` / `ready_delay` |
| Dashboard doesn't open | App already running (single-instance), or ports 6969/6967/6767 are busy |
| Routine stuck without recovering | `timeout` / `max_step_retry` disabled (`null`)? Re-enable them |

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
