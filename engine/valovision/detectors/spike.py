"""Spike state: planted (red HSV mass in the top-centre icon) and carrier slot.

Carrier: the white spike glyph under a roster portrait — luma > 240 pixel count
per cell. The 2022 version flipped the whole 1280x720 frame to read the right
team; here the right-team cells are mirrored *rects*, so nothing is copied.
"""
from __future__ import annotations

from typing import Any, Dict

import cv2
import numpy as np

from ..templates import TEMPLATE_DIR
from .base import Detector, FrameContext

_RED1 = (np.array([0, 100, 20], np.uint8), np.array([10, 255, 255], np.uint8))
_RED2 = (np.array([160, 100, 20], np.uint8), np.array([179, 255, 255], np.uint8))


class SpikeDetector(Detector):
    """Planted: red mass in the spike box *including its lower tip*.

    The real 2022 planted icon is a hollow red inverted triangle (25-55 % of the
    box is red, so the 2022 ">50 % red" rule missed most plants), while the red
    last-seconds round timer ("13.89") is red but never reaches the tip.

    Carrier: the spike icon (white triangle, yellow ring) drawn under a roster
    portrait, found by normalised cross-correlation in each carrier cell; the
    best cell wins if it clears the threshold.
    """

    name = "spike"

    def __init__(self, layout, **kw):
        super().__init__(layout)
        self.cells = [(1 + i, r) for i, r in enumerate(layout.carrier_cell_rects("left"))] + \
                     [(6 + i, r) for i, r in enumerate(layout.carrier_cell_rects("right"))]
        tpl = cv2.imread(str(TEMPLATE_DIR / "hud" / "spike_carrier.png"), cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            raise FileNotFoundError("hud/spike_carrier.png")
        self.carrier_tpl = tpl

    def __call__(self, ctx: FrameContext) -> Dict[str, Any]:
        hsv = cv2.cvtColor(ctx.crop(self.layout.spike), cv2.COLOR_BGR2HSV)
        red = cv2.inRange(hsv, *_RED1) | cv2.inRange(hsv, *_RED2)
        H, W = red.shape
        red_ratio = cv2.countNonZero(red) / red.size
        tip = red[int(H * 0.62):int(H * 0.9), int(W * 0.38):int(W * 0.62)]
        tip_ratio = float(np.count_nonzero(tip)) / max(1, tip.size)
        planted = red_ratio >= self.t["spike_red_ratio"] and tip_ratio >= self.t["spike_tip_ratio"]
        carrier, best = None, -1.0
        if not planted:
            th, tw = self.carrier_tpl.shape
            for slot, (x0, y0, x1, y1) in self.cells:
                g = ctx.crop((x0, y0 - 2, x1, y1 + 2), gray=True)
                if g.shape[0] < th or g.shape[1] < tw:
                    continue
                s = float(cv2.matchTemplate(g, self.carrier_tpl, cv2.TM_CCOEFF_NORMED).max())
                if s > best:
                    carrier, best = slot, s
            if best < self.t["carrier_match"]:
                carrier = None
        return {"spike": {"planted": bool(planted), "carrier_slot": carrier, "red_ratio": round(red_ratio, 3),
                          "tip_ratio": round(tip_ratio, 3), "carrier_score": round(best, 3)}}
