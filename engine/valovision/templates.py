"""Template banks (agents, weapons, digits) — loaded once, pre-processed once.

Improvements over the 2022 engine:
* weapon binaries are built from the PNG **alpha channel** (the old code used
  imread(..., 0), which drops alpha; on some icons transparent pixels carry
  grey RGB and leaked into the template — e.g. 54% "on" pixels vs 31% real
  silhouette for the Vandal icon);
* weapon templates are resized/padded to the ROI size **once at start-up**,
  not 18 times per frame;
* the agent bank is shared by the current-agent and roster detectors.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np

from .config import ASSET_DIR

TEMPLATE_DIR = ASSET_DIR / "templates"
AGENT_SIZE = 55  # templates and crops are compared at 55x55, as in 2022

DISPLAY_NAMES = {"KAYO": "KAY/O", "GoldenGun": "Golden Gun"}


def display_name(key: str | None) -> str | None:
    if key is None:
        return None
    return DISPLAY_NAMES.get(key, key)


def _read_rgba(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(path)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    if img.shape[2] == 3:
        img = np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
    return img


@dataclass
class AgentTemplate:
    name: str
    gray: np.ndarray      # 55x55 uint8
    mask: np.ndarray      # 55x55 uint8 (0/255) from alpha
    bgra: np.ndarray      # 55x55 BGRA (for rendering / synthetic data)


class AgentBank:
    def __init__(self, folder: Path = TEMPLATE_DIR / "agents", size: int = AGENT_SIZE):
        self.size = size
        self.templates: List[AgentTemplate] = []
        for p in sorted(folder.glob("*_icon.png")):
            rgba = cv2.resize(_read_rgba(p), (size, size), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_BGR2GRAY)
            mask = np.where(rgba[:, :, 3] > 0, 255, 0).astype(np.uint8)
            self.templates.append(AgentTemplate(p.name.split("_icon")[0], gray, mask, rgba))
        if not self.templates:
            raise RuntimeError(f"no agent templates in {folder}")
        self.names = [t.name for t in self.templates]
        # Vectorised masked NCC. Crop and template are the same size, so
        # TM_CCOEFF_NORMED with a mask collapses to a masked Pearson correlation:
        #   score_i = <M_i(c - mu_i), M_i(t_i - nu_i)> / (||M_i(c - mu_i)|| ||M_i(t_i - nu_i)||)
        # Pre-computing the template side turns 18 matchTemplate calls into
        # three (18 x 3025) mat-vec products.
        M = np.stack([(t.mask > 0).reshape(-1) for t in self.templates]).astype(np.float32)
        T = np.stack([t.gray.reshape(-1) for t in self.templates]).astype(np.float32)
        self._M = M
        self._Mn = M.sum(1)
        Tc = (T - (T * M).sum(1, keepdims=True) / self._Mn[:, None]) * M
        self._T = Tc / (np.linalg.norm(Tc, axis=1, keepdims=True) + 1e-6)

    def match(self, gray_crop: np.ndarray) -> Tuple[str | None, float, np.ndarray]:
        """Best masked-NCC match. Returns (name, score, all_scores).

        The 2022 code returned the *last* template whose score was > 0.5; here
        we take the arg-max and report its score as a confidence.
        """
        if gray_crop.shape != (self.size, self.size):
            gray_crop = cv2.resize(gray_crop, (self.size, self.size), interpolation=cv2.INTER_AREA)
        c = gray_crop.reshape(-1).astype(np.float32)
        mu = (self._M @ c) / self._Mn                       # masked mean per template
        num = self._T @ c                                    # T is zero-mean inside its mask
        var = (self._M @ (c * c)) - self._Mn * mu * mu
        # a (near-)flat crop has no correlation: OpenCV returns NaN there, so
        # score it 0 instead of dividing by ~0 (real frames: empty HUD boxes)
        flat = var < self._Mn * 1.0          # masked std-dev below 1 grey level
        scores = np.where(flat, 0.0, num / np.sqrt(np.maximum(var, 1e-6)))
        best = int(np.argmax(scores))
        return self.names[best], float(scores[best]), scores

    def match_opencv(self, gray_crop: np.ndarray) -> Tuple[str | None, float, np.ndarray]:
        """Reference implementation with cv2.matchTemplate (used by the tests)."""
        if gray_crop.shape != (self.size, self.size):
            gray_crop = cv2.resize(gray_crop, (self.size, self.size), interpolation=cv2.INTER_AREA)
        scores = np.empty(len(self.templates), np.float32)
        for i, t in enumerate(self.templates):
            r = cv2.matchTemplate(gray_crop, t.gray, cv2.TM_CCOEFF_NORMED, mask=t.mask)
            v = float(r[0, 0])
            scores[i] = v if np.isfinite(v) else -1.0
        best = int(np.argmax(scores))
        return self.names[best], float(scores[best]), scores


@dataclass
class WeaponTemplate:
    name: str
    alpha: np.ndarray       # original-resolution alpha (silhouette)
    fitted: np.ndarray      # binary template resized + left-padded to the ROI


def resize_and_pad(img: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    """Aspect-preserving fit into (target_h, target_w), right-aligned, vertically centred.

    The HUD right-aligns weapon icons. The 2022 version scaled to full height and,
    when the icon came out wider than the slot, *squashed* it to the slot width,
    which distorted long guns (Ares/Marshal/Operator). Here we shrink to fit.
    """
    h, w = img.shape[:2]
    s = min(target_h / h, target_w / w)
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    r = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    out = np.zeros((target_h, target_w), img.dtype)
    y0 = (target_h - nh) // 2
    out[y0:y0 + nh, target_w - nw:] = r
    return out


class WeaponBank:
    def __init__(self, folder: Path, roi_hw: Tuple[int, int]):
        self.templates: List[WeaponTemplate] = []
        h, w = roi_hw
        for p in sorted(folder.glob("*_killfeed.png")):
            rgba = _read_rgba(p)
            alpha = np.where(rgba[:, :, 3] > 127, 255, 0).astype(np.uint8)
            ys, xs = np.nonzero(alpha)
            alpha = alpha[ys.min():ys.max() + 1, xs.min():xs.max() + 1]   # tight crop
            fitted = resize_and_pad(alpha, h, w)
            fitted = np.where(fitted > 127, 255, 0).astype(np.uint8)
            self.templates.append(WeaponTemplate(p.name.split("_killfeed")[0], alpha, fitted))
        self.names = [t.name for t in self.templates]
        # same-size TM_CCOEFF_NORMED == Pearson correlation -> one mat-vec product
        F = np.stack([t.fitted.reshape(-1) for t in self.templates]).astype(np.float32)
        F -= F.mean(1, keepdims=True)
        self._F = F / (np.linalg.norm(F, axis=1, keepdims=True) + 1e-6)

    def match(self, binary_roi: np.ndarray) -> Tuple[str | None, float]:
        v = binary_roi.reshape(-1).astype(np.float32)
        v -= v.mean()
        n = np.linalg.norm(v)
        if n < 1e-6:
            return None, 0.0
        s = (self._F @ v) / n
        i = int(np.argmax(s))
        return self.names[i], float(s[i])

    def match_opencv(self, binary_roi: np.ndarray) -> Tuple[str | None, float]:
        best, best_s = None, -1.0
        for t in self.templates:
            s = float(cv2.matchTemplate(binary_roi, t.fitted, cv2.TM_CCOEFF_NORMED)[0, 0])
            if np.isfinite(s) and s > best_s:
                best, best_s = t.name, s
        return best, best_s


class DigitBank:
    """Glyph templates 0-9 used by :mod:`valovision.ocr`."""

    GLYPH_W, GLYPH_H = 12, 18

    def __init__(self, folder: Path = TEMPLATE_DIR / "digits_valorant"):
        self.glyphs: Dict[str, np.ndarray] = {}
        for d in range(10):
            p = folder / f"{d}.png"
            if p.exists():
                g = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
                self.glyphs[str(d)] = self.normalise(g > 127)
        if len(self.glyphs) != 10:
            raise RuntimeError(f"digit templates missing in {folder} — run `valovision make-digits`")
        self.keys = list(self.glyphs)
        self.stack = np.stack([self.glyphs[k] for k in self.keys]).reshape(10, -1)
        self.stack = self.stack - self.stack.mean(1, keepdims=True)
        self.norms = np.linalg.norm(self.stack, axis=1) + 1e-6

    @classmethod
    def normalise(cls, binary: np.ndarray) -> np.ndarray:
        """Tight-crop a binary glyph and fit it into a fixed GLYPH_W x GLYPH_H box (aspect kept)."""
        ys, xs = np.nonzero(binary)
        if len(xs) == 0:
            return np.zeros((cls.GLYPH_H, cls.GLYPH_W), np.float32)
        g = binary[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8) * 255
        h, w = g.shape
        scale = min(cls.GLYPH_H / h, cls.GLYPH_W / w)
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        g = cv2.resize(g, (nw, nh), interpolation=cv2.INTER_AREA)
        out = np.zeros((cls.GLYPH_H, cls.GLYPH_W), np.uint8)
        x0 = (cls.GLYPH_W - nw) // 2
        out[:nh, x0:x0 + nw] = g          # top-aligned (digits share a cap-height)
        return out.astype(np.float32) / 255.0

    @classmethod
    def normalise_gray(cls, patch: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """Like :meth:`normalise` but keeps grey levels (values in 0..1)."""
        ys, xs = np.nonzero(mask)
        if len(xs) == 0:
            return np.zeros((cls.GLYPH_H, cls.GLYPH_W), np.float32)
        g = patch[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float32)
        h, w = g.shape
        scale = min(cls.GLYPH_H / h, cls.GLYPH_W / w)
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        g = cv2.resize(g, (nw, nh), interpolation=cv2.INTER_AREA)
        out = np.zeros((cls.GLYPH_H, cls.GLYPH_W), np.float32)
        x0 = (cls.GLYPH_W - nw) // 2
        out[:nh, x0:x0 + nw] = g
        return out

    def classify(self, glyph: np.ndarray) -> Tuple[str, float]:
        v = glyph.reshape(-1) - glyph.mean()
        scores = (self.stack @ v) / (self.norms * (np.linalg.norm(v) + 1e-6))
        i = int(np.argmax(scores))
        return self.keys[i], float(scores[i])
