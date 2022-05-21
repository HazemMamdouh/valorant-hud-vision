"""Map the new state to the 2022 JSON message format (for old clients)."""
from __future__ import annotations

from typing import Any, Dict


def to_legacy(s: Dict[str, Any]) -> Dict[str, Any]:
    p, lo = s["player"], s["loadout"]
    alive = {}
    for side in ("left", "right"):
        for x in s["teams"][side]:
            alive[f"agent{x['slot']}"] = x["alive"]
    return {
        "ALIVE_AGENTS": alive,
        "AGENT_TEAM": "Green" if p["team"] == "ally" else "Red",
        "CURR_AGENT": p["agent_key"],
        "HP": str(p["hp"]) if p["hp"] is not None else 0,
        "SHIELD": str(p["shield"]) if p["shield"] is not None else 0,
        "AB_C": p["abilities"]["c"], "AB_Q": p["abilities"]["q"], "AB_E": p["abilities"]["e"],
        "AB_X": p["ult_points"], "ULT_READY": p["ult_ready"],
        "CURR_WEAPON": lo.get("secondary"),
        "SPIKE_PLANTED": True if s["spike"]["planted"] else None,
        "SPIKE_CARRIER_IDX": s["spike"]["carrier_slot"],
    }
