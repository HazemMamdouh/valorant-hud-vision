#!/usr/bin/env python3
"""Generate the README / docs figures from the measured JSON results."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
IMG = ROOT / "docs" / "images"
IMG.mkdir(parents=True, exist_ok=True)

# validated reference palette (dataviz skill), light surface
SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"

plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "font.size": 10.5, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "font.family": "DejaVu Sans",
})


def latency(bench):
    L = bench["latency_ms"]
    rows = [("2022 engine (14 threads/frame + Tesseract)", L.get("legacy_2022_threads_tesseract")),
            ("2022 engine, OCR removed", L.get("legacy_2022_threads_no_ocr")),
            ("v2, persistent thread pool (2)", L.get("v2_threadpool_2")),
            ("v2, sequential (default)", L.get("v2_sequential"))]
    rows = [(n, v) for n, v in rows if v]
    fig, ax = plt.subplots(figsize=(9.6, 2.9))
    y = np.arange(len(rows))
    med = [v["median"] for _, v in rows]
    colors = [GRID if i < 2 else S1 for i in range(len(rows))]
    colors = ["#b9b8b2", "#b9b8b2"] + [S1] * (len(rows) - 2)
    ax.barh(y, med, height=0.55, color=colors[:len(rows)])
    for i, (n, v) in enumerate(rows):
        ax.text(v["median"] * 1.12, i, f"{v['median']:.1f} ms  (p95 {v['p95']:.1f})", va="center", color=INK,
                fontsize=10)
    ax.set_yticks(y, [n for n, _ in rows])
    ax.set_xscale("log")
    ax.set_xlim(0.8, 2500)
    ax.set_xticks([1, 10, 100, 1000], ["1", "10", "100", "1000"])
    ax.minorticks_off()
    ax.set_xlabel("Per-frame latency, median (ms, log scale) — lower is better")
    ax.grid(axis="y", visible=False)
    ax.invert_yaxis()
    ax.set_title("End-to-end latency per 720p frame", loc="left", fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(IMG / "latency.png", dpi=160)
    plt.close(fig)


def detectors(bench):
    d = {k: v["median"] for k, v in bench["detectors_ms"].items()}
    names = {"prepare": "resize + grayscale", "current_agent": "current agent + team", "roster": "roster alive / identity",
             "vitals": "HP + shield digits", "weapons": "loadout", "spike": "spike + carrier", "abilities": "abilities + ult"}
    items = sorted(d.items(), key=lambda kv: -kv[1])
    fig, ax = plt.subplots(figsize=(7.2, 2.8))
    y = np.arange(len(items))
    ax.barh(y, [v for _, v in items], height=0.55, color=S1)
    for i, (_, v) in enumerate(items):
        ax.text(v + 0.01, i, f"{v * 1000:.0f} µs", va="center", fontsize=9.5)
    ax.set_yticks(y, [names.get(k, k) for k, _ in items])
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("median ms per frame")
    ax.set_title("Where the 1.5 ms goes (v2, sequential)", loc="left", fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(IMG / "detectors.png", dpi=160)
    plt.close(fig)


def throughput(bench):
    th = bench["throughput"]
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    x = np.arange(len(th))
    for i, s in enumerate(th):
        ax.bar(i, s["fps"], width=0.6, color=S1 if not s["oversubscribed"] else "#c9d9ee",
               hatch=None if not s["oversubscribed"] else "///", edgecolor=SURF if not s["oversubscribed"] else S1,
               linewidth=0)
        ax.text(i, s["fps"] + 6, f"{s['fps']:.0f}", ha="center", fontsize=9.5)
    ax.set_xticks(x, [str(s["workers"]) for s in th])
    ax.set_xlabel(f"worker processes (machine has {bench['system']['cpus_available']} CPUs; hatched = oversubscribed)")
    ax.set_ylabel("frames / s (decode + detect)")
    ax.grid(axis="x", visible=False)
    ax.set_title("Offline analysis throughput, measured", loc="left", fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(IMG / "throughput.png", dpi=160)
    plt.close(fig)


def timeline(analysis, gt):
    st = analysis["states"]
    t = np.array([s["t"] for s in st])
    hp = np.array([np.nan if s["player"]["hp"] is None else s["player"]["hp"] for s in st], float)
    sh = np.array([np.nan if s["player"]["shield"] is None else s["player"]["shield"] for s in st], float)
    ghp = np.array([g["player"]["hp"] for g in gt][:len(st)], float)
    gsh = np.array([g["player"]["shield"] for g in gt][:len(st)], float)
    al = np.array([s["alive_count"]["left"] for s in st])
    ar = np.array([s["alive_count"]["right"] for s in st])
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 4.6), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    a1.plot(t, ghp, color="#b9b8b2", lw=5, solid_capstyle="round", label="ground truth")
    a1.plot(t, gsh, color="#b9b8b2", lw=5, solid_capstyle="round")
    a1.plot(t, hp, color=S1, lw=2, label="HP (detected)")
    a1.plot(t, sh, color=S2, lw=2, label="shield (detected)")
    a1.set_ylabel("points")
    a1.set_ylim(-5, 110)
    a1.legend(loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False, ncol=3, fontsize=9)
    a1.set_title("30 s sample round: engine output vs ground truth", loc="left", fontsize=12, fontweight="bold",
                 pad=22)
    a2.step(t, al, where="post", color=S3, lw=2, label="your team alive")
    a2.step(t, ar, where="post", color=S2, lw=2, label="enemies alive")
    a2.set_ylim(0, 5.6)
    a2.set_ylabel("alive")
    a2.set_xlabel("time (s)")
    a2.legend(loc="lower left", frameon=False, ncol=2, fontsize=9)
    for e in analysis["events"]:
        if e["type"] == "spike_planted":
            for ax in (a1, a2):
                ax.axvline(e["t"], color=INK2, lw=1, ls=(0, (3, 3)))
            a1.text(e["t"] + 0.2, 62, "spike planted", fontsize=9, color=INK2)
        if e["type"] == "ult_ready":
            a1.text(e["t"] + 0.2, 62, "ult ready", fontsize=9, color=INK2)
            a1.axvline(e["t"], color=INK2, lw=1, ls=(0, (1, 3)))
    fig.tight_layout()
    fig.savefig(IMG / "timeline.png", dpi=160)
    plt.close(fig)


def robustness(rob):
    V = rob["variants"]
    conds = list(V)
    fields = [f for f in rob["fields"]]
    M = np.array([[V[c][f] * 100 for f in fields] for c in conds])
    fig, ax = plt.subplots(figsize=(10, 4.4))
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("seq", ["#fbe3d6", "#f2a27d", "#eb6834", "#a8401a"][::-1] + [SURF][:0])
    # sequential single hue: errors are what matter, so shade by error rate
    err = 100 - M
    im = ax.imshow(err, cmap=LinearSegmentedColormap.from_list("e", [SURF, "#f7c9b2", S2, "#9a3a14"]),
                   vmin=0, vmax=60, aspect="auto")
    ax.set_xticks(range(len(fields)), fields, rotation=40, ha="right", fontsize=9)
    ax.set_yticks(range(len(conds)), conds, fontsize=9.5)
    ax.grid(False)
    for i in range(len(conds)):
        for j in range(len(fields)):
            v = M[i, j]
            if v < 99.95:
                ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=8.5,
                        color="#ffffff" if err[i, j] > 35 else INK)
    ax.set_title("Accuracy under degradation (raw per-frame, no smoothing) — blank cells are 100 %",
                 loc="left", fontsize=11.5, fontweight="bold")
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01)
    cb.set_label("error rate %")
    cb.outline.set_visible(False)
    fig.tight_layout()
    fig.savefig(IMG / "robustness.png", dpi=160)
    plt.close(fig)


def legacy_vs_v2(rob):
    d = rob.get("legacy_vs_v2")
    if not d:
        return
    names = list(d)
    leg = [d[n]["legacy_2022"] * 100 for n in names]
    new = [d[n]["v2"] * 100 for n in names]
    fig, ax = plt.subplots(figsize=(9.5, 3.4))
    x = np.arange(len(names))
    w = 0.36
    ax.bar(x - w / 2 - 0.01, leg, w, color="#b9b8b2", label="2022 engine")
    ax.bar(x + w / 2 + 0.01, new, w, color=S1, label="v2 (this repo)")
    for i in range(len(names)):
        if leg[i] < 99.5:
            ax.text(x[i] - w / 2, leg[i] + 0.6, f"{leg[i]:.0f}", ha="center", va="bottom", fontsize=8.5, color=INK2)
        if new[i] < 99.5:
            ax.text(x[i] + w / 2, new[i] + 0.6, f"{new[i]:.0f}", ha="center", va="bottom", fontsize=8.5, color=INK)
    ax.set_xticks(x, names, rotation=25, ha="right", fontsize=9)
    ax.set_ylim(50, 104)
    ax.set_ylabel("accuracy, 12 shared fields (%)")
    ax.grid(axis="x", visible=False)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, fontsize=9.5)
    ax.set_title("Same frames, same degradations: 2022 engine vs v2", loc="left", fontsize=12, fontweight="bold",
                 pad=24)
    fig.tight_layout()
    fig.savefig(IMG / "legacy_vs_v2.png", dpi=160)
    plt.close(fig)


def rois_and_techniques(video):
    from valovision.annotate import draw_rois, draw_state
    from valovision.pipeline import Engine
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 380)
    ok, f = cap.read()
    eng = Engine()
    s = eng.process(f, index=0)
    cv2.imwrite(str(IMG / "rois.jpg"), draw_rois(f, eng.layout), [cv2.IMWRITE_JPEG_QUALITY, 88])
    cv2.imwrite(str(IMG / "readings.jpg"), draw_state(f, eng.layout, s), [cv2.IMWRITE_JPEG_QUALITY, 88])
    L = eng.layout
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)

    def crop(r, img=f):
        x0, y0, x1, y1 = r
        return img[y0:y1, x0:x1]

    def up(img, h=90):
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        s_ = h / img.shape[0]
        return cv2.resize(img, None, fx=s_, fy=s_, interpolation=cv2.INTER_NEAREST)

    panels = []
    from valovision.detectors.abilities import teal_mask
    area = crop((L.roster_area_left[0], L.roster_area_left[1], L.roster_area_left[2], L.roster_area_left[3] + 12), g)
    sob = cv2.Sobel(area, cv2.CV_8U, 1, 0, ksize=3)
    panels.append(("Roster: survivors packed to the centre, health bar under each; Sobel-x energy + bar band", [area, sob]))
    hp = crop(L.hp, g)
    panels.append(("HP digits (real HUD font): ROI and relative gate -> components -> grey-glyph NCC",
                   [hp, np.where(hp > 0.72 * hp.max(), 255, 0).astype(np.uint8)]))
    ab = crop((L.abilities["c"][0], L.abilities["c"][1], L.abilities["x"][2], L.abilities["x"][3]))
    panels.append(("Abilities: teal gate (G, B >> R) -> bar segments; ult diamonds and ready bar", [ab, teal_mask(ab, 45)]))
    wp = crop(L.weapons["primary"], g)
    th = cv2.threshold(wp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    fitted = next(t for t in eng.weapons.banks["primary"].templates if t.name == "Vandal").fitted
    panels.append(("Loadout: ROI, Otsu silhouette, fitted kill-feed template", [wp, th, fitted]))
    cr = crop((L.carrier_row_left[0] - 4, L.carrier_row_left[1] - 2, L.carrier_row_left[2] + 4, L.carrier_row_left[3] + 2), g)
    res = cv2.matchTemplate(cr, eng.spike.carrier_tpl, cv2.TM_CCOEFF_NORMED)
    res = cv2.normalize(np.maximum(res, 0), None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    panels.append(("Spike carrier: NCC with the real carrier icon along the row (bright = match)",
                   [cr, eng.spike.carrier_tpl, res]))

    rows = []
    W = 1100
    for title, imgs in panels:
        row = np.full((128, W, 3), 252, np.uint8)
        cv2.putText(row, title, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (30, 30, 30), 1, cv2.LINE_AA)
        x = 10
        widths = [im.shape[1] * 90 / im.shape[0] for im in imgs]
        h = int(min(90, 90 * (W - 20 - 14 * (len(imgs) - 1)) / sum(widths)))
        for im in imgs:
            u = up(im, h)
            row[32:32 + u.shape[0], x:x + u.shape[1]] = u
            x += u.shape[1] + 14
        rows.append(row)
    cv2.imwrite(str(IMG / "techniques.png"), np.vstack(rows))


def sample_report(an, gt_doc):
    """docs/SAMPLE_ANALYSIS.md, generated from the analysis JSON."""
    pl = gt_doc["players"]
    scen = {"player": next(p["agent"] for p in pl if p["pid"] == gt_doc.get("pov", "p1")),
            "left": [p["agent"] for p in pl if p["team"] == "A"], "right": [p["agent"] for p in pl if p["team"] == "B"]}
    raw, tr = an["accuracy_raw"], an["accuracy_tracked"]
    lines = ["# Sample analysis — 30 s round, VALORANT 2022 Q1 HUD replica", "",
             "_Generated by `tools/make_figures.py` from `samples/sample_2022q1_30s.analysis.json`._", "",
             f"Video: `{an['video']}` ({an['frames']} frames at {an['fps']:.0f} fps, 1280x720). "
             f"Player: **{scen['player']}**. Your team: {', '.join(scen['left'])}. "
             f"Enemies: {', '.join(scen['right'])}.", "",
             "## Accuracy per field", "",
             "Ground truth exists for every frame. *Raw* is the per-frame reading; *tracked* is after the "
             "3-frame vote, which is one frame late at each change.", "",
             "| Field | Raw | Tracked |", "|---|---|---|"]
    for k in raw:
        if k.startswith("_"):
            continue
        lines.append(f"| `{k}` | {raw[k]['accuracy'] * 100:.2f} % | {tr[k]['accuracy'] * 100:.2f} % |")
    lines += [f"| **overall** | **{raw['_overall']['accuracy'] * 100:.2f} %** | **{tr['_overall']['accuracy'] * 100:.2f} %** |", "",
              "## Events detected", "",
              "Scripted time vs. detected time. All events are found; the constant +1 frame (33 ms) is the vote.", "",
              "| Detected at | Event | Details |", "|---|---|---|"]
    for e in an["events"]:
        det = {k: v for k, v in e.items() if k not in ("t", "type")}
        txt = ", ".join(f"{k}={v}" for k, v in det.items())
        lines.append(f"| {e['t']:.2f} s | `{e['type']}` | {txt} |")
    lines += ["", "## Timing on this run", "",
              f"Median per-frame latency {an['latency_ms']['median']} ms (p95 {an['latency_ms']['p95']} ms), "
              f"throughput {an['throughput_fps']} fps including H.264 decode, {an['workers']} worker(s). "
              "Per-detector medians (ms):", "", "| Stage | ms |", "|---|---|"]
    for k, v in an["detector_ms_median"].items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "![Timeline](images/timeline.png)", "",
              "Annotated debug video: `samples/sample_2022q1_30s.annotated.mp4`. Example frame:", "",
              "![Readings](images/readings.jpg)", ""]
    (ROOT / "docs" / "SAMPLE_ANALYSIS.md").write_text("\n".join(lines))


def real_footage(res):
    """Held-out real-frame accuracy: v2 vs the 2022 engine."""
    v2 = res["v2"]["test (45-88)"]
    lg = res.get("legacy_2022", {}).get("test (45-88)", {})
    fields = [k for k in v2 if k != "HUD hidden -> HP null"]
    fig, ax = plt.subplots(figsize=(9.5, 3.4))
    x = np.arange(len(fields))
    w = 0.36
    a = [lg[k]["accuracy"] * 100 if k in lg else 0 for k in fields]
    b = [v2[k]["accuracy"] * 100 for k in fields]
    ax.bar(x - w / 2 - 0.01, a, w, color="#b9b8b2", label="2022 engine (Tesseract)")
    ax.bar(x + w / 2 + 0.01, b, w, color=S1, label="v2 (this repo)")
    for i in range(len(fields)):
        ax.text(x[i] - w / 2, a[i] + 0.6, f"{a[i]:.0f}", ha="center", va="bottom", fontsize=8, color=INK2)
        ax.text(x[i] + w / 2, b[i] + 0.6, f"{b[i]:.0f}", ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_xticks(x, fields, rotation=22, ha="right", fontsize=9)
    ax.set_ylim(60, 104)
    ax.set_ylabel("accuracy (%)")
    ax.grid(axis="x", visible=False)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, fontsize=9.5)
    ax.set_title("Real Jan-Feb 2022 screenshots, held-out split (44 frames)", loc="left", fontsize=12,
                 fontweight="bold", pad=24)
    fig.tight_layout()
    fig.savefig(IMG / "real_footage.png", dpi=160)
    plt.close(fig)


def main():
    bench = json.loads((ROOT / "docs" / "benchmark" / "benchmark.json").read_text())
    rob = json.loads((ROOT / "docs" / "benchmark" / "robustness.json").read_text())
    an = json.loads((ROOT / "samples" / "sample_2022q1_30s.analysis.json").read_text())
    gt_doc = json.loads((ROOT / "samples" / "sample_2022q1_30s.groundtruth.json").read_text())
    gt = gt_doc["frames"]
    latency(bench)
    detectors(bench)
    throughput(bench)
    timeline(an, gt)
    legacy_vs_v2(rob)
    sample_report(an, gt_doc)
    rp = ROOT / "docs" / "real_eval" / "results.json"
    if rp.exists():
        real_footage(json.loads(rp.read_text()))
    rois_and_techniques(ROOT / "samples" / "sample_2022q1_30s.mp4")
    print("figures ->", IMG)


if __name__ == "__main__":
    main()
