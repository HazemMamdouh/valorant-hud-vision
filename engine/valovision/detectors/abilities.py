"""Ability charges (C/Q/E) and ultimate state — calibrated on real 2022 frames.

The 2022 HUD draws each ability's charges as a bar split into one segment per
maximum charge; available charges are **teal**, spent ones grey, an ability in
use turns yellow. The ultimate shows teal diamonds (collected points) and its
bar turns teal when the ult is ready.

Technique: a teal colour gate in BGR (G and B well above R — grey, white and
yellow all fail it), 8-connected components, then:
* charges = components of bar size (height-limited, so teal scenery behind the
  translucent HUD is rejected) with area >= 50 % of the largest one;
* ult ready = a teal component at least ~75 % of the ult box wide;
* ult points = small teal components (diamonds), merged ones split by width.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

import cv2
import numpy as np

from .base import Detector, FrameContext


def teal_mask(roi_bgr: np.ndarray, dmin: int) -> np.ndarray:
    b, g, r = (roi_bgr[:, :, i].astype(np.int16) for i in range(3))
    return ((g - r > dmin) & (b - r > int(dmin * 0.6)) & (g > 110)).astype(np.uint8) * 255


class AbilitiesDetector(Detector):
    name = "abilities"

    def _components(self, roi: np.ndarray) -> np.ndarray:
        m = teal_mask(roi, int(self.t["teal_delta"]))
        n, _, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        return st[1:]

    def count_charges(self, roi_bgr: np.ndarray) -> int:
        st = self._components(roi_bgr)
        if len(st) == 0:
            return 0
        keep = st[(st[:, cv2.CC_STAT_AREA] >= self.t["ability_min_area"]) &
                  (st[:, cv2.CC_STAT_HEIGHT] <= self.t["ability_max_height"]) &
                  (st[:, cv2.CC_STAT_AREA] <= self.t["ability_max_area"])]
        if len(keep) == 0:
            return 0
        a = keep[:, cv2.CC_STAT_AREA]
        return int(np.sum(a >= self.t["ability_rel_area"] * a.max()))

    def read_ult(self, roi_bgr: np.ndarray) -> Tuple[bool, int]:
        st = self._components(roi_bgr)
        if len(st) == 0:
            return False, 0
        w = st[:, cv2.CC_STAT_WIDTH]
        a = st[:, cv2.CC_STAT_AREA]
        ready = bool(np.any((w >= self.t["ult_ready_width_ratio"] * roi_bgr.shape[1]) &
                            (a >= self.t["ult_ready_area"])))
        small = (a >= self.t["ult_dot_min_area"]) & (w < 0.5 * roi_bgr.shape[1])
        points = int(np.sum(np.maximum(1, np.round(w[small] / self.t["ult_dot_pitch"]))))
        return ready, points

    def __call__(self, ctx: FrameContext, agent_key: str | None = None) -> Dict[str, Any]:
        L = self.layout
        ab: Dict[str, int] = {}
        if agent_key == "Reyna":           # Devour/Dismiss share one soul-orb counter
            ab["c"] = self.count_charges(ctx.crop(L.abilities["c"]))
            qe = self.count_charges(ctx.crop(L.abilities["qe"]))
            ab["q"] = ab["e"] = qe
        else:
            for k in ("c", "q", "e"):
                ab[k] = self.count_charges(ctx.crop(L.abilities[k]))
        ready, points = self.read_ult(ctx.crop(L.abilities["x"]))
        maxes = L.ability_charges(agent_key)
        if ready:
            points = maxes["x"]
        return {"abilities": ab, "ult_ready": ready, "ult_points": min(points, maxes["x"]), "ult_max": maxes["x"]}
