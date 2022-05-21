#!/usr/bin/env python3
"""Render the *real* React overlay on top of the sample video, frame-exact.

1. serve overlay/dist + samples/ with the engine's FastAPI app (capture off);
2. open the overlay in headless Chromium (Playwright) in replay+step mode;
3. for each frame: ``window.__valovision.setFrame(i)``, screenshot with a
   transparent background, alpha-composite onto the decoded video frame;
4. pipe to ffmpeg (H.264).

    python tools/render_overlay_video.py            # -> samples/sample_2022q1_30s.overlay.mp4
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def serve(port: int):
    import uvicorn
    from valovision.server import create_app
    app = create_app(source="screen", start=False)
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(cfg)
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return srv
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("server did not start")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="samples/sample_2022q1_30s.mp4")
    ap.add_argument("--analysis", default="samples/sample_2022q1_30s.analysis.json")
    ap.add_argument("--out", default="samples/sample_2022q1_30s.overlay.mp4")
    ap.add_argument("--frames", type=int, default=0, help="limit (0 = all)")
    ap.add_argument("--still", help="also save this frame index as PNG (docs)", type=int, action="append")
    a = ap.parse_args()
    if not (ROOT / "overlay" / "dist" / "index.html").exists():
        sys.exit("overlay/dist missing - run `npm run build` in overlay/ first")

    from playwright.sync_api import sync_playwright
    port = free_port()
    serve(port)
    rel = Path(a.analysis).resolve().relative_to((ROOT / "samples").resolve())
    url = f"http://127.0.0.1:{port}/?replay=/samples/{rel.as_posix()}&step"

    cap = cv2.VideoCapture(str(ROOT / a.video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if a.frames:
        n = min(n, a.frames)
    W, H = 1280, 720
    out = ROOT / a.out
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                           "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "20",
                           "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
                          stdin=subprocess.PIPE)
    stills = set(a.still or [])
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=_chromium())
        page = browser.new_page(viewport={"width": W, "height": H})
        page.goto(url)
        page.wait_for_function("window.__valovision && window.__valovision.ready", timeout=20000)
        page.evaluate("document.fonts.ready")
        t0 = time.time()
        for i in range(n):
            ok, frame = cap.read()
            if not ok:
                break
            page.evaluate("""i => new Promise(r => { window.__valovision.setFrame(i);
                              requestAnimationFrame(() => requestAnimationFrame(r)); })""", i)
            png = page.screenshot(omit_background=True, type="png")
            ov = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
            alpha = ov[:, :, 3:4].astype(np.float32) / 255.0
            frame = cv2.resize(frame, (W, H))
            comp = (frame.astype(np.float32) * (1 - alpha) + ov[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
            ff.stdin.write(comp.tobytes())
            if i in stills:
                cv2.imwrite(str(ROOT / "docs" / "images" / f"overlay_frame_{i:04d}.jpg"), comp, [cv2.IMWRITE_JPEG_QUALITY, 88])
            if i % 150 == 0:
                print(f"  frame {i}/{n}  {(time.time() - t0):.0f}s")
        browser.close()
    ff.stdin.close()
    ff.wait()
    print("->", out)


def _chromium():
    import glob
    import os
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    for pat in (f"{base}/chromium-*/chrome-linux/chrome", f"{base}/chromium"):
        hits = sorted(glob.glob(pat))
        if hits and os.path.isfile(hits[-1]):
            return hits[-1]
    return None   # let Playwright use its own managed browser


if __name__ == "__main__":
    main()
