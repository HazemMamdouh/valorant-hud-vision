"""Debug visualisation: draw every ROI and what the engine read from it."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, Optional

import cv2
import numpy as np

from .config import Layout

GREEN, RED, YELLOW, CYAN, WHITE = (90, 220, 120), (80, 80, 255), (0, 220, 255), (255, 220, 0), (255, 255, 255)


def _box(img, r, color, label=None, below=False):
    x0, y0, x1, y1 = r
    cv2.rectangle(img, (x0, y0), (x1 - 1, y1 - 1), color, 1)
    if label:
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.38, 1)
        ty = y1 + th + 3 if below else y0 - 3
        cv2.rectangle(img, (x0, ty - th - 2), (x0 + tw + 3, ty + 2), (0, 0, 0), -1)
        cv2.putText(img, label, (x0 + 1, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1, cv2.LINE_AA)


def draw_rois(img: np.ndarray, layout: Layout) -> np.ndarray:
    out = img.copy()
    for name, r in layout.all_rois().items():
        color = CYAN if name.startswith(("slot", "carrier")) else YELLOW
        _box(out, r, color, None if name.startswith(("slot", "carrier")) else name)
    return out


def draw_state(img: np.ndarray, layout: Layout, s: Dict) -> np.ndarray:
    out = img.copy()
    L, p, lo = layout, s["player"], s["loadout"]
    _box(out, L.current_agent, GREEN if p["agent"] else RED,
         f"{p['agent']} {p['agent_conf']:.2f} {p['team']}", below=False)
    _box(out, L.hp, GREEN if p["hp"] is not None else RED, f"HP {p['hp']}")
    _box(out, L.shield, GREEN, f"SH {p['shield']}", below=True)
    ab = p["abilities"]
    for k in ("c", "q", "e"):
        _box(out, L.abilities[k], GREEN, f"{k.upper()}={ab[k]}", below=True)
    ult = "READY" if p["ult_ready"] else f"{p['ult_points']}/{p['ult_max']}"
    _box(out, L.abilities["x"], YELLOW if p["ult_ready"] else GREEN, f"X {ult}", below=True)
    for slot in ("primary", "secondary"):
        tag = f"{lo[slot]}{' *' if lo['active'] == slot else ''}"
        _box(out, L.weapons[slot], GREEN if lo[slot] else RED, tag)
    sp = s["spike"]
    _box(out, L.spike, RED if sp["planted"] else GREEN, "PLANTED" if sp["planted"] else "spike", below=True)
    for side in ("left", "right"):
        for r, x in zip(L.roster_slot_rects(side), s["teams"][side]):
            _box(out, r, GREEN if x["alive"] else RED)
            if x.get("has_spike"):
                cx = (r[0] + r[2]) // 2
                cv2.drawMarker(out, (cx, 73), YELLOW, cv2.MARKER_DIAMOND, 16, 2)
    lat = s.get("latency_ms")
    if lat is not None:
        cv2.putText(out, f"frame {s['frame']}  {lat:.2f} ms", (10, 712), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1,
                    cv2.LINE_AA)
    return out


def annotate_video(video: str | Path, states, layout: Layout, out: str | Path, fps: Optional[float] = None) -> Path:
    cap = cv2.VideoCapture(str(video))
    fps = fps or cap.get(cv2.CAP_PROP_FPS) or 30.0
    W, H = layout.base_resolution
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
           "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "21", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for s in states:
        ok, f = cap.read()
        if not ok:
            break
        f = cv2.resize(f, (W, H))
        proc.stdin.write(draw_state(f, layout, s).tobytes())
    proc.stdin.close()
    proc.wait()
    return Path(out)
