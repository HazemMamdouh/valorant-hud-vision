"""Global HUD registration (translation only).

Every ROI in the layout is rigid, so a HUD that sits a few pixels away from
where the layout expects it (capture cropping, overscan, a 1366x768 monitor
scaled to 720p...) breaks every detector at once. The current-agent portrait is
a strong, always-visible anchor: search it inside a padded window with masked
NCC against the agent bank and treat the best displacement as the HUD offset.
Runs on key-frames only and is median-filtered, so its cost is amortised.
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Tuple

import cv2
import numpy as np

from .config import Layout
from .templates import AgentBank


class HudRegistration:
    def __init__(self, layout: Layout, bank: AgentBank, radius: int = 6, every: int = 30, min_score: float = 0.6):
        self.L, self.bank = layout, bank
        self.radius, self.every, self.min_score = radius, every, min_score
        self.history: Deque[Tuple[int, int]] = deque(maxlen=3)
        self.offset: Tuple[int, int] = (0, 0)
        self.score = 0.0
        self._last_agent: int | None = None

    def estimate(self, gray: np.ndarray) -> Tuple[Tuple[int, int], float]:
        x0, y0, x1, y1 = self.L.current_agent
        r = self.radius
        H, W = gray.shape
        X0, Y0, X1, Y1 = max(0, x0 - r), max(0, y0 - r), min(W, x1 + r), min(H, y1 + r)
        win = gray[Y0:Y1, X0:X1]
        sz = self.bank.size
        if (x1 - x0, y1 - y0) != (sz, sz):     # layout portrait size differs from bank size
            s = sz / (x1 - x0)
            win = cv2.resize(win, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        else:
            s = 1.0
        order = range(len(self.bank.templates))
        if self._last_agent is not None:        # try the last winner first, stop early if it is confident
            order = [self._last_agent] + [i for i in order if i != self._last_agent]
        best = (-1.0, (0, 0), None)
        for i in order:
            t = self.bank.templates[i]
            res = cv2.matchTemplate(win, t.gray, cv2.TM_CCOEFF_NORMED, mask=t.mask)
            res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
            _, v, _, loc = cv2.minMaxLoc(res)
            if v > best[0]:
                best = (v, loc, i)
            if i == self._last_agent and v > 0.85:
                break
        v, (lx, ly), i = best
        self._last_agent = i
        dx = int(round(lx / s)) + X0 - x0
        dy = int(round(ly / s)) + Y0 - y0
        return (dx, dy), float(v)

    def update(self, gray: np.ndarray, index: int) -> Tuple[int, int]:
        if index % self.every == 0 or not self.history:
            off, score = self.estimate(gray)
            self.score = score
            if score >= self.min_score:
                self.history.append(off)
                xs = sorted(o[0] for o in self.history)
                ys = sorted(o[1] for o in self.history)
                self.offset = (xs[len(xs) // 2], ys[len(ys) // 2])
        return self.offset
