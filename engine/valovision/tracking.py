"""Temporal layer: debounce per-frame readings and turn state changes into events.

Per-frame classical CV is stateless and occasionally flickers (a muzzle flash
over the HUD, a compression block on a digit). The 2022 engine shipped every
raw frame result. Here each field is filtered by a short majority vote, short
``None`` drop-outs are bridged, and the *stable* state is diffed to emit
semantic events (deaths, plant, ability use, damage, weapon swaps...).
"""
from __future__ import annotations

import copy
from collections import Counter, deque
from typing import Any, Deque, Dict, List, Optional

SPIKE_TIMER_2022 = 45.0   # seconds from plant to detonation (2022)


class Vote:
    def __init__(self, window: int = 3, hold: int = 6):
        self.buf: Deque[Any] = deque(maxlen=window)
        self.hold = hold
        self.misses = 0
        self.value: Any = None

    def update(self, v: Any) -> Any:
        if v is None and self.value is not None and self.misses < self.hold:
            self.misses += 1
            return self.value
        self.misses = 0 if v is not None else self.misses
        self.buf.append(v)
        c = Counter(self.buf).most_common()
        top, n = c[0]
        if n * 2 > len(self.buf) or self.value is None:
            self.value = top
        return self.value


class Tracker:
    SCALARS = [("player", "agent"), ("player", "agent_key"), ("player", "team"), ("player", "hp"),
               ("player", "shield"), ("player", "ult_points"), ("player", "ult_ready"),
               ("loadout", "primary"), ("loadout", "secondary"), ("loadout", "active"),
               ("spike", "planted"), ("spike", "carrier_slot")]

    def __init__(self, window: int = 3, fps: float = 30.0, history: int = 40):
        self.window = window
        self.fps = fps
        self.votes: Dict[str, Vote] = {}
        self.prev: Optional[dict] = None
        self.history: Deque[dict] = deque(maxlen=history)
        self.planted_at: Optional[float] = None
        # last roster where every living portrait was identified, per side
        self.stable_names: Dict[str, List[str]] = {"left": [], "right": []}

    def _vote(self, key: str, v: Any, hold: int = 6) -> Any:
        if key not in self.votes:
            self.votes[key] = Vote(self.window, hold)
        return self.votes[key].update(v)

    def update(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        s = copy.deepcopy(raw)
        t = s["t"] if s.get("t") is not None else s["frame"] / self.fps
        s["t"] = round(t, 3)
        for a, b in self.SCALARS:
            # carrier: no hold — the spike genuinely disappears when dropped
            s[a][b] = self._vote(f"{a}.{b}", s[a][b], hold=0 if b == "carrier_slot" else 6)
        for k in ("c", "q", "e"):
            s["player"]["abilities"][k] = self._vote(f"ab.{k}", s["player"]["abilities"][k])
        for side in ("left", "right"):
            for slot in s["teams"][side]:
                # no per-slot name memory: in the real HUD survivors shift slots
                slot["alive"] = self._vote(f"alive.{slot['slot']}", slot["alive"], hold=0)
                slot["has_spike"] = s["spike"]["carrier_slot"] == slot["slot"]
        # spike timer
        if s["spike"]["planted"]:
            if self.planted_at is None:
                self.planted_at = t
            s["spike"]["timer"] = round(max(0.0, SPIKE_TIMER_2022 - (t - self.planted_at)), 2)
        else:
            self.planted_at = None
            s["spike"]["timer"] = None
        s["alive_count"] = {side: sum(x["alive"] for x in s["teams"][side]) for side in ("left", "right")}
        events = self._diff(self.prev, s, t, self.stable_names) if self.prev else []
        for side in ("left", "right"):
            alive = [x for x in s["teams"][side] if x["alive"]]
            if alive and all(x["agent"] for x in alive):
                self.stable_names[side] = [x["agent"] for x in alive]
        self.history.extend(events)
        s["events"] = events
        s["recent_events"] = list(self.history)[-8:]
        self.prev = s
        return s

    # ------------------------------------------------------------------ events
    @staticmethod
    def _diff(p: dict, s: dict, t: float, stable: Optional[Dict[str, List[str]]] = None) -> List[dict]:
        ev: List[dict] = []

        def add(kind, **kw):
            ev.append({"t": round(t, 2), "type": kind, **kw})

        # Deaths: the real HUD drops a dead player's portrait and packs the
        # survivors, so compare *who* is alive (agent names), not slot flags.
        for side in ("left", "right"):
            before = [x["agent"] for x in p["teams"][side] if x["alive"]]
            after = [x["agent"] for x in s["teams"][side] if x["alive"]]
            if len(after) < len(before):
                ref = (stable or {}).get(side) or before
                gone = [a for a in ref if a and a not in after]
                for i in range(len(before) - len(after)):
                    add("death", side=side, agent=gone[i] if i < len(gone) else None)
            elif len(after) > len(before):
                for a in [a for a in after if a not in before] or [None] * (len(after) - len(before)):
                    add("revive", side=side, agent=a)
        if not p["spike"]["planted"] and s["spike"]["planted"]:
            add("spike_planted")
        if p["spike"]["carrier_slot"] != s["spike"]["carrier_slot"] and not s["spike"]["planted"]:
            if s["spike"]["carrier_slot"] is None:
                add("spike_dropped", slot=p["spike"]["carrier_slot"])
            else:
                add("spike_picked_up", slot=s["spike"]["carrier_slot"])
        pp, sp = p["player"], s["player"]
        for k in ("c", "q", "e"):
            a, b = pp["abilities"][k], sp["abilities"][k]
            if a is not None and b is not None and b < a:
                add("ability_used", key=k.upper(), remaining=b)
        if not pp["ult_ready"] and sp["ult_ready"]:
            add("ult_ready")
        if pp["ult_ready"] and not sp["ult_ready"]:
            add("ult_used")
        elif (pp["ult_points"] is not None and sp["ult_points"] is not None
              and sp["ult_points"] > pp["ult_points"] and not sp["ult_ready"]):
            add("ult_point", points=sp["ult_points"])
        if pp["hp"] is not None and sp["hp"] is not None and sp["hp"] < pp["hp"]:
            dmg = (pp["hp"] - sp["hp"]) + max(0, (pp["shield"] or 0) - (sp["shield"] or 0))
            add("damage", amount=dmg, hp=sp["hp"], shield=sp["shield"])
        if (pp["shield"] or 0) > 0 and sp["shield"] == 0:
            add("shield_broken")
        if p["loadout"]["active"] != s["loadout"]["active"] and s["loadout"]["active"]:
            w = s["loadout"][s["loadout"]["active"]]
            add("weapon_switch", slot=s["loadout"]["active"], weapon=w)
        return ev
