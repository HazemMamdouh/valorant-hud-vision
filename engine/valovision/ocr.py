"""Template-matching digit reader (replaces Tesseract).

The 2022 engine called ``pytesseract.image_to_string`` twice per frame. Since
Tesseract 4 the default engine is an LSTM network, i.e. a learned model, and
each call costs tens of milliseconds because it spawns a process and writes
temporary images. This reader is pure classical CV:

1. binarise the ROI with a fixed luma threshold (HUD digits are near-white);
2. split into glyphs with 8-connected components (stats only, no per-label masks);
3. merge fragments that overlap horizontally, split blobs that are too wide
   (touching digits) into equal-width parts;
4. normalise each glyph into a 12x18 box and pick the digit whose template has
   the highest zero-mean normalised cross-correlation (cosine similarity).
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import cv2
import numpy as np

from .templates import DigitBank


def _segments(binary: np.ndarray) -> List[Tuple[int, int, int, int]]:
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    boxes = [tuple(stats[i, :4]) for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 3]
    if not boxes:
        return []
    max_h = max(b[3] for b in boxes)
    boxes = [b for b in boxes if b[3] >= 0.5 * max_h]
    boxes.sort(key=lambda b: b[0])
    merged: List[List[int]] = []
    for x, y, w, h in boxes:                      # merge horizontally-overlapping fragments
        if merged and x < merged[-1][0] + merged[-1][2] - 1:
            mx, my, mw, mh = merged[-1]
            nx0, ny0 = min(mx, x), min(my, y)
            nx1, ny1 = max(mx + mw, x + w), max(my + mh, y + h)
            merged[-1] = [nx0, ny0, nx1 - nx0, ny1 - ny0]
        else:
            merged.append([x, y, w, h])
    out = []
    for x, y, w, h in merged:                     # split touching glyphs
        expected = max(2.0, 0.62 * h)
        k = int(round(w / expected)) if w > 1.35 * expected else 1
        k = max(1, min(k, 3))
        step = w / k
        for i in range(k):
            out.append((int(round(x + i * step)), y, int(round(step)), h))
    return out


def read_number(gray_roi: np.ndarray, bank: DigitBank, luma: int = 110, rel: float = 0.72,
                max_digits: int = 3) -> Tuple[Optional[int], float]:
    """Return (value, confidence). ``value`` is None when no digits are visible.

    * ROIs shorter than 24 px (the shield counter is ~11 px) are upscaled x3
      (bicubic) first so segmentation and glyph shape survive blur/downscaling;
    * the gate is relative to the brightest pixel (``rel * max``, floored at
      ``luma``) so it follows exposure and blur instead of a fixed 160;
    * glyphs are compared as contrast-normalised **grey** patches, not binary
      blobs, which keeps antialiasing information on tiny text.
    """
    g = gray_roi
    if g.shape[0] < 24:
        g = cv2.resize(g, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    peak = float(g.max())
    thr = max(luma, rel * peak)
    if peak <= luma:
        return None, 0.0
    binary = np.where(g > thr, 255, 0).astype(np.uint8)
    segs = _segments(binary)
    if not segs or len(segs) > max_digits:
        return None, 0.0
    lo = 0.5 * thr
    norm = np.clip((g.astype(np.float32) - lo) / max(1.0, peak - lo), 0, 1)
    digits, scores = [], []
    for x, y, w, h in segs:
        glyph = DigitBank.normalise_gray(norm[y:y + h, x:x + w], binary[y:y + h, x:x + w] > 0)
        d, sc = bank.classify(glyph)
        digits.append(d)
        scores.append(sc)
    return int("".join(digits)), float(min(scores))
