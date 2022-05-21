"""Current agent, team colour, roster identities and alive/dead state.

Techniques (unchanged family from 2022):
* masked normalised cross-correlation (``cv2.matchTemplate`` + alpha mask)
  against 18 agent portraits (the Q1-2022 roster, Astra -> Neon);
* BGR ``inRange`` colour gating for the team tint behind the portrait;
* horizontal Sobel edge energy per roster slot — live portraits are detailed,
  dead portraits are greyed-out and almost flat.
"""
from __future__ import annotations

from typing import Any, Dict, List

import cv2
import numpy as np

from ..templates import AgentBank, display_name
from .base import Detector, FrameContext


class CurrentAgentDetector(Detector):
    name = "current_agent"

    def __init__(self, layout, agent_bank: AgentBank, **kw):
        super().__init__(layout)
        self.bank = agent_bank
        self.lo = np.array(self.t["team_color_bgr_lo"], np.uint8)
        self.hi = np.array(self.t["team_color_bgr_hi"], np.uint8)

    def __call__(self, ctx: FrameContext) -> Dict[str, Any]:
        crop = ctx.crop(self.layout.current_agent)
        h, w = crop.shape[:2]
        tint = cv2.inRange(crop, self.lo, self.hi)
        ally = int(cv2.countNonZero(tint)) > h * w * self.t["team_color_ratio"]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        name, score, _ = self.bank.match(gray)
        ok = score > self.t["agent_match"]
        return {"agent": display_name(name) if ok else None, "agent_key": name if ok else None,
                "agent_conf": round(score, 3), "team": "ally" if ally else "enemy"}


class RosterDetector(Detector):
    """Who is alive on each team, and which agent sits in each top-bar slot.

    Real 2022 HUD behaviour (verified on January 2022 screenshots):
    * a dead player's portrait disappears and the survivors **pack towards the
      centre** of the bar, so a slot is a position, not a player;
    * every living player has a health bar under the portrait (white for your
      team, grey for enemies).

    Alive = strong horizontal edge energy (Sobel dx, as in 2022), or moderate
    energy **plus** a visible health-bar band; empty slots over textured scenery
    have edges but no bar. Identities are re-matched whenever the alive pattern
    changes (and on key-frames), because packing moves players between slots.
    """

    name = "roster"

    def __init__(self, layout, agent_bank: AgentBank, identify_every: int = 15, **kw):
        super().__init__(layout)
        self.bank = agent_bank
        self.identify_every = identify_every
        self.rects = {"left": layout.roster_slot_rects("left"), "right": layout.roster_slot_rects("right")}
        self._names: Dict[int, str] = {}
        self._pattern: tuple = ()

    @staticmethod
    def _edge_energy(gray: np.ndarray) -> float:
        sob = cv2.Sobel(gray, cv2.CV_8U, 1, 0, ksize=3)       # same operator as 2022
        return float(sob.sum()) / 255.0

    def _bar_fraction(self, ctx: FrameContext, r) -> float:
        """Share of columns where the health-bar band is brighter than both neighbours."""
        x0, _, x1, y1 = r
        dx, dy = ctx.offset
        g = ctx.gray
        xs = slice(max(0, x0 + dx + 2), x1 + dx - 2)
        yb = y1 + dy
        bar = g[yb + 4:yb + 8, xs].astype(np.float32).mean(0)
        above = g[yb:yb + 2, xs].astype(np.float32).mean(0)
        below = g[yb + 10:yb + 14, xs].astype(np.float32).mean(0)
        c = np.minimum(bar - below, bar - above)
        return float((c > self.t["alive_bar_contrast"]).mean()) if c.size else 0.0

    def __call__(self, ctx: FrameContext) -> Dict[str, Any]:
        t = self.t
        raw = []
        for side in ("left", "right"):
            for r in self.rects[side]:
                g = ctx.crop(r, gray=True)
                e = self._edge_energy(g)
                bar = self._bar_fraction(ctx, r)
                alive = e > t["alive_edge_strong"] or (e > t["alive_edge_energy"] and bar >= t["alive_bar_frac"])
                raw.append((side, r, g, e, bar, alive))
        pattern = tuple(x[5] for x in raw)
        identify = pattern != self._pattern or ctx.index % self.identify_every == 0
        self._pattern = pattern
        out: Dict[str, List[Dict[str, Any]]] = {"left": [], "right": []}
        for i, (side, r, g, e, bar, alive) in enumerate(raw):
            slot = i + 1
            if not alive:
                self._names.pop(slot, None)
            elif identify:
                n1, s1, _ = self.bank.match(g)
                n2, s2, _ = self.bank.match(cv2.flip(g, 1))
                name, score = (n1, s1) if s1 >= s2 else (n2, s2)
                if score > t["roster_match"]:
                    self._names[slot] = name
                else:
                    self._names.pop(slot, None)
            out[side].append({"slot": slot, "agent": display_name(self._names.get(slot)) if alive else None,
                              "alive": bool(alive), "edge_energy": round(e, 1), "bar": round(bar, 2)})
        return {"teams": out}

    def reset(self):
        self._names.clear()
        self._pattern = ()
