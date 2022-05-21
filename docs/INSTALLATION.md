# Installation and usage manual

This covers installing the engine and overlay, running the demo, using it with the live game and OBS, calibrating it for real footage, and running the tests and benchmarks.

## 1. Requirements

| | Version | Needed for |
|---|---|---|
| Python | 3.9 – 3.13 | engine |
| Node.js + npm | 18 or newer | building the overlay |
| ffmpeg | any recent build, on `PATH` | `synth`, `analyze --annotate`, the robustness and render tools (not needed for live mode) |
| OS | Windows 10/11, Linux (X11), macOS | live screen capture via `mss` |
| Optional: Tesseract 4+ | — | only to benchmark the *2022* engine |
| Optional: Playwright + Chromium | — | only to re-render the overlay demo video |

No GPU is used. The engine runs on one CPU core.

## 2. Install

### Linux / macOS

```bash
git clone <repo-url> valorant-hud-vision
cd valorant-hud-vision

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e "engine[dev]"          # engine + test/benchmark extras

cd overlay
npm install
npm run build                         # -> overlay/dist, served by the engine
cd ..
```

### Windows (PowerShell)

```powershell
git clone <repo-url> valorant-hud-vision
cd valorant-hud-vision

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e "engine[dev]"

cd overlay; npm install; npm run build; cd ..
```

If PowerShell blocks the activate script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once. Install ffmpeg with `winget install Gyan.FFmpeg` if you want the sample tools.

### Check the install

```bash
valovision --help
python -m pytest engine/tests -q        # 26 tests, ~5 s
```

The `valovision` command is also available as `python -m valovision`.

## 3. The match system: 10 players, one engine, one commentator

This is the production setup. Architecture, protocol, fusion rules and sizing are in [SYSTEM.md](SYSTEM.md).

| Machine | Install | Run |
|---|---|---|
| Engine server (16 threads / 18 GB is plenty) | Python package only (`pip install -e engine`) | `valovision engine` |
| Each player PC (×10) | Python package only | `valovision send` |
| Commentator machine | Python package **and** the built overlay (`overlay/dist`) | `valovision commentator` |

Players and the commentator never run the vision code; it simply isn't invoked there.

### 3.1 Engine server

```bash
# Linux/macOS (Windows PowerShell: $env:OMP_NUM_THREADS=1)
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1      # one thread per player worker, no BLAS thread storms
valovision engine --port 8000 --token MATCH_SECRET --forward-fps 10 --match-hz 15
```

Open port 8000 on the LAN only. `http://ENGINE_IP:8000/api/health` lists every connected player with frames received, analysed and dropped, plus decode and analysis time.

### 3.2 Each player PC

```bash
valovision send --engine ws://ENGINE_IP:8000/ingest --token MATCH_SECRET \
                --pid p1 --name Hazem --team A --agent Jett --source screen --fps 30
```

- `--pid` must be unique per player (p1…p10); `--team` is A or B, the same for all five teammates.
- `--agent` is the agent picked in the lobby. The engine uses it to know whose portrait is whose (the player HUD does not mark "me").
- Use `--source screen:2` if the game is on the second monitor. Use `--fps 15` on weak uplinks (about 14 Mbit/s instead of 28).
- The sender reconnects by itself if the engine restarts.

### 3.3 Commentator machine

```bash
cd overlay && npm install && npm run build && cd ..          # once
valovision commentator --engine ws://ENGINE_IP:8000/feed --token MATCH_SECRET --port 9000
```

| Open | You get |
|---|---|
| `http://localhost:9000/` | caster view: match bar, 10 live player tiles (video + HP/shield/charges/ult/loadout), focus feed, event log |
| `http://localhost:9000/feeds/p3.mjpeg` | one player's live video (OBS → Media Source → input URL) |
| `http://localhost:9000/api/match` | the fused match state as JSON |

Click a tile to put that player in the focus view.

### 3.4 Try the whole system on one machine

```bash
# a) real 2022 frames: 10 players each replay genuine January–February 2022 screenshots
git clone https://github.com/deepsidh9/Live-Valorant-Overlay real/deep1200
git clone -b 1920x1080 https://github.com/deepsidh9/Live-Valorant-Overlay real/deep1080
python tools/match_demo.py --mode real --real-root real --record match_real.mp4
#    --static          each player streams one fixed frame (feeds never change)
#    --focus-every 3   the caster focus switches to the next player every 3 s
python tools/match_demo.py --mode real --static --focus-every 3 --real-root real --record match_real_static.mp4

# b) one synchronised round seen by all 10 players (replica), with fusion scored against ground truth
valovision synth-match --out samples/match_replica        # or use the 10 POVs already in samples/
#    --scenery real (default): real 2022 map views behind the HUD; --scenery none: procedural world
python tools/match_demo.py --mode replica --povs samples/match_replica --fps 12 --replay --focus-every 3 \
    --record match_replica.mp4 --report report.json
#    --replay   pass 1 runs the live system with no browser and captures everything the commentator
#               pushes on /ws; pass 2 renders the caster UI from that capture at a steady 25 fps.
#               Without it, the UI is screenshotted live (choppy on small machines: the browser
#               competes with the system for CPU).
```

The demo starts the engine, the commentator and ten separate sender processes, records the caster UI in headless Chromium (needs `pip install playwright` and a Chromium), and prints throughput and accuracy.

## 4. Single-feed mode (one screen, no match system)

For a solo streamer, or for development: one process reads one screen and serves the transparent overlay.

```bash
valovision serve --source samples/sample_2022q1_30s.mp4      # or --source screen
```

| Open | You get |
|---|---|
| `http://127.0.0.1:8000/` | the overlay, live from the engine (transparent background) |
| `http://127.0.0.1:8000/?replay=/samples/sample_2022q1_30s.analysis.json&video=/samples/sample_2022q1_30s.mp4` | the overlay over the video, from recorded states |
| `http://127.0.0.1:8000/api/state` | latest state (`?format=legacy` for the 2022 keys) |
| `ws://127.0.0.1:8000/ws` | the push stream |

Press <kbd>D</kbd> on the overlay to toggle the raw JSON panel. In OBS, add a Browser source with that URL, sized to your canvas, above the game capture.

### Game settings

Windowed fullscreen or fullscreen, **16:9 or 16:10** (frames are normalised: the HUD scales with screen height), default HUD settings.

### Developing the overlay

```bash
valovision serve --source samples/sample_2022q1_30s.mp4   # terminal 1, port 8000
cd overlay && npm run dev                                 # terminal 2, http://localhost:5173
```

The Vite dev server proxies `/ws`, `/api` and `/samples` to port 8000. Add `?view=caster&ws=ws://localhost:9000/ws` to develop the caster view against a running commentator server.

## 5. Offline analysis of a recording

```bash
valovision analyze match.mp4 --workers 8 --out match.analysis.json --annotate match.debug.mp4
```

- `--workers N` splits the video into chunks for N processes (use your core count).
- The output JSON has `states` (tracked), `events`, timing statistics and, with `--groundtruth`, accuracy.
- `--annotate` writes a video with every ROI and its reading, which is the fastest way to spot a misaligned layout.

Single screenshot: `valovision frame screenshot.png --debug debug.png`.

## 6. Calibrating for real footage

The shipped layout is the 2022 Q1 HUD from the original `screen_config.txt`. For other HUD versions, or a capture that crops the frame:

1. Grab a screenshot of the game.
2. `valovision frame screenshot.png --debug debug.png` and open `debug.png`. Every ROI is drawn; small offsets are fixed automatically by registration (`hud_offset` in the state).
3. For larger differences, copy `engine/valovision/layouts/valorant_2022q1_720p.json`, edit the rectangles (`[x0, y0, x1, y1]` in 1280×720 coordinates) and run with `--layout my_layout.json`. A 2022-style `screen_config.txt` also works with `--layout`.

### Digit templates

The default digit set (`assets/templates/digits_valorant`) holds glyphs of the real VALORANT HUD font (MIT, see its `ATTRIBUTION.md`). If a future HUD changes the font, cut new templates from screenshots that between them show all ten digits. For example, HP "100", HP "73", HP "45", shield "50", HP "26", HP "89":

```bash
valovision make-digits --from-image shot1.png --rect 383,668,434,699 --labels 100 --out my_digits
valovision make-digits --from-image shot2.png --rect 383,668,434,699 --labels 73  --out my_digits
# ... until 0-9 all exist in my_digits/
```

Then copy `my_digits/*.png` to a new folder under `engine/valovision/assets/templates/` and set `"digit_set"` to that folder's name in your layout JSON. Later shots overwrite earlier ones for the same digit.

## 7. Tests, benchmark and reproducing the docs

```bash
python -m pytest engine/tests -q

# benchmark on the target machine (16 threads / 18 GB):
python tools/benchmark.py --threads 16 --mem-limit-gb 18     # -> docs/benchmark/benchmark.json

# robustness suite (+ 2022 engine comparison if Tesseract is installed)
python tools/robustness.py                                   # -> docs/benchmark/robustness.json

# redraw all charts and docs/SAMPLE_ANALYSIS.md
python tools/make_figures.py

# rebuild the sample video and its ground truth
valovision synth --out samples/sample_2022q1_30s.mp4 --groundtruth samples/sample_2022q1_30s.groundtruth.json
valovision analyze samples/sample_2022q1_30s.mp4 --groundtruth samples/sample_2022q1_30s.groundtruth.json \
    --out samples/sample_2022q1_30s.analysis.json --annotate samples/sample_2022q1_30s.annotated.mp4

# re-render the overlay demo video (needs: pip install playwright; python -m playwright install chromium)
python tools/render_overlay_video.py
```

### Benchmarking the 2022 engine

`tools/benchmark.py` runs the recovered legacy engine automatically when Tesseract is installed:

- Ubuntu/Debian: `sudo apt install tesseract-ocr` and `pip install -e "engine[legacy]"`
- Windows: install from the UB Mannheim build into `C:\Program Files\Tesseract-OCR\` (the path the 2022 code expects) and `pip install -e "engine[legacy]"`

Without Tesseract the legacy rows are skipped and recorded in the JSON as `legacy_error`.

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Overlay says "Engine offline" | The engine is not running or is on another port. Start `valovision serve`, or add `?ws=ws://host:port/ws`. |
| `GET /` returns 404 | The overlay is not built: run `npm run build` in `overlay/`. |
| All readings `null` on the live game | Wrong monitor (`--source screen:2`), or the game is not 16:9. Check with `?debug`. |
| HP reads wrong digits on real footage | The default digit set is the real HUD font; over very bright backgrounds misses happen (see docs/REAL_FOOTAGE.md). For another HUD version, cut new templates (section 6). |
| Caster tiles say "Offline" | That player's sender is not connected, or its last frame is older than 1.5 s. Check `http://ENGINE_IP:8000/api/health`. |
| A player shows as dead while alive | Their `--agent` does not match the agent they picked, so their portrait cannot be linked. Restart the sender with the right agent. |
| Engine CPU is high with 10 players | Set `OMP_NUM_THREADS=1`, lower `--fps` on senders (15 is enough), or lower `--forward-fps`. |
| Black frames on macOS | Grant Screen Recording permission to your terminal (System Settings > Privacy & Security). |
| Black frames on Linux Wayland | `mss` needs X11/XWayland; run the game and engine in an X11 session. |
| `ffmpeg failed` | ffmpeg is not on `PATH` (only the synth/annotate/render tools need it). |
| Benchmark aborts with `MemoryError` | `--mem-limit-gb` is below what the run needs; the benchmark holds `--frames` decoded frames (~2.7 MB each). Lower `--frames` or raise the limit. |
