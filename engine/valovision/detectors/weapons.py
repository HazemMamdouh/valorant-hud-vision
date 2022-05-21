"""Loadout: primary + secondary weapon and which one is equipped.

* binarise each slot (luma 120 for primary / 160 for secondary, as in 2022);
* match against right-aligned kill-feed silhouettes with TM_CCOEFF_NORMED;
* new: the equipped weapon is the slot whose silhouette is brightest
  (the HUD dims holstered weapons).
"""
from __future__ import annotations

from typing import Any, Dict

import cv2
import numpy as np

from ..templates import TEMPLATE_DIR, WeaponBank, display_name
from .base import Detector, FrameContext, otsu


class WeaponsDetector(Detector):
    name = "weapons"

    def __init__(self, layout, **kw):
        super().__init__(layout)
        self.slots = {"primary": layout.weapons["primary"], "secondary": layout.weapons["secondary"]}
        self.banks = {}
        for slot, folder in (("primary", "mainarms"), ("secondary", "sidearms")):
            x0, y0, x1, y1 = self.slots[slot]
            self.banks[slot] = WeaponBank(TEMPLATE_DIR / folder, (y1 - y0, x1 - x0))
        self.luma = {"primary": self.t["weapon_primary_luma"], "secondary": self.t["weapon_secondary_luma"]}

    def __call__(self, ctx: FrameContext) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        brightness = {}
        for slot, r in self.slots.items():
            g = ctx.crop(r, gray=True)
            if g.shape != (r[3] - r[1], r[2] - r[0]):
                g = cv2.resize(g, (r[2] - r[0], r[3] - r[1]))
            # 2022 used a fixed gate (120 / 160). Icon vs. translucent panel is
            # bimodal, so Otsu adapts to exposure; an empty slot has no contrast.
            if int(g.max()) - int(np.median(g)) < 60:
                out[slot], out[f"{slot}_conf"] = None, 0.0
                continue
            thr = min(200.0, max(90.0, otsu(g)))
            mask = g > thr
            fill = float(mask.mean())
            if fill == 0.0 or fill > self.t["weapon_max_fill"]:
                out[slot] = None
                out[f"{slot}_conf"] = 0.0
                continue
            b = mask.astype(np.uint8) * 255
            name, score = self.banks[slot].match(b)
            ok = score > self.t["weapon_min_score"]
            out[slot] = display_name(name) if ok else None
            out[f"{slot}_conf"] = round(score, 3)
            if ok:
                brightness[slot] = float(g[mask].mean())
        active = None
        if brightness:
            active = max(brightness, key=brightness.get)
            if len(brightness) == 2 and abs(brightness["primary"] - brightness["secondary"]) < 12:
                active = None
        out["active"] = active
        return {"loadout": out}
