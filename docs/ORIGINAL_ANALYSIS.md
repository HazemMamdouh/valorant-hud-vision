# The 2022 engine: recovery and analysis

## What was delivered in 2022

```
New_Valorant_Server/
  server.exe                 381 MB, PyInstaller 4.10 one-file bundle, CPython 3.9, Windows x64
  Engine/screen_config.txt   ROI coordinates + per-agent ability charges
  Engine/templates/          18 agent portraits, 12 primary + 6 secondary kill-feed icons
  chat-example/              Angular 11 + ngx-socket-io "chat" client
```

There was no Python source in the archive. The engine existed only inside `server.exe`.

## Recovery

1. `pyinstxtractor-ng` unpacked the bundle: 4,426 modules in the PYZ archive plus the entry point `server.pyc`. The user code is `server.pyc` and the package `Engine/` (`get_agents`, `get_agent_abilities_health`, `get_loadouts`, `get_spike_carrier`, `inference_videos`).
2. `pycdc` decompiled the module structure. It fails on CPython 3.9 control flow in the core methods (`identify_agent`, `get_abilities`, `get_loadouts`, …), so those were rebuilt by hand from `pycdas` disassembly, opcode by opcode.
3. The reconstruction in [`legacy/recovered_2022/`](../legacy/recovered_2022) keeps the original logic, including its bugs. It is validated by running it: it reads the sample replica at 100% on the 12 fields compared. The exception is its ult-point counter (`AB_X`), which returns 0: it counts the 1 px gaps between the real game's ult pips, a geometry the replica does not reproduce, so that field is left out of the comparison.

The bundle also shows what the build machine had installed: PyQt5, IPython, Jupyter, jedi, black, Sphinx, gevent, debugpy and more. None are used by the engine. This is why the binary was 381 MB; the engine itself needs NumPy, OpenCV, Flask-SocketIO and pytesseract.

## How it worked

```mermaid
sequenceDiagram
  participant UI as Angular chat client
  participant S as Flask-SocketIO (eventlet)
  participant E as Engine (threading_call)
  UI->>S: emit("message", {to, message})
  S->>S: pyautogui.screenshot()  (PIL, full desktop)
  S->>E: threading_call(frame)
  E->>E: resize to 1280x720
  E->>E: start 11 threads, join; start 3 threads, join
  E-->>S: json.dumps(result)
  S-->>UI: emit("message", {message: str(json)})
```

The engine ran **only when a client sent a chat message**. There was no capture loop, so the "overlay" refresh rate was however fast the client sent messages. The Angular app was a generic chat example: it listed connected users and printed each JSON result as a chat bubble.

### Detectors (as recovered)

| Module / method | Reads | Technique | Notes |
|---|---|---|---|
| `GetCurrAgentInfo.get_curr_agent` | current agent, team | crop 55×55; `inRange` BGR teal gate > 25% → "Green"; masked `TM_CCOEFF_NORMED` against 18 portraits | returns the **last** template scoring > 0.5, not the best |
| `get_agent_health(…, 'hp' / 'sh')` | HP, shield | gray → `THRESH_BINARY_INV` 160 → `pytesseract.image_to_string(--psm 6)` → regex keep digits | Tesseract ≥ 4 is an LSTM network; each call spawns a process |
| `get_abilities(…, c/q/e)` | charges | G channel > 220, `connectedComponentsWithStats`, count areas ≥ 0.8 × max (min 50) | area per label via `np.sum(labels == i)`: one full-image pass per component |
| `get_abilities(…, 'x')` | ult points | G > 200, horizontal close − original, count gap components | tuned to real 2022 pips |
| `get_abilities(…, 'Ult')` | ult ready | any component > 250 px | |
| `GetLiveAgents.get_alive_agents` | 5 alive flags | Sobel dx (CV_8U) on the top strip, 5 equal columns, energy > 100 | right team via `cv2.flip` of the **whole frame** |
| `GetLoadouts.get_loadouts` | secondary weapon | gray > 160, reject if fill > 1/3, NCC vs binarised kill-feed icons | `get_loadouts2` (primary) exists but is never called |
| `GetSpike.get_spike_status` | planted | HSV red (two hue bands) > 50% of the icon box | resizes the frame again |
| `GetSpike.get_spike_carrier` | carrier slot | luma > 240 per 1/5 column of the row under the portraits | flips the whole frame again for the right team |
| `inference_videos.threading_call` | everything | 14 `threading.Thread` objects per frame writing to one dict | |

## Findings

Severity is from the point of view of a live overlay.

| # | Finding | Effect | Severity | Fixed in v2 by |
|---|---|---|---|---|
| 1 | Tesseract OCR for HP/shield | ~130–165 ms per frame (measured), a learned model, Windows path hard-coded | high | template digit reader (`ocr.py`), 0.44 ms for both numbers |
| 2 | Engine runs per chat message, `pyautogui` full-desktop grab | no steady frame rate; a PIL round-trip per grab (capture cost not measured here: no display in the test environment) | high | capture thread with `mss` at a fixed FPS, WebSocket push |
| 3 | 14 threads created per frame, results in a shared dict | thread start/join overhead; with OCR stubbed out the 2022 pipeline still cost 10.5 ms | medium | sequential pipeline (1.8 ms); persistent pool optional |
| 4 | `identify_agent` keeps the *last* template > 0.5 | picks whichever agent sorts later when two score above 0.5; no confidence | medium | arg-max + confidence score |
| 5 | Weapon templates via `imread(…, 0)` | alpha is dropped; Vandal's transparent pixels have RGB ≈ 85, so the binary template has 54% "on" pixels vs 31% real silhouette | medium | binary template from the alpha channel |
| 6 | Weapon templates resized/padded every frame, squashed when wider than the slot | wasted work; distorted long guns | low | aspect-preserving fit, computed once |
| 7 | Frame resized up to 4×, full-frame flips ×2 | ~1 ms wasted per frame | low | one resize, mirrored ROIs |
| 8 | Fixed thresholds (alive 100, luma 160/120/220/240, > 50 % red) | 53–96 % accuracy under degradation on the replica; on real 2022 frames it misses most hollow-triangle plants (planted 88.6 %) and bright-sky carrier rows (79.5 %) (measured) | high | adaptive gates, health-bar alive cue, triangle-tip plant rule, carrier icon NCC (docs/REAL_FOOTAGE.md) |
| 9 | Rigid ROIs | a 3 px misalignment costs HP and shield readings (measured) | medium | frame normalisation (16:9/16:10/21:9); HUD registration exists for the spectator HUD (off by default: the player HUD has no anchor portrait) |
| 10 | `get_spike_status` returns `None` instead of `False` | inconsistent JSON | low | booleans |
| 11 | Only the sidearm is reported as `CURR_WEAPON` | primary weapon never reported | medium | primary + secondary + equipped slot |
| 12 | Empty OCR → HP 0 | "0 HP" when the HUD is hidden | medium | `null` + tracker hold |
| 13 | No temporal logic | flicker passes straight to the UI; no events | medium | tracker: vote, bridging, events |
| 14 | Unused imports (`turtle`, `difflib.diff_bytes`, `tracemalloc.start`), dev tools frozen into the exe | 381 MB binary, Tk loaded at import | low | clean package, 6 runtime dependencies |
| 15 | Config parsed by hand in four classes; paths relative to the CWD | breaks when started from another folder | low | one `Layout` object, package-relative assets |

## What was worth keeping

The core idea holds up: the VALORANT HUD is a fixed, high-contrast graphic, and classical operators read it reliably at a tiny cost. Every v2 detector is still template matching, colour gating, edges, components or morphology. The layout coordinates were correct (the replica built from them is read at 100% by the 2022 code on the 12 compared fields). The agent and weapon templates are reused as they are.
