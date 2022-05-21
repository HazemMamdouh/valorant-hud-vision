"""Compare engine output against ground truth, field by field."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Dict, List

FIELDS: Dict[str, Callable[[dict], Any]] = {
    "player.hp": lambda s: s["player"]["hp"],
    "player.shield": lambda s: s["player"]["shield"],
    "ability.c": lambda s: s["player"]["abilities"]["c"],
    "ability.q": lambda s: s["player"]["abilities"]["q"],
    "ability.e": lambda s: s["player"]["abilities"]["e"],
    "ult.points": lambda s: s["player"]["ult_points"],
    "ult.ready": lambda s: s["player"]["ult_ready"],
    "loadout.primary": lambda s: s["loadout"]["primary"],
    "loadout.secondary": lambda s: s["loadout"]["secondary"],
    "loadout.active": lambda s: s["loadout"]["active"],
    "spike.planted": lambda s: s["spike"]["planted"],
    "spike.carrier": lambda s: s["spike"]["carrier_slot"],
    "roster.alive(10)": lambda s: tuple(x["alive"] for side in ("left", "right") for x in s["teams"][side]),
    "roster.agents(10)": lambda s: tuple(x["agent"] for side in ("left", "right") for x in s["teams"][side]),
}


def evaluate(pred: List[dict], gt: List[dict]) -> Dict[str, dict]:
    ok = defaultdict(int)
    errors: Dict[str, List[dict]] = defaultdict(list)
    n = min(len(pred), len(gt))
    for p, g in zip(pred[:n], gt[:n]):
        for name, get in FIELDS.items():
            try:
                pv, gv = get(p), get(g)
            except (KeyError, TypeError):
                pv, gv = "<missing>", get(g)
            if pv == gv:
                ok[name] += 1
            elif len(errors[name]) < 5:
                errors[name].append({"frame": g.get("frame"), "pred": pv, "gt": gv})
    report = {k: {"accuracy": round(ok[k] / n, 4) if n else 0.0, "correct": ok[k], "frames": n,
                  "examples": errors.get(k, [])} for k in FIELDS}
    total = sum(ok.values())
    report["_overall"] = {"accuracy": round(total / (n * len(FIELDS)), 4) if n else 0.0,
                          "frames": n, "fields": len(FIELDS)}
    return report
