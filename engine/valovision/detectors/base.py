from __future__ import annotations

from typing import Any, Dict

import cv2
import numpy as np

from ..config import Layout, Rect


def normalise_frame(bgr: np.ndarray, size) -> np.ndarray:
    """Bring any frame into the layout's 1280x720 design space.

    VALORANT scales its HUD to the screen *height* and centres it. So for any
    aspect ratio: resize to 720 px tall, then centre-pad (16:10, 4:3 ...) or
    centre-crop (21:9) to 1280 px wide. 16:9 frames are just resized.
    """
    W, H = size
    h, w = bgr.shape[:2]
    if (w, h) == (W, H):
        return bgr
    # INTER_AREA is the right filter for big reductions (1080p -> 720p and up)
    # but ~10x slower than bilinear at non-integer factors close to 1
    interp = cv2.INTER_AREA if h >= 1.4 * H else cv2.INTER_LINEAR
    if abs(w / h - W / H) < 0.01:
        return cv2.resize(bgr, (W, H), interpolation=interp)
    nw = int(round(w * H / h))
    r = cv2.resize(bgr, (nw, H), interpolation=interp)
    if nw < W:
        pad = W - nw
        return cv2.copyMakeBorder(r, 0, 0, pad // 2, pad - pad // 2, cv2.BORDER_CONSTANT, value=0)
    x0 = (nw - W) // 2
    return r[:, x0:x0 + W]


class FrameContext:
    """One frame, resized once, with lazily computed shared views."""

    __slots__ = ("bgr", "_gray", "layout", "index", "offset")

    def __init__(self, bgr: np.ndarray, layout: Layout, index: int = 0):
        bgr = normalise_frame(bgr, layout.base_resolution)
        self.bgr = bgr
        self._gray = None
        self.layout = layout
        self.index = index
        self.offset = (0, 0)          # global HUD displacement from registration

    @property
    def gray(self) -> np.ndarray:
        if self._gray is None:
            self._gray = cv2.cvtColor(self.bgr, cv2.COLOR_BGR2GRAY)
        return self._gray

    def crop(self, r: Rect, gray: bool = False, pad: int = 0) -> np.ndarray:
        dx, dy = self.offset
        x0, y0, x1, y1 = r[0] + dx - pad, r[1] + dy - pad, r[2] + dx + pad, r[3] + dy + pad
        src = self.gray if gray else self.bgr
        return src[max(0, y0):y1, max(0, x0):x1]


def otsu(gray: np.ndarray) -> float:
    """Otsu threshold of a small ROI (used to adapt fixed luma gates to exposure)."""
    return float(cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0])


class Detector:
    """A detector reads one HUD element and returns a partial state dict."""

    name = "detector"

    def __init__(self, layout: Layout, **_: Any):
        self.layout = layout
        self.t = layout.thresholds

    def __call__(self, ctx: FrameContext) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError
