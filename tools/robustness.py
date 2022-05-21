#!/usr/bin/env python3
"""Stress-test the detectors against realistic degradations of the sample clip.

A replica rendered from the engine's own layout is the *easy* case, so a 100 %
score on it says little. This script degrades the clip the way real captures
degrade (stream compression, resolution changes, blur, exposure, sensor noise,
a HUD that is a few pixels off the layout) and reports per-field accuracy of
the raw per-frame readings (no temporal smoothing) for each condition.

It also scores the recovered 2022 engine on the clean clip for the fields it
supports, so old vs new is compared on identical frames.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "tools"))

from valovision.evaluate import FIELDS, evaluate   # noqa: E402
from valovision.pipeline import Engine             # noqa: E402


def ffmpeg(src, dst, *args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), *args, "-pix_fmt", "yuv420p", str(dst)],
                   check=True)
    return dst


def gamma(f, g):
    lut = (np.linspace(0, 1, 256) ** g * 255).astype(np.uint8)
    return cv2.LUT(f, lut)


def shift(f, dx, dy):
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(f, M, (f.shape[1], f.shape[0]), borderMode=cv2.BORDER_REPLICATE)


def noise(f, s, rng=np.random.default_rng(0)):
    return np.clip(f.astype(np.int16) + rng.normal(0, s, f.shape).astype(np.int16), 0, 255).astype(np.uint8)


def run(video, gt, step, transform=None, engine=None):
    eng = engine or Engine()
    cap = cv2.VideoCapture(str(video))
    preds, gts, i = [], [], 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if i % step == 0:
            if transform:
                f = transform(f)
            p = eng.process(f, index=i)
            preds.append(p)
            gts.append(gt[i])
        i += 1
    return evaluate(preds, gts)


LEGACY_FIELDS = ["player.hp", "player.shield", "ability.c", "ability.q", "ability.e", "ult.ready",
                 "loadout.secondary", "spike.planted", "spike.carrier", "roster.alive(10)"]


def legacy_to_state(d: dict) -> dict:
    alive = d["ALIVE_AGENTS"]

    def num(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    return {"player": {"agent": d.get("CURR_AGENT"), "team": "ally" if d.get("AGENT_TEAM") == "Green" else "enemy",
                       "hp": num(d.get("HP")), "shield": num(d.get("SHIELD")),
                       "abilities": {"c": int(d.get("AB_C") or 0), "q": int(d.get("AB_Q") or 0), "e": int(d.get("AB_E") or 0)},
                       "ult_points": d.get("AB_X"), "ult_ready": bool(d.get("ULT_READY"))},
            "loadout": {"primary": None, "secondary": d.get("CURR_WEAPON"), "active": None},
            "spike": {"planted": bool(d.get("SPIKE_PLANTED")), "carrier_slot": d.get("SPIKE_CARRIER_IDX")},
            "teams": {"left": [{"alive": alive[f"agent{i}"], "agent": None} for i in range(1, 6)],
                      "right": [{"alive": alive[f"agent{i}"], "agent": None} for i in range(6, 11)]}}


def run_legacy(video, gt, step, transform=None, ctx=None):
    import os
    from benchmark import setup_legacy
    if ctx is None:
        ctx = setup_legacy(Path(tempfile.mkdtemp(prefix="legacy2022_")))
    tmp, inf, _ = ctx
    cwd = os.getcwd()
    os.chdir(tmp)
    cap = cv2.VideoCapture(str(video))
    preds, gts, i = [], [], 0
    try:
        while True:
            ok, f = cap.read()
            if not ok:
                break
            if i % step == 0:
                if transform:
                    f = transform(f)
                preds.append(legacy_to_state(json.loads(inf.threading_call(f))))
                gts.append(gt[i])
            i += 1
    finally:
        os.chdir(cwd)
    rep = evaluate(preds, gts)
    return {k: rep[k] for k in LEGACY_FIELDS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default=str(ROOT / "samples" / "sample_2022q1_30s.mp4"))
    ap.add_argument("--gt", default=str(ROOT / "samples" / "sample_2022q1_30s.groundtruth.json"))
    ap.add_argument("--step", type=int, default=2)
    ap.add_argument("--legacy-step", type=int, default=6)
    ap.add_argument("--out", default=str(ROOT / "docs" / "benchmark" / "robustness.json"))
    a = ap.parse_args()
    gt = json.loads(Path(a.gt).read_text())["frames"]
    tmp = Path(tempfile.mkdtemp())
    variants = {
        "clean (x264 crf20)": (a.video, None),
        "stream compression (crf35)": (ffmpeg(a.video, tmp / "crf35.mp4", "-c:v", "libx264", "-crf", "35"), None),
        "540p source": (ffmpeg(a.video, tmp / "540.mp4", "-vf", "scale=960:540", "-c:v", "libx264", "-crf", "23"), None),
        "1080p source": (ffmpeg(a.video, tmp / "1080.mp4", "-vf", "scale=1920:1080", "-c:v", "libx264", "-crf", "23"), None),
        "gaussian blur s=1.2": (a.video, lambda f: cv2.GaussianBlur(f, (0, 0), 1.2)),
        "darker (gamma 1.4)": (a.video, lambda f: gamma(f, 1.4)),
        "brighter (gamma 0.7)": (a.video, lambda f: gamma(f, 0.7)),
        "sensor noise s=10": (a.video, lambda f: noise(f, 10)),
        "HUD offset 1 px": (a.video, lambda f: shift(f, 1, 1)),
        "HUD offset 3 px": (a.video, lambda f: shift(f, 3, 2)),
    }
    out = {"step": a.step, "fields": list(FIELDS), "variants": {}}
    for name, (video, tf) in variants.items():
        rep = run(video, gt, a.step, tf)
        out["variants"][name] = {k: v["accuracy"] for k, v in rep.items() if not k.startswith("_")}
        out["variants"][name]["_overall"] = rep["_overall"]["accuracy"]
        worst = sorted(((v, k) for k, v in out["variants"][name].items() if not k.startswith("_")))[:3]
        print(f"{name:28s} overall {rep['_overall']['accuracy'] * 100:6.2f}%   weakest: "
              + ", ".join(f"{k} {v * 100:.1f}%" for v, k in worst))
    try:
        from benchmark import setup_legacy
        ctx = setup_legacy(Path(tempfile.mkdtemp(prefix="legacy2022_")))
        out["legacy_vs_v2"] = {}
        print("\n2022 engine vs v2 on the 10 fields both support (same frames, every %d-th):" % a.legacy_step)
        for name, (video, tf) in variants.items():
            leg = run_legacy(video, gt, a.legacy_step, tf, ctx)
            new = run(video, gt, a.legacy_step, tf)
            lo = sum(leg[k]["accuracy"] for k in LEGACY_FIELDS) / len(LEGACY_FIELDS)
            nv = sum(new[k]["accuracy"] for k in LEGACY_FIELDS) / len(LEGACY_FIELDS)
            out["legacy_vs_v2"][name] = {"legacy_2022": round(lo, 4), "v2": round(nv, 4),
                                         "legacy_fields": {k: leg[k]["accuracy"] for k in LEGACY_FIELDS}}
            print(f"  {name:28s} 2022 {lo * 100:6.1f}%   v2 {nv * 100:6.1f}%")
    except Exception as e:
        out["legacy_error"] = str(e)
        print("legacy skipped:", e)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
