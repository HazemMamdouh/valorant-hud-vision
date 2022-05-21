#!/usr/bin/env python3
"""Build the real-world scenery used behind the replica HUD (synth-match --scenery).

Takes the world view (no HUD) from real January–February 2022 player screenshots
(deepsidh9/Live-Valorant-Overlay, MIT): a window centred on the crosshair that stays clear
of the top bar, minimap, kill feed, right-side HUD column and bottom HUD, at the
screenshot's native resolution. The game's own crosshair is painted out; the renderer
draws its crosshair in the same place.

    python tools/make_scenery.py --real-root real/
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "tools"))

# label index -> one scene per player (clean world view, varied maps, no banner text)
SCENES = [14, 18, 20, 15, 29, 35, 48, 51, 53, 68]
# world window in 1280x720 HUD coordinates, centred on the crosshair (640, 360)
WIN = (334, 188, 946, 532)
OUT_SIZE = (1320, 744)        # a little larger than 1280x720: room for aim sway


def main():
    from eval_real import resolve
    from valovision.detectors.base import normalise_frame
    ap = argparse.ArgumentParser()
    ap.add_argument("--real-root", required=True)
    ap.add_argument("--out", default=str(ROOT / "engine" / "valovision" / "assets" / "scenery_2022"))
    a = ap.parse_args()
    labels = {l["idx"]: l for l in json.loads((ROOT / "docs" / "real_eval" / "real_labels.json").read_text())}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for k, idx in enumerate(SCENES):
        f = normalise_frame(cv2.imread(str(resolve(Path(a.real_root), labels[idx]["file"]))), (1920, 1080))
        x0, y0, x1, y1 = (int(v * 1.5) for v in WIN)
        crop = f[y0:y1, x0:x1].copy()
        cx, cy = 960 - x0, 540 - y0                  # paint out the game's crosshair
        mask = cv2.rectangle(crop[:, :, 0] * 0, (cx - 22, cy - 22), (cx + 22, cy + 22), 255, -1)
        crop = cv2.inpaint(crop, mask, 7, cv2.INPAINT_TELEA)
        crop = cv2.resize(crop, OUT_SIZE, interpolation=cv2.INTER_CUBIC)
        cv2.imwrite(str(out / f"scene_{k + 1:02d}.jpg"), crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
        print(out / f"scene_{k + 1:02d}.jpg", "<-", labels[idx]["file"])
    (out / "ATTRIBUTION.md").write_text(
        "# Scenery\n\nWorld views cropped from real VALORANT player screenshots (January–February 2022) in\n"
        "[deepsidh9/Live-Valorant-Overlay](https://github.com/deepsidh9/Live-Valorant-Overlay) (MIT licence).\n"
        "The HUD is cropped away and the crosshair painted out; built by `tools/make_scenery.py`.\n"
        "VALORANT imagery is © Riot Games, used here for a non-commercial technical demonstration.\n\n"
        + "\n".join(f"- scene_{k + 1:02d}.jpg <- `{labels[i]['file'].split('/', 1)[1]}`" for k, i in enumerate(SCENES))
        + "\n")


if __name__ == "__main__":
    main()
