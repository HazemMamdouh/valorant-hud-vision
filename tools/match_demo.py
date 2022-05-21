#!/usr/bin/env python3
"""End-to-end demo of the 10-player system on one machine.

Starts, as separate processes exactly as they would run on separate machines:
  * 1 ENGINE server        valovision engine        (all vision)
  * 1 COMMENTATOR server   valovision commentator   (relay + caster UI)
  * 10 PLAYER senders      valovision send          (capture/replay + JPEG only)
then records the caster UI in headless Chromium and writes a report.

Modes
-----
--mode real     each of the 10 players replays genuine VALORANT 2022 screenshots
                (89 hand-labelled frames, docs/REAL_FOOTAGE.md). Per-player readings
                are real-pixel readings; the frames come from different rounds of one
                player's games, so team-level fusion has no single truth here.
--mode replica  the 10 synchronised POVs of one scripted round (valovision synth-match),
                so the fused match state is scored against ground truth.

    python tools/match_demo.py --mode real    --real-root real/ --record samples/match_demo_real.mp4
    python tools/match_demo.py --mode replica --povs match10/   --record samples/match_demo_replica.mp4
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "tools"))
PY = sys.executable


def wait_port(port, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
            return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"port {port} did not open")


def get(url):
    with urllib.request.urlopen(url, timeout=3) as r:
        return json.loads(r.read())


# One fixed real screenshot per player for --static: varied states so every tile reads differently
# (frame index in docs/real_eval/real_labels.json: HP / shield / planted / carrier / ult differ).
STATIC_FRAMES = [87, 24, 19, 13, 15, 66, 77, 8, 20, 42]


def real_feeds(real_root: Path, workdir: Path, hold_frames: int, static: bool = False):
    """10 file lists of real 2022 screenshots (HUD visible).

    static=False: each player cycles through ~7 screenshots, each held `hold_frames` frames.
    static=True:  each player streams ONE screenshot for the whole demo (an unchanging feed).
    """
    from eval_real import resolve
    labels = json.loads((ROOT / "docs" / "real_eval" / "real_labels.json").read_text())
    usable = [l for l in labels if l["hud_visible"] and not l["dm"]]
    by_idx = {l["idx"]: l for l in labels}
    lists = []
    from valovision.sender import encode
    for i in range(10):
        mine = [by_idx[STATIC_FRAMES[i]]] if static else usable[i::10]
        jpgs = []
        for l in mine:     # what a player PC would send: 1280-wide JPEG (done once here, then forwarded as-is)
            out = workdir / f"real_{l['idx']:02d}.jpg"
            out.write_bytes(encode(cv2.imread(str(resolve(real_root, l["file"]))), 1280, 80))
            jpgs.append(str(out))
        lst = workdir / f"p{i + 1}.txt"
        lst.write_text("\n".join(j for j in jpgs for _ in range(1 if static else hold_frames)))
        lists.append((f"@{lst}", mine))
    return lists


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["real", "replica"], required=True)
    ap.add_argument("--real-root", help="folder with deep1080/ and deep1200/ (see tools/eval_real.py)")
    ap.add_argument("--povs", help="folder with p1.mp4..p10.mp4 + match.json (valovision synth-match)")
    ap.add_argument("--duration", type=float, default=24)
    ap.add_argument("--fps", type=float, default=8, help="frames/s each player sends")
    ap.add_argument("--record", help="mp4 of the caster UI")
    ap.add_argument("--record-fps", type=float, default=4)
    ap.add_argument("--replay", action="store_true",
                    help="record the commentator's live /ws stream, then render the caster UI from it at 25 fps "
                         "(smooth video; the browser does not compete with the live system for CPU)")
    ap.add_argument("--still", help="png of the caster UI mid-demo")
    ap.add_argument("--report", help="json report path")
    ap.add_argument("--static", action="store_true", help="real mode: each player streams one fixed screenshot")
    ap.add_argument("--focus-every", type=float, default=0,
                    help="seconds between commentator focus switches (clicks the next player tile)")
    ap.add_argument("--engine-port", type=int, default=8100)
    ap.add_argument("--commentator-port", type=int, default=9100)
    a = ap.parse_args()

    # one thread per player worker; NumPy's BLAS pool would oversubscribe (see INSTALLATION.md)
    env = dict(os.environ, PYTHONUNBUFFERED="1", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    procs = []
    logs = Path(tempfile.mkdtemp(prefix="vv_demo_"))

    def spawn(name, args):
        f = open(logs / f"{name}.log", "w")
        p = subprocess.Popen([PY, "-m", "valovision", *args], cwd=ROOT / "engine", env=env, stdout=f, stderr=subprocess.STDOUT)
        procs.append(p)
        return p

    report = {"mode": a.mode, "fps_per_player": a.fps, "duration_s": a.duration}
    try:
        spawn("engine", ["engine", "--port", str(a.engine_port), "--forward-fps", str(a.fps), "--match-hz", "10"])
        wait_port(a.engine_port)
        spawn("commentator", ["commentator", "--engine", f"ws://127.0.0.1:{a.engine_port}/feed",
                              "--port", str(a.commentator_port)])
        wait_port(a.commentator_port)

        if a.mode == "real":
            feeds = real_feeds(Path(a.real_root), logs, hold_frames=int(a.fps * 1.5), static=a.static)
            players = [(f"p{i + 1}", f"Player {i + 1}", "A" if i < 5 else "B", None, src) for i, (src, _) in enumerate(feeds)]
            report["real_frames_per_player"] = [[l["idx"] for l in mine] for _, mine in feeds]
        else:
            meta = json.loads((Path(a.povs) / "match.json").read_text())
            players = []
            for p in meta["players"]:      # pre-extract at the send rate -> senders forward JPEGs untouched
                d = logs / p["pid"]
                d.mkdir()
                subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str((Path(a.povs) / f"{p['pid']}.mp4").resolve()),
                                "-vf", f"fps={a.fps}", "-q:v", "4", str(d / "%05d.jpg")], check=True)
                lst = logs / f"{p['pid']}.txt"
                lst.write_text("\n".join(str(x) for x in sorted(d.glob("*.jpg"))))
                players.append((p["pid"], p["name"], p["team"], p["agent"], f"@{lst}"))
        start_at = time.time() + 4.0
        for pid, name, team, agent, src in players:
            args = ["send", "--engine", f"ws://127.0.0.1:{a.engine_port}/ingest", "--pid", pid, "--name", name,
                    "--team", team, "--source", src, "--fps", str(a.fps), "--duration", str(a.duration),
                    "--start-at", str(start_at)] + (["--no-loop"] if a.mode == "replica" else [])
            if agent:
                args += ["--agent", agent]
            spawn(f"send_{pid}", args)

        # ---- sample the fused state while the round plays; record the caster UI
        samples, shots = [], []
        import threading

        def sampler():
            while time.time() - start_at < a.duration:
                try:
                    m = get(f"http://127.0.0.1:{a.engine_port}/api/match")
                    samples.append((time.time() - start_at, m))
                except Exception:
                    pass
                time.sleep(0.2)
        threading.Thread(target=sampler, daemon=True).start()
        if a.replay:
            # Pass 1: the live system runs with no browser attached; a capture client records every
            # message the commentator server pushes on /ws (match state + forwarded JPEGs), with arrival time.
            captured = []
            cap = threading.Thread(target=capture_ws, args=(f"ws://127.0.0.1:{a.commentator_port}/ws", captured,
                                                           start_at, start_at + a.duration), daemon=True)
            cap.start()
            cap.join()
            health = get(f"http://127.0.0.1:{a.engine_port}/api/health")
            chealth = get(f"http://127.0.0.1:{a.commentator_port}/api/health")
            report["engine_health"] = health
            report["captured_messages"] = len(captured)
            # Pass 2: the caster UI replays exactly those messages on a 25 fps clock (render_replay)
            if a.record:
                render_replay(captured, a, f"http://127.0.0.1:{a.commentator_port}/")
                report["recording"] = a.record
        else:
            health, chealth = record_live(a, start_at, shots)
            report["engine_health"] = health
        report["commentator_health"] = chealth

        if a.record and shots:
            out = Path(a.record)
            out.parent.mkdir(parents=True, exist_ok=True)
            # screenshots land at irregular times under load: place each at its true timestamp
            first = cv2.imdecode(np.frombuffer(shots[0][1], np.uint8), cv2.IMREAD_COLOR)
            h, w = first.shape[:2]
            ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                                   "-s", f"{w}x{h}", "-r", str(a.record_fps), "-i", "-", "-c:v", "libx264", "-crf", "23",
                                   "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
            k = 0
            for i in range(int(a.duration * a.record_fps)):
                t = i / a.record_fps
                while k + 1 < len(shots) and shots[k + 1][0] <= t:
                    k += 1
                ff.stdin.write(cv2.imdecode(np.frombuffer(shots[k][1], np.uint8), cv2.IMREAD_COLOR).tobytes())
            ff.stdin.close()
            ff.wait()
            report["recording"] = str(out)

        if a.mode == "replica":
            report["fusion_accuracy"] = score_fusion(samples, json.loads((Path(a.povs) / "match.json").read_text()))
        sess = health["sessions"]
        report["throughput"] = {"players": len(sess),
                                "frames_analysed": sum(s["frames_done"] for s in sess),
                                "frames_dropped_newest_wins": sum(s["dropped"] for s in sess),
                                "mean_process_ms": round(float(np.mean([s["process_ms"] for s in sess])), 2),
                                "mean_decode_ms": round(float(np.mean([s["decode_ms"] for s in sess])), 2)}
    finally:
        for p in procs:
            p.send_signal(signal.SIGINT)
        time.sleep(1.0)
        for p in procs:
            if p.poll() is None:
                p.kill()
    print(json.dumps({k: v for k, v in report.items() if k not in ("engine_health",)}, indent=1))
    if a.report:
        Path(a.report).write_text(json.dumps(report, indent=1))
    print("logs:", logs)


def record_live(a, start_at, shots):
    """Record the caster UI live with timed screenshots (browser shares the CPU with the system)."""
    from playwright.sync_api import sync_playwright
    from render_overlay_video import _chromium
    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path=_chromium())
        page = br.new_page(viewport={"width": 1280, "height": 720})
        page.goto(f"http://127.0.0.1:{a.commentator_port}/")
        while time.time() < start_at:
            time.sleep(0.1)
        t_next = time.time()
        focus_k, focus_next = 0, start_at + 1.5
        while time.time() - start_at < a.duration:
            now = time.time()
            if a.focus_every and now >= focus_next:     # the commentator switches player
                tiles = page.locator(".tile")
                if tiles.count() >= 10:
                    tiles.nth(focus_k % 10).click()
                    focus_k += 1
                focus_next += a.focus_every
            if now >= t_next:
                t_next += 1.0 / a.record_fps
                if a.record:
                    shots.append((now - start_at, page.screenshot(type="jpeg", quality=85)))
                if a.still and not Path(a.still).exists() and now - start_at > a.duration * 0.6:
                    page.screenshot(path=a.still)
            time.sleep(0.01)
        health = get(f"http://127.0.0.1:{a.engine_port}/api/health")
        chealth = get(f"http://127.0.0.1:{a.commentator_port}/api/health")
        br.close()
    return health, chealth


def capture_ws(url, out, start_at, stop_at):
    """Subscribe to the commentator like a browser would and keep (t, message) for every message."""
    import asyncio
    import websockets

    async def run():
        while time.time() < start_at - 2:
            await asyncio.sleep(0.1)
        async with websockets.connect(url, max_size=None, ping_interval=None) as ws:
            while time.time() < stop_at:
                try:
                    m = await asyncio.wait_for(ws.recv(), 0.5)
                except asyncio.TimeoutError:
                    continue
                out.append((time.time() - start_at, m))
    asyncio.run(run())


def render_replay(captured, a, page_url, fps=25):
    """Render the caster UI from a captured /ws stream, one screenshot per 1/fps of stream time.

    The page's WebSocket is served by Playwright (route_web_socket); before each frame every message
    that had arrived by that instant is delivered, the page settles (React commit + image decode),
    then the frame is captured. The video therefore shows exactly what a commentator saw, at a
    steady frame rate, independent of how fast this machine can screenshot."""
    import re
    from playwright.sync_api import sync_playwright
    from render_overlay_video import _chromium
    out = Path(a.record)
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-c:v", "mjpeg", "-r", str(fps),
                           "-i", "-", "-c:v", "libx264", "-crf", "21", "-preset", "medium", "-pix_fmt", "yuv420p",
                           "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
    settle = ("() => new Promise(r => requestAnimationFrame(() => Promise.all([...document.images]"
              ".map(i => i.decode().catch(() => {}))).then(() => requestAnimationFrame(r))))")
    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path=_chromium())
        page = br.new_page(viewport={"width": 1280, "height": 720})
        holder = {}
        page.route_web_socket(re.compile(r".*/ws$"), lambda ws: holder.setdefault("ws", ws))
        page.goto(page_url)
        while "ws" not in holder:
            page.wait_for_timeout(20)
        ws, k, focus_k, focus_next = holder["ws"], 0, 0, 1.5
        for i in range(int(a.duration * fps)):
            t = i / fps
            while k < len(captured) and captured[k][0] <= t:
                ws.send(captured[k][1])
                k += 1
            if a.focus_every and t >= focus_next:      # the commentator switches player
                tiles = page.locator(".tile")
                if tiles.count() >= 10:
                    tiles.nth(focus_k % 10).click()
                    focus_k += 1
                focus_next += a.focus_every
            page.evaluate(settle)
            jpg = page.screenshot(type="jpeg", quality=88)
            ff.stdin.write(jpg)
            if a.still and i == int(a.duration * fps * 0.6):
                Path(a.still).write_bytes(page.screenshot(type="png"))
        br.close()
    ff.stdin.close()
    ff.wait()


def score_fusion(samples, meta, lag_tolerance=0.6):
    """A fused field is correct if it matches the truth at some instant in [t - tolerance, t]."""
    truth = meta["truth"]
    ts = np.array([x["t"] for x in truth])

    def window(t):
        return [truth[i] for i in np.nonzero((ts <= t + 0.05) & (ts >= t - lag_tolerance))[0]]

    ok, n = {}, {}

    def check(k, cond):
        n[k] = n.get(k, 0) + 1
        ok[k] = ok.get(k, 0) + bool(cond)

    for t, m in samples:
        if t < 1.0 or t > meta["duration"] - 0.2:
            continue
        w = window(t)
        if not w:
            continue
        for team in ("A", "B"):
            check("team alive count", any(m["teams"][team]["alive"] == x["alive"][team] for x in w))
        check("spike planted", any(m["spike"]["planted"] == x["spike"]["planted"] for x in w))
        check("spike carrier (player)", any(m["spike"]["carrier_pid"] == x["spike"]["carrier"] for x in w))
        for p in m["players"]:
            check("player alive", any(p["alive"] == x["players"][p["pid"]]["alive"] for x in w))
            if any(x["players"][p["pid"]]["alive"] for x in w):
                check("player HP", any(p["hp"] == x["players"][p["pid"]]["hp"] for x in w))
                check("player C/Q/E", any(p["abilities"] == x["players"][p["pid"]]["abilities"] for x in w))
                check("player ult ready", any(p["ult_ready"] == x["players"][p["pid"]]["ult_ready"] for x in w))
                check("player loadout", any(p["loadout"]["primary"] == x["players"][p["pid"]]["loadout"]["primary"]
                                            for x in w))
    return {k: {"accuracy": round(ok[k] / n[k], 4), "n": n[k]} for k in n}


if __name__ == "__main__":
    main()
