#!/usr/bin/env python3
"""Score the engine (and optionally the 2022 engine) on hand-labelled REAL screenshots.

Labels: ``docs/real_eval/real_labels.json`` — 89 player-POV screenshots from
VALORANT late 2021 / January–February 2022 (1920x1080 and 1920x1200), taken
from the MIT-licensed repository deepsidh9/Live-Valorant-Overlay. The images
themselves are not redistributed here; fetch them with:

    git clone https://github.com/deepsidh9/Live-Valorant-Overlay  real/deep1200
    git clone -b 1920x1080 https://github.com/deepsidh9/Live-Valorant-Overlay  real/deep1080

    python tools/eval_real.py --root real [--legacy] [--debug-dir out/]

Fields scored (only where the label is defined):
  alive (per slot, 10 per frame), alive count per side, spike planted,
  spike carrier slot, HP, shield, ability charges (C/Q/E), ult ready.

Frames 0-44 are the dev split (thresholds were fitted there); 45-88 are held out.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "tools"))

from valovision.detectors.base import normalise_frame   # noqa: E402
from valovision.pipeline import Engine                  # noqa: E402

PREFIX_MAP = {"deep1080/": "deep1080/", "deepsidh9_Live-Valorant-Overlay/": "deep1200/"}


def resolve(root: Path, rel: str) -> Path:
    for k, v in PREFIX_MAP.items():
        if rel.startswith(k):
            return root / (v + rel[len(k):])
    return root / rel


def v2_reader(engine: Engine):
    def read(img):
        s = engine.process(img, index=0)
        alive = [x["alive"] for side in ("left", "right") for x in s["teams"][side]]
        return {"alive": alive, "planted": s["spike"]["planted"], "carrier_slot": s["spike"]["carrier_slot"],
                "hp": s["player"]["hp"], "shield": s["player"]["shield"],
                "abilities": s["player"]["abilities"], "ult_ready": s["player"]["ult_ready"], "_state": s}
    return read


def legacy_reader():
    from benchmark import setup_legacy
    tmp, inf, _ = setup_legacy(Path(tempfile.mkdtemp(prefix="legacy2022_")))

    def read(img):
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            d = json.loads(inf.threading_call(img))
        finally:
            os.chdir(cwd)
        a = d["ALIVE_AGENTS"]

        def num(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return None
        hp = num(d.get("HP"))
        return {"alive": [a[f"agent{i}"] for i in range(1, 11)], "planted": bool(d.get("SPIKE_PLANTED")),
                "carrier_slot": d.get("SPIKE_CARRIER_IDX"), "hp": hp if hp else None,
                "shield": num(d.get("SHIELD")) or 0,
                "abilities": {"c": int(d.get("AB_C") or 0), "q": int(d.get("AB_Q") or 0), "e": int(d.get("AB_E") or 0)},
                "ult_ready": bool(d.get("ULT_READY"))}
    return read


def score(labels, root, reader, debug_dir=None, layout=None):
    ok, n = defaultdict(int), defaultdict(int)
    errors = defaultdict(list)
    for lab in labels:
        img = cv2.imread(str(resolve(root, lab["file"])))
        if img is None:
            raise FileNotFoundError(resolve(root, lab["file"]))
        img = normalise_frame(img, (1280, 720))
        p = reader(img)

        def check(field, pv, gv):
            n[field] += 1
            if pv == gv:
                ok[field] += 1
            else:
                errors[field].append({"idx": lab["idx"], "pred": pv, "gt": gv})

        if not lab["dm"]:
            for i, (pa, ga) in enumerate(zip(p["alive"], lab["alive"])):
                check("alive (per slot)", pa, ga)
            check("alive count, your team", sum(p["alive"][:5]), sum(lab["alive"][:5]))
            check("alive count, enemies", sum(p["alive"][5:]), sum(lab["alive"][5:]))
            check("spike planted", p["planted"], lab["planted"])
            check("spike carrier", p["carrier_slot"], lab["carrier_slot"])
        if lab["hud_visible"]:
            check("HP", p["hp"], lab["hp"])
            if lab["shield"] is not None:
                check("shield", p["shield"], lab["shield"])
        else:
            check("HUD hidden -> HP null", p["hp"], None)
        if lab.get("abilities"):
            for k in ("c", "q", "e"):
                check("ability charges (C/Q/E)", p["abilities"][k], lab["abilities"][k])
            check("ult ready", p["ult_ready"], lab["ult_ready"])
        if debug_dir is not None and "_state" in p:
            from valovision.annotate import draw_state
            cv2.imwrite(str(Path(debug_dir) / f"{lab['idx']:02d}.jpg"), draw_state(img, layout, p["_state"]),
                        [cv2.IMWRITE_JPEG_QUALITY, 85])
    return {k: {"accuracy": round(ok[k] / n[k], 4), "correct": ok[k], "n": n[k], "errors": errors[k][:12]}
            for k in n}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="folder containing deep1080/ and deep1200/")
    ap.add_argument("--labels", default=str(ROOT / "docs" / "real_eval" / "real_labels.json"))
    ap.add_argument("--layout", default=None)
    ap.add_argument("--legacy", action="store_true", help="also score the recovered 2022 engine")
    ap.add_argument("--debug-dir")
    ap.add_argument("--out", default=str(ROOT / "docs" / "real_eval" / "results.json"))
    a = ap.parse_args()
    labels = json.loads(Path(a.labels).read_text())
    eng = Engine(a.layout)
    if a.debug_dir:
        Path(a.debug_dir).mkdir(parents=True, exist_ok=True)
    splits = {"dev (0-44)": [l for l in labels if l["idx"] < 45], "test (45-88)": [l for l in labels if l["idx"] >= 45],
              "all": labels}
    res = {"frames": len(labels), "v2": {}, "legacy_2022": {}}
    leg = legacy_reader() if a.legacy else None
    for name, labs in splits.items():
        res["v2"][name] = score(labs, Path(a.root), v2_reader(Engine(a.layout)), a.debug_dir if name == "all" else None, eng.layout)
        if leg:
            res["legacy_2022"][name] = score(labs, Path(a.root), leg)
    for name in splits:
        print(f"\n== {name}")
        print(f"{'field':26s} {'v2':>16s}" + (f" {'2022 engine':>18s}" if a.legacy else ""))
        for k, v in res["v2"][name].items():
            line = f"{k:26s} {v['accuracy'] * 100:6.1f}% ({v['correct']:>3}/{v['n']:<3})"
            if a.legacy:
                w = res["legacy_2022"][name][k]
                line += f"   {w['accuracy'] * 100:6.1f}% ({w['correct']:>3}/{w['n']:<3})"
            print(line)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
