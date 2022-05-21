"""Offline analysis of a recording: per-frame states, events, timings.

Frames are independent for the CV stage, so a video is split into contiguous
chunks processed by a pool of worker *processes* (each with its own Engine);
the temporal tracker then runs once, in order, over the merged raw states.
"""
from __future__ import annotations

import json
import os
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

import cv2

from .pipeline import Engine
from .tracking import Tracker

_ENGINE: Optional[Engine] = None


def _init_worker(layout_path: Optional[str], cv_threads: int):
    global _ENGINE
    cv2.setNumThreads(cv_threads)
    _ENGINE = Engine(layout_path, mode="sequential")


def _process_chunk(args) -> List[dict]:
    path, start, stop, fps = args
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    out = []
    for i in range(start, stop):
        ok, f = cap.read()
        if not ok:
            break
        out.append(_ENGINE.process(f, index=i, timestamp=i / fps))
    cap.release()
    return out


def analyze_video(path: str | Path, workers: int = 1, layout: Optional[str] = None,
                  cv_threads: int = 1, chunk: int = 0) -> Dict:
    path = str(path)
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    t0 = time.perf_counter()
    if workers <= 1:
        _init_worker(layout, cv_threads)
        raw = _process_chunk((path, 0, n, fps))
    else:
        chunk = chunk or max(30, -(-n // workers))
        jobs = [(path, s, min(n, s + chunk), fps) for s in range(0, n, chunk)]
        with ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(layout, cv_threads)) as ex:
            raw = [s for part in ex.map(_process_chunk, jobs) for s in part]
    wall = time.perf_counter() - t0
    tracker = Tracker(fps=fps)
    states = [tracker.update(r) for r in raw]
    events = [e for s in states for e in s["events"]]
    lat = [s["latency_ms"] for s in raw]
    det = {}
    for s in raw:
        for k, v in s["timing_ms"].items():
            det.setdefault(k, []).append(v)
    return {
        "video": os.path.basename(path), "fps": fps, "frames": len(states),
        "workers": workers, "wall_s": round(wall, 3), "throughput_fps": round(len(states) / wall, 1),
        "latency_ms": {"median": round(statistics.median(lat), 3), "p95": round(sorted(lat)[int(0.95 * len(lat)) - 1], 3),
                       "max": round(max(lat), 3)},
        "detector_ms_median": {k: round(statistics.median(v), 3) for k, v in det.items()},
        "events": events, "states": states, "raw": raw,
    }


def save_analysis(result: Dict, out: str | Path, include_raw: bool = False) -> Path:
    out = Path(out)
    data = {k: v for k, v in result.items() if include_raw or k != "raw"}
    out.write_text(json.dumps(data, separators=(",", ":")))
    return out
