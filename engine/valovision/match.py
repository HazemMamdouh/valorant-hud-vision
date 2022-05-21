"""Match fusion: ten per-player screen states -> one match state.

Every player PC streams its own screen. Each screen is read independently by
the engine (one Engine + Tracker per player). This module merges the ten
readings into one consistent picture for the commentator:

* **Own-screen fields are authoritative only while the player is alive.** HP,
  shield, ability charges, ult and loadout come from that player's own feed.
  After death the screen shows a *spectated teammate's* HUD, so the player's
  values freeze (HP 0) instead of being overwritten.
* **Shared fields are voted.** Every screen shows both rosters and the spike
  icon. Alive counts use the median over fresh views; an agent is alive if a
  majority of views that identified that team list them; planted is a majority.
* Roster sides are relative (left = the viewer's own team) and are mapped to
  absolute teams A/B with the viewer's registered team.
* Who is a player? The engine cannot see "which portrait is me" in the player
  HUD, so each sender registers ``name``, ``team`` and ``agent`` (from the
  lobby). Agent identities from the top bar then link portraits to players.
"""
from __future__ import annotations

import copy
import statistics
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

SPIKE_FUSE = 45.0
FRESH_S = 1.5        # a view older than this is ignored in votes


@dataclass
class PlayerInfo:
    pid: str
    name: str
    team: str                 # "A" | "B"
    agent: Optional[str] = None


@dataclass
class PlayerView:
    info: PlayerInfo
    state: Optional[dict] = None          # latest tracked engine state of this player's screen
    updated: float = 0.0                  # server clock (s)
    frozen: Dict[str, Any] = field(default_factory=dict)   # last values while alive


def _other(team: str) -> str:
    return "B" if team == "A" else "A"


class MatchFusion:
    def __init__(self, history: int = 60):
        self.views: Dict[str, PlayerView] = {}
        self.prev: Optional[dict] = None
        self.planted_at: Optional[float] = None
        self.events: Deque[dict] = deque(maxlen=history)
        self.t0 = time.time()

    # ------------------------------------------------------------------ input
    def register(self, info: PlayerInfo) -> None:
        v = self.views.get(info.pid)
        if v is None:
            self.views[info.pid] = PlayerView(info)
        else:
            v.info = info

    def update(self, pid: str, state: dict, now: Optional[float] = None) -> None:
        v = self.views[pid]
        v.state = state
        v.updated = time.time() if now is None else now

    # ------------------------------------------------------------------ fusion
    def _fresh(self, now: float) -> List[PlayerView]:
        return [v for v in self.views.values() if v.state is not None and now - v.updated <= FRESH_S]

    @staticmethod
    def _side_for(view: PlayerView, team: str) -> str:
        return "left" if view.info.team == team else "right"

    def fuse(self, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        fresh = self._fresh(now)
        teams: Dict[str, dict] = {}
        for team in ("A", "B"):
            counts, names = [], Counter()
            n_named = 0
            for v in fresh:
                slots = v.state["teams"][self._side_for(v, team)]
                alive = [s for s in slots if s["alive"]]
                counts.append(len(alive))
                ids = [s["agent"] for s in alive if s["agent"]]
                if ids:
                    n_named += 1
                    names.update(set(ids))
            count = int(round(statistics.median(counts))) if counts else None
            alive_agents = sorted(a for a, c in names.items() if c * 2 > n_named) if n_named else []
            teams[team] = {"alive": count, "alive_agents": alive_agents, "views": len(counts)}

        # spike
        planted_votes = [bool(v.state["spike"]["planted"]) for v in fresh]
        planted = sum(planted_votes) * 2 > len(planted_votes) if planted_votes else False
        if planted and self.planted_at is None:
            self.planted_at = now
        if not planted:
            self.planted_at = None
        carrier_votes = Counter()
        for v in fresh:
            cs = v.state["spike"]["carrier_slot"]
            if cs is None:
                continue
            for side in ("left", "right"):
                for s in v.state["teams"][side]:
                    if s["slot"] == cs and s["agent"]:
                        carrier_votes[s["agent"]] += 1
        carrier_agent = carrier_votes.most_common(1)[0][0] if carrier_votes and not planted else None

        # players
        players = []
        for pid, v in sorted(self.views.items(), key=lambda kv: (kv[1].info.team, int(''.join(c for c in kv[0] if c.isdigit()) or 0))):
            info, st = v.info, v.state
            online = st is not None and now - v.updated <= FRESH_S
            alive = None
            team_named = teams[info.team]["alive_agents"]
            if info.agent and team_named:
                alive = info.agent in team_named
            elif st is not None:
                alive = st["player"]["hp"] is not None
            rec = {"pid": pid, "name": info.name, "team": info.team, "agent": info.agent, "online": online,
                   "alive": alive, "fps": st.get("engine_fps") if st else None,
                   "latency_ms": st.get("latency_ms") if st else None,
                   "has_spike": bool(carrier_agent and info.agent == carrier_agent)}
            if st is not None and alive:
                vit = {"hp": st["player"]["hp"], "shield": st["player"]["shield"],
                       "abilities": dict(st["player"]["abilities"]), "ult_points": st["player"]["ult_points"],
                       "ult_max": st["player"]["ult_max"], "ult_ready": st["player"]["ult_ready"],
                       "loadout": {k: st["loadout"].get(k) for k in ("primary", "secondary", "active")}}
                if vit["hp"] is not None:
                    v.frozen = copy.deepcopy(vit)
                rec.update(vit)
            else:
                rec.update(copy.deepcopy(v.frozen) if v.frozen else
                           {"hp": None, "shield": None, "abilities": {"c": 0, "q": 0, "e": 0}, "ult_points": None,
                            "ult_max": 7, "ult_ready": False, "loadout": {"primary": None, "secondary": None, "active": None}})
                if alive is False:
                    rec["hp"], rec["shield"] = 0, 0
            players.append(rec)

        m = {"type": "match", "t": round(now - self.t0, 3), "teams": teams,
             "spike": {"planted": planted, "timer": round(max(0.0, SPIKE_FUSE - (now - self.planted_at)), 2)
                       if self.planted_at else None,
                       "carrier_agent": carrier_agent,
                       "carrier_pid": next((p["pid"] for p in players if p["has_spike"]), None)},
             "players": players}
        evs = self._diff(self.prev, m) if self.prev else []
        self.events.extend(evs)
        m["events"] = evs
        m["recent_events"] = list(self.events)[-12:]
        self.prev = m
        return m

    # ------------------------------------------------------------------ events
    @staticmethod
    def _diff(p: dict, m: dict) -> List[dict]:
        ev = []

        def add(kind, **kw):
            ev.append({"t": m["t"], "type": kind, **kw})

        before = {x["pid"]: x for x in p["players"]}
        for x in m["players"]:
            b = before.get(x["pid"])
            if not b:
                continue
            who = {"pid": x["pid"], "name": x["name"], "team": x["team"], "agent": x["agent"]}
            if b["alive"] and x["alive"] is False:
                add("death", **who)
            if x["alive"]:
                if (b.get("hp") is not None and x.get("hp") is not None and x["hp"] < b["hp"]):
                    add("damage", amount=b["hp"] - x["hp"], hp=x["hp"], **who)
                for k in ("c", "q", "e"):
                    if x["abilities"][k] < b["abilities"][k]:
                        add("ability_used", key=k.upper(), remaining=x["abilities"][k], **who)
                if x["ult_ready"] and not b["ult_ready"]:
                    add("ult_ready", **who)
                if b["ult_ready"] and not x["ult_ready"]:
                    add("ult_used", **who)
        for team in ("A", "B"):
            a0, a1 = p["teams"][team]["alive"], m["teams"][team]["alive"]
            if a0 is not None and a1 is not None and a1 != a0:
                add("alive_count", team=team, alive=a1)
        if m["spike"]["planted"] and not p["spike"]["planted"]:
            add("spike_planted")
        if not m["spike"]["planted"] and m["spike"]["carrier_pid"] != p["spike"]["carrier_pid"]:
            if m["spike"]["carrier_pid"]:
                add("spike_picked_up", pid=m["spike"]["carrier_pid"], agent=m["spike"]["carrier_agent"])
            elif p["spike"]["carrier_pid"]:
                add("spike_dropped", pid=p["spike"]["carrier_pid"])
        return ev
