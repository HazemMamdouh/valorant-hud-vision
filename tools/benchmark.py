#!/usr/bin/env python3
"""ValoVision CPU benchmark.

Measures, on the sample clip (or any video):
  1. per-detector latency of the new engine;
  2. end-to-end per-frame latency: 2022 engine (with / without Tesseract)
     vs. the new engine (sequential / persistent thread pool);
  3. offline throughput (decode + detect) with 1..N worker processes;
  4. peak memory (RSS of the whole process tree).

Usage (target machine from the README: 16 threads, 18 GB):
    python tools/benchmark.py --threads 16 --mem-limit-gb 18

``--threads`` caps every pool and OpenCV's own thread count, and pins the
process to that many logical CPUs when the OS allows it. ``--mem-limit-gb``
sets RLIMIT_AS on Linux so the run fails loudly instead of swapping.
If the machine has fewer logical CPUs than requested, results above the
physical count are flagged ``oversubscribed`` and a projection (Amdahl fit on
the measured points) is reported separately — never mixed with measurements.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from valovision.analysis import analyze_video          # noqa: E402
from valovision.pipeline import Engine                  # noqa: E402


# ----------------------------------------------------------------- utilities
def cpu_model() -> str:
    try:
        for line in open("/proc/cpuinfo"):
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def total_ram_gb() -> float:
    try:
        import psutil
        return round(psutil.virtual_memory().total / 2 ** 30, 1)
    except Exception:
        return float("nan")


class PeakRSS(threading.Thread):
    """Samples memory of this process + children every 20 ms.

    Uses PSS (proportional set size) where available: forked workers share the
    parent's pages, and plain RSS would count those once per process.
    """

    def __init__(self):
        super().__init__(daemon=True)
        import psutil
        self.p = psutil.Process()
        self.peak = 0
        self.running = True

    def run(self):
        import psutil
        while self.running:
            try:
                procs = [self.p] + self.p.children(recursive=True)
                rss = 0
                for q in procs:
                    try:
                        rss += q.memory_full_info().pss
                    except (AttributeError, psutil.AccessDenied):
                        rss += q.memory_info().rss
                self.peak = max(self.peak, rss)
            except psutil.Error:
                pass
            time.sleep(0.02)

    def stop(self) -> float:
        self.running = False
        return round(self.peak / 2 ** 20, 1)


def stats(xs):
    xs = sorted(xs)
    return {"median": round(statistics.median(xs), 3), "mean": round(statistics.fmean(xs), 3),
            "p95": round(xs[max(0, int(0.95 * len(xs)) - 1)], 3), "min": round(xs[0], 3), "n": len(xs)}


def load_frames(video: str, n: int):
    cap = cv2.VideoCapture(video)
    frames = []
    while len(frames) < n:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    return frames


def time_fn(fn, frames, repeat=1, warmup=10):
    for f in frames[:warmup]:
        fn(f)
    out = []
    for _ in range(repeat):
        for f in frames:
            t0 = time.perf_counter()
            fn(f)
            out.append((time.perf_counter() - t0) * 1000)
    return out


# ----------------------------------------------------------------- legacy
def setup_legacy(tmp: Path):
    """Assemble the recovered 2022 engine in a temp dir (it uses ./Engine/... relative paths)."""
    eng = tmp / "Engine"
    eng.mkdir(parents=True)
    for p in (ROOT / "legacy" / "recovered_2022" / "Engine").glob("*.py"):
        shutil.copy(p, eng)
    shutil.copy(ROOT / "legacy" / "recovered_2022" / "Engine" / "screen_config.txt", eng)
    src = ROOT / "engine" / "valovision" / "assets" / "templates"
    for d in ("agents", "mainarms", "sidearms"):
        shutil.copytree(src / d, eng / "templates" / d)
    cwd = os.getcwd()
    os.chdir(tmp)
    sys.path.insert(0, str(tmp))
    try:
        from Engine import inference_videos as inf   # noqa
        from Engine import get_agent_abilities_health as gah  # noqa
    finally:
        os.chdir(cwd)
    return tmp, inf, gah


def run_legacy(tmp, inf, frames, with_ocr=True):
    cwd = os.getcwd()
    os.chdir(tmp)
    try:
        if not with_ocr:
            orig = inf.get_agent_info.get_agent_health
            inf.get_agent_info.get_agent_health = lambda *a, **k: 0
        lat = time_fn(inf.threading_call, frames, warmup=3)
        if not with_ocr:
            inf.get_agent_info.get_agent_health = orig
        return lat
    finally:
        os.chdir(cwd)


def hub_capacity(video: str, seconds: float = 8.0, players: int = 10) -> dict:
    """Saturate the engine server's 10 worker threads and count analysed frames/s.

    Each session is offered a new JPEG as soon as the previous one was taken, so
    the result is the maximum analysis rate of the engine machine (decode +
    detect + track), independent of network and senders.
    """
    import struct
    from valovision.hub import Hub
    cv2.setNumThreads(1)
    frames = load_frames(video, 60)
    jpgs = [cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes() for f in frames]
    hub = Hub()
    sess = [hub.join({"pid": f"p{i + 1}", "team": "A" if i < 5 else "B"}) for i in range(players)]
    t0 = time.time()
    k = 0
    while time.time() - t0 < seconds:
        for s in sess:
            if s.pending is None:
                hub.offer(s, struct.pack(">d", time.time()) + jpgs[k % len(jpgs)])
                k += 1
        time.sleep(0.0005)
    done = sum(s.frames_done for s in sess)
    hub.running = False
    wall = time.time() - t0
    return {"players": players, "seconds": round(wall, 2), "frames_analysed": done,
            "frames_per_s": round(done / wall, 1), "per_player_fps": round(done / wall / players, 1),
            "mean_decode_ms": round(float(np.mean([s.decode_ms for s in sess])), 2),
            "mean_process_ms": round(float(np.mean([s.proc_ms for s in sess])), 2)}


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default=str(ROOT / "samples" / "sample_2022q1_30s.mp4"))
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--mem-limit-gb", type=float, default=18)
    ap.add_argument("--frames", type=int, default=900)
    ap.add_argument("--legacy-frames", type=int, default=120)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--skip-legacy", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "docs" / "benchmark" / "benchmark.json"))
    a = ap.parse_args()

    logical = os.cpu_count() or 1
    try:
        avail = len(os.sched_getaffinity(0))
    except AttributeError:
        avail = logical
    threads = a.threads
    if hasattr(os, "sched_setaffinity") and threads < avail:
        os.sched_setaffinity(0, set(sorted(os.sched_getaffinity(0))[:threads]))
        avail = threads
    if a.mem_limit_gb and sys.platform.startswith("linux"):
        import resource
        lim = int(a.mem_limit_gb * 2 ** 30)
        resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
    cv2.setNumThreads(min(threads, avail))

    info = {"cpu": cpu_model(), "logical_cpus": logical, "cpus_available": avail,
            "requested_threads": threads, "ram_gb": total_ram_gb(), "mem_limit_gb": a.mem_limit_gb,
            "python": platform.python_version(), "opencv": cv2.__version__, "numpy": np.__version__,
            "os": f"{platform.system()} {platform.release()}", "video": Path(a.video).name}
    print(json.dumps(info, indent=2))
    res = {"system": info}

    frames = load_frames(a.video, a.frames)
    mon = PeakRSS(); mon.start()

    # 1. per-detector + end-to-end, new engine
    eng = Engine(mode="sequential")
    det = {}
    def run_seq(f):
        s = eng.process(f)
        for k, v in s["timing_ms"].items():
            det.setdefault(k, []).append(v)
    e2e_seq = time_fn(run_seq, frames, repeat=a.repeat)
    res["detectors_ms"] = {k: stats(v) for k, v in det.items()}
    res["latency_ms"] = {"v2_sequential": stats(e2e_seq)}
    for w in sorted({2, 4, min(threads, 8)}):
        eng_t = Engine(mode="threaded", workers=w)
        res["latency_ms"][f"v2_threadpool_{w}"] = stats(time_fn(lambda f: eng_t.process(f), frames, repeat=1))
        eng_t.close()
    print("v2 latency", res["latency_ms"])

    # 2. legacy 2022
    if not a.skip_legacy:
        try:
            tmp = Path(tempfile.mkdtemp(prefix="legacy2022_"))
            tmp, inf, _ = setup_legacy(tmp)
            sub = frames[:: max(1, len(frames) // a.legacy_frames)][: a.legacy_frames]
            res["latency_ms"]["legacy_2022_threads_tesseract"] = stats(run_legacy(tmp, inf, sub, True))
            res["latency_ms"]["legacy_2022_threads_no_ocr"] = stats(run_legacy(tmp, inf, sub, False))
            print("legacy", {k: v for k, v in res["latency_ms"].items() if k.startswith("legacy")})
        except Exception as e:   # Tesseract missing etc.
            res["legacy_error"] = f"{type(e).__name__}: {e}"
            print("legacy skipped:", res["legacy_error"])

    res["peak_mem_latency_phase_mb"] = round(mon.peak / 2 ** 20, 1)
    del frames, eng
    import gc
    gc.collect()
    mon.peak = 0

    # 3. throughput scaling (decode + detect), worker processes
    scaling = []
    ws = [w for w in (1, 2, 4, 8, 12, 16) if w <= threads]
    for w in ws:
        best = None
        for _ in range(2):
            r = analyze_video(a.video, workers=w)
            best = r if best is None or r["throughput_fps"] > best["throughput_fps"] else best
        scaling.append({"workers": w, "fps": best["throughput_fps"], "wall_s": best["wall_s"],
                        "oversubscribed": w > avail})
        print(f"workers={w:2d}  {best['throughput_fps']:7.1f} fps{'  (oversubscribed)' if w > avail else ''}")
    res["throughput"] = scaling
    res["peak_mem_throughput_phase_mb"] = mon.stop()

    # 3b. engine-server capacity: 10 player sessions, newest-frame-wins, pre-encoded JPEGs
    try:
        res["hub_capacity"] = hub_capacity(a.video, seconds=8.0)
        print("hub capacity", res["hub_capacity"])
    except Exception as e:
        res["hub_capacity_error"] = str(e)

    # 4. CPU cost per frame (single worker, decode + detect), then a bounded
    #    projection for the requested thread count if this box has fewer CPUs.
    import resource
    r0 = resource.getrusage(resource.RUSAGE_SELF)
    w0 = time.perf_counter()
    single = analyze_video(a.video, workers=1)
    r1 = resource.getrusage(resource.RUSAGE_SELF)
    cpu_ms = ((r1.ru_utime - r0.ru_utime) + (r1.ru_stime - r0.ru_stime)) * 1000 / single["frames"]
    res["cpu_ms_per_frame"] = round(cpu_ms, 3)
    res["wall_ms_per_frame_1worker"] = round((time.perf_counter() - w0) * 1000 / single["frames"], 3)
    meas = [s for s in scaling if not s["oversubscribed"]]
    if avail < threads and meas:
        best = max(meas, key=lambda s: s["fps"])
        eff = best["fps"] / (best["workers"] * 1000 / cpu_ms) if cpu_ms else 0
        res["projection"] = {
            "note": f"PROJECTION for {threads} threads - this machine has {avail} CPUs; not a measurement",
            "cpu_ms_per_frame": round(cpu_ms, 3),
            "ideal_fps": round(threads * 1000 / cpu_ms, 1),
            "measured_scaling_efficiency": round(eff, 3),
            "expected_fps": round(threads * 1000 / cpu_ms * min(1.0, eff), 1),
            "method": "fps(N) = N * 1000 / cpu_ms_per_frame * efficiency, efficiency measured at "
                      f"{best['workers']} workers on this machine",
        }
        print("projection", res["projection"])

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=2))
    print("->", a.out)


if __name__ == "__main__":
    main()
