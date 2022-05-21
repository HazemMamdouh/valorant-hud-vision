"""The frame pipeline: one frame in, one structured game state out.

Execution modes (``mode``):

* ``"sequential"`` — detectors run one after another on the calling thread.
  Lowest overhead; the right choice when you parallelise *across frames*.
* ``"threaded"`` — detectors run on a **persistent** thread pool. OpenCV
  releases the GIL inside its kernels, so independent ROIs overlap. (The 2022
  engine created and joined 14 brand-new ``threading.Thread`` objects per frame.)

Across-frame parallelism for offline analysis lives in :mod:`valovision.analysis`.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

import cv2
import numpy as np

from .config import Layout, load_layout
from .detectors import (AbilitiesDetector, CurrentAgentDetector, FrameContext, RosterDetector,
                        SpikeDetector, VitalsDetector, WeaponsDetector)
from .registration import HudRegistration
from .templates import AgentBank, DigitBank


class Engine:
    def __init__(self, layout: Layout | str | None = None, mode: str = "sequential",
                 workers: int = 4, roster_every: int = 15, cv_threads: Optional[int] = None,
                 register: Optional[bool] = None):
        self.layout = layout if isinstance(layout, Layout) else load_layout(layout)
        if cv_threads is not None:
            cv2.setNumThreads(cv_threads)
        from .templates import TEMPLATE_DIR
        digit_set = self.layout.raw.get("digit_set", "digits_valorant") if self.layout.raw else "digits_valorant"
        self._agents, self._digits = AgentBank(), DigitBank(TEMPLATE_DIR / digit_set)
        # registration anchors on the bottom-left agent portrait, which only the
        # spectator/observer HUD shows; the player HUD has none -> off by default
        if register is None:
            register = bool(self.layout.raw.get("registration", True)) if self.layout.raw else True
        self._roster_every, self._register = roster_every, register
        self._sets: Dict[tuple, dict] = {}
        self._activate(self._detectors_for(self.layout))
        self.base_layout = self.layout
        self.mode = mode
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="det") if mode == "threaded" else None
        self.frame_index = 0

    # -------------------------------------------------------------------------
    def _detectors_for(self, layout: Layout) -> dict:
        key = layout.base_resolution
        if key not in self._sets:
            self._sets[key] = {
                "layout": layout,
                "current": CurrentAgentDetector(layout, agent_bank=self._agents),
                "roster": RosterDetector(layout, agent_bank=self._agents, identify_every=self._roster_every),
                "vitals": VitalsDetector(layout, digit_bank=self._digits),
                "abilities": AbilitiesDetector(layout),
                "weapons": WeaponsDetector(layout),
                "spike": SpikeDetector(layout),
                "registration": HudRegistration(layout, self._agents) if self._register else None,
            }
        return self._sets[key]

    def _activate(self, d: dict) -> None:
        self.layout = d["layout"]
        self.current, self.roster, self.vitals = d["current"], d["roster"], d["vitals"]
        self.abilities, self.weapons, self.spike = d["abilities"], d["weapons"], d["spike"]
        self.registration = d["registration"]

    def _timed(self, name: str, fn, *args):
        t0 = time.perf_counter()
        r = fn(*args)
        return name, r, (time.perf_counter() - t0) * 1000.0

    def process(self, frame_bgr: np.ndarray, index: Optional[int] = None,
                timestamp: Optional[float] = None) -> Dict[str, Any]:
        t0 = time.perf_counter()
        idx = self.frame_index if index is None else index
        self.frame_index = idx + 1
        ctx = FrameContext(frame_bgr, self.layout, idx)
        _ = ctx.gray                                   # shared grayscale, computed once
        if self.registration is not None:
            ctx.offset = self.registration.update(ctx.gray, idx)
        t_prep = (time.perf_counter() - t0) * 1000.0

        independent = [("current_agent", self.current), ("roster", self.roster), ("vitals", self.vitals),
                       ("weapons", self.weapons), ("spike", self.spike)]
        results: Dict[str, Any] = {}
        timings: Dict[str, float] = {"prepare": round(t_prep, 3)}
        if self.pool is not None:
            futs = [self.pool.submit(self._timed, n, d, ctx) for n, d in independent]
            for f in futs:
                n, r, ms = f.result()
                results[n], timings[n] = r, round(ms, 3)
        else:
            for n, d in independent:
                n, r, ms = self._timed(n, d, ctx)
                results[n], timings[n] = r, round(ms, 3)
        # abilities depend on the agent (Reyna's shared Q/E counter, max charges)
        n, r, ms = self._timed("abilities", self.abilities, ctx, results["current_agent"]["agent_key"])
        results[n], timings[n] = r, round(ms, 3)

        state = self._assemble(results, idx, timestamp)
        state["hud_offset"] = list(ctx.offset)
        state["timing_ms"] = timings
        state["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        return state

    def _assemble(self, r: Dict[str, Any], idx: int, ts: Optional[float]) -> Dict[str, Any]:
        cur, vit, ab = r["current_agent"], r["vitals"], r["abilities"]
        teams = r["roster"]["teams"]
        spike = r["spike"]["spike"]
        for side in ("left", "right"):
            for s in teams[side]:
                s["has_spike"] = spike["carrier_slot"] == s["slot"]
        return {
            "frame": idx,
            "t": None if ts is None else round(ts, 3),
            "layout": self.layout.name,
            "player": {
                "agent": cur["agent"], "agent_key": cur["agent_key"], "agent_conf": cur["agent_conf"],
                "team": cur["team"],
                "hp": vit["hp"], "shield": vit["shield"],
                "abilities": ab["abilities"], "ult_points": ab["ult_points"], "ult_max": ab["ult_max"],
                "ult_ready": ab["ult_ready"],
                "max_charges": self.layout.ability_charges(cur["agent_key"]),
            },
            "loadout": r["weapons"]["loadout"],
            "teams": teams,
            "spike": spike,
            "confidence": {"agent": cur["agent_conf"], "hp": vit["hp_conf"], "shield": vit["shield_conf"],
                           "primary": r["weapons"]["loadout"].get("primary_conf"),
                           "secondary": r["weapons"]["loadout"].get("secondary_conf")},
        }

    def close(self):
        if self.pool is not None:
            self.pool.shutdown(wait=True)
            self.pool = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
