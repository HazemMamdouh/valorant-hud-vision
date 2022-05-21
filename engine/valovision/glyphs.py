"""Text rendering helpers + digit-template generation (Pillow).

Runtime detection does **not** need Pillow; it is only used to (re)build the
digit templates from a font and to draw the synthetic HUD.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Tuple

import cv2
import numpy as np

from .config import ASSET_DIR

FONT_HUD = ASSET_DIR / "fonts" / "DejaVuSansCondensed-Bold.ttf"
FONT_UI = ASSET_DIR / "fonts" / "DejaVuSans-Bold.ttf"


@lru_cache(maxsize=64)
def _font(path: str, size: int):
    from PIL import ImageFont
    return ImageFont.truetype(path, size)


def text_mask(text: str, size: int, font: Path = FONT_HUD) -> np.ndarray:
    """Antialiased single-channel mask tightly cropped to the ink."""
    from PIL import Image, ImageDraw
    f = _font(str(font), size)
    l, t, r, b = f.getbbox(text)
    img = Image.new("L", (r - l + 4, b - t + 4), 0)
    ImageDraw.Draw(img).text((2 - l, 2 - t), text, font=f, fill=255)
    m = np.array(img)
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return np.zeros((1, 1), np.uint8)
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def blit_mask(frame: np.ndarray, mask: np.ndarray, x: int, y: int, color: Tuple[int, int, int],
              alpha: float = 1.0) -> None:
    """Alpha-composite a solid colour through ``mask`` at top-left (x, y), clipped to the frame."""
    H, W = frame.shape[:2]
    h, w = mask.shape
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x0 >= x1 or y0 >= y1:
        return
    m = mask[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32)[..., None] / 255.0 * alpha
    roi = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = (roi * (1 - m) + np.array(color, np.float32) * m).astype(np.uint8)


def draw_text(frame, text, x, y, size, color, anchor="lt", font: Path = FONT_HUD, alpha=1.0):
    """anchor: two letters, horizontal (l/m/r) + vertical (t/m/b), on the ink box."""
    m = text_mask(text, size, font)
    h, w = m.shape
    if anchor[0] == "m":
        x -= w // 2
    elif anchor[0] == "r":
        x -= w
    if anchor[1] == "m":
        y -= h // 2
    elif anchor[1] == "b":
        y -= h
    blit_mask(frame, m, x, y, color, alpha)
    return w, h


def make_digit_templates(out_dir: Path | None = None, font: Path = FONT_HUD, size: int = 64) -> Path:
    out_dir = Path(out_dir or ASSET_DIR / "templates" / "digits")
    out_dir.mkdir(parents=True, exist_ok=True)
    for d in range(10):
        m = text_mask(str(d), size, font)
        cv2.imwrite(str(out_dir / f"{d}.png"), np.where(m > 127, 255, 0).astype(np.uint8))
    return out_dir


def extract_digit_templates(frame_path: Path, rect, digits: str, out_dir: Path, luma: int = 160) -> Path:
    """Cut glyph templates out of a *real* screenshot (e.g. HP showing "100" + shield "50").

    Use this to adapt the reader to the true in-game font: grab screenshots
    that together show all ten digits and call this once per ROI.
    """
    from .ocr import _segments
    img = cv2.imread(str(frame_path))
    x0, y0, x1, y1 = rect
    g = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    b = np.where(g > luma, 255, 0).astype(np.uint8)
    segs = _segments(b)
    if len(segs) != len(digits):
        raise ValueError(f"found {len(segs)} glyphs but {len(digits)} labels")
    out_dir.mkdir(parents=True, exist_ok=True)
    for (x, y, w, h), d in zip(segs, digits):
        cv2.imwrite(str(out_dir / f"{d}.png"), b[y:y + h, x:x + w])
    return out_dir
