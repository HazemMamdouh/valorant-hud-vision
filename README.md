# VALORANT Overlay Server (2022)

A real-time HUD reader for VALORANT (patch 4.x, early 2022). It captures the screen, reads the in-game HUD with classical image processing (OpenCV template matching, colour gates, edge energy and connected components, plus Tesseract for the health digits), and serves the result as JSON over Socket.IO to an overlay client.

## What it reads

| Field | How |
|---|---|
| `ALIVE_AGENTS` | Sobel edge energy over each of the 10 roster portraits in the top bar (right team via a mirrored frame) |
| `CURR_AGENT`, `AGENT_TEAM` | masked normalised cross-correlation against 18 agent portraits; team from a teal colour gate |
| `HP`, `SHIELD` | binarised crops of the health and shield numbers, read with Tesseract |
| `AB_C`, `AB_Q`, `AB_E` | ability charges: green-channel threshold + connected components |
| `AB_X`, `ULT_READY` | ultimate points from the gaps between pips (morphological closing), ult ready from component size |
| `CURR_WEAPON` | sidearm silhouette matched against kill-feed weapon icons |
| `SPIKE_PLANTED` | red ratio (two HSV hue bands) in the round-timer box |
| `SPIKE_CARRIER_IDX` | bright spike icon under one of the roster portraits |

All regions are defined for a 1280×720 frame in [`Engine/screen_config.txt`](Engine/screen_config.txt); any screen is resized to that first. Each frame is processed by 14 detector threads whose results are merged into one JSON object.

## Layout

```
server.py                         Flask-SocketIO server, screen capture
Engine/
  inference_videos.py             runs all detectors on a frame (threading_call)
  get_agents.py                   alive roster, current agent
  get_agent_abilities_health.py   HP, shield, abilities, ultimate
  get_loadouts.py                 weapon detection
  get_spike_carrier.py            spike planted, spike carrier
  screen_config.txt               HUD regions and per-agent ability charges
  templates/agents|mainarms|sidearms   reference images
```

## Run

Windows 10/11, Python 3.9, and [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) installed at `C:\Program Files\Tesseract-OCR\`.

```bat
py -3.9 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

Start the server from the repository folder (paths are relative to it). VALORANT should run in borderless/windowed mode at 16:9 on the main monitor.

## Socket.IO API

The server listens on `http://localhost:5000`.

| Client emits | Server replies |
|---|---|
| `sign_in` `{name}` | `current_users` with all connected clients |
| `message` `{to, message}` | captures the screen, runs the engine and emits `message` with the JSON result in `message` to the sender and to `to` |
| `inf_screen` `{to}` | captures the screen, runs the engine and emits `inf_screen` with the JSON result to `to` |

Example result:

```json
{"ALIVE_AGENTS": {"agent1": false, "agent2": true, "agent3": true, "agent4": true, "agent5": true,
  "agent6": true, "agent7": true, "agent8": true, "agent9": false, "agent10": false},
 "AGENT_TEAM": "Red", "CURR_AGENT": null, "HP": "73", "SHIELD": "31",
 "AB_C": 2, "AB_Q": 1, "AB_E": 1, "AB_X": 3, "ULT_READY": false,
 "CURR_WEAPON": "Ghost", "SPIKE_PLANTED": null, "SPIKE_CARRIER_IDX": 4}
```

## Build the executable

```bat
pip install pyinstaller==4.10
pyinstaller --onefile server.py
```

Ship `dist\server.exe` next to the `Engine` folder (config and templates).

## Notes

VALORANT is a trademark of Riot Games. This project reads only the screen; it does not read game memory or send input to the game.
