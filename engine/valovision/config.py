"""HUD layout loading.

A *layout* describes where every HUD element lives on a 1280x720 frame and the
thresholds each detector uses. Frames of any other resolution are resized to
the layout's base resolution once per frame (the 2022 engine resized up to 4
times per frame, once inside each detector).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

PACKAGE_DIR = Path(__file__).resolve().parent
LAYOUT_DIR = PACKAGE_DIR / "layouts"
ASSET_DIR = PACKAGE_DIR / "assets"
DEFAULT_LAYOUT = LAYOUT_DIR / "valorant_2022q1_720p.json"

Rect = Tuple[int, int, int, int]  # x0, y0, x1, y1 (x1/y1 exclusive)


@dataclass
class Layout:
    name: str
    base_resolution: Tuple[int, int]
    current_agent: Rect
    roster_slots_left: List[Tuple[int, int]]
    portrait_size: Tuple[int, int]
    roster_area_left: Rect
    carrier_row_left: Rect
    hp: Rect
    shield: Rect
    abilities: Dict[str, Rect]
    weapons: Dict[str, Rect]
    spike: Rect
    thresholds: Dict[str, float]
    agents: Dict[str, Dict[str, int]]
    game_version: str = ""
    description: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ helpers
    @property
    def width(self) -> int:
        return self.base_resolution[0]

    @property
    def height(self) -> int:
        return self.base_resolution[1]

    def mirror_rect(self, r: Rect) -> Rect:
        """Horizontal mirror of a rect (the right team is a mirror of the left)."""
        x0, y0, x1, y1 = r
        return (self.width - x1, y0, self.width - x0, y1)

    def roster_slot_rects(self, side: str) -> List[Rect]:
        """Portrait rects for slots 1..5 (left) or 6..10 (right), left-to-right on screen."""
        w, h = self.portrait_size
        left = [(x, y, x + w, y + h) for x, y in self.roster_slots_left]
        if side == "left":
            return left
        # right team: slot 6 is closest to the centre, slot 10 is the far right.
        return [self.mirror_rect(r) for r in reversed(left)]

    def carrier_cell_rects(self, side: str) -> List[Rect]:
        """Cells of the spike-carrier row under each portrait (same order as slots)."""
        _, cy0, _, cy1 = self.carrier_row_left
        cells = [(x0 - 4, cy0, x1 + 4, cy1) for (x0, _, x1, _) in self.roster_slot_rects("left")]
        if side == "left":
            return cells
        return [self.mirror_rect(r) for r in reversed(cells)]

    def ability_charges(self, agent: str | None) -> Dict[str, int]:
        if not agent:
            return {"c": 2, "q": 2, "e": 2, "x": 7}
        return self.agents.get(agent.lower(), {"c": 2, "q": 2, "e": 2, "x": 7})

    def all_rois(self) -> Dict[str, Rect]:
        """Every ROI the engine reads, for drawing calibration overlays."""
        rois: Dict[str, Rect] = {"current_agent": self.current_agent, "hp": self.hp,
                                 "shield": self.shield, "spike": self.spike}
        for k, r in self.abilities.items():
            if k != "qe":
                rois[f"ability_{k}"] = r
        for k, r in self.weapons.items():
            rois[f"weapon_{k}"] = r
        for side in ("left", "right"):
            base = 1 if side == "left" else 6
            for i, r in enumerate(self.roster_slot_rects(side)):
                rois[f"slot_{base + i}"] = r
            for i, r in enumerate(self.carrier_cell_rects(side)):
                rois[f"carrier_{base + i}"] = r
        return rois


def load_layout(path: str | Path | None = None) -> Layout:
    path = Path(path) if path else DEFAULT_LAYOUT
    if path.suffix == ".txt":
        return from_legacy_txt(path)
    d = json.loads(Path(path).read_text())
    ro = d["roster"]
    return Layout(
        name=d["name"],
        base_resolution=tuple(d["base_resolution"]),
        current_agent=tuple(d["current_agent"]),
        roster_slots_left=[tuple(p) for p in ro["slots_left"]],
        portrait_size=tuple(ro["portrait_size"]),
        roster_area_left=tuple(ro["area_left"]),
        carrier_row_left=tuple(ro["carrier_row_left"]),
        hp=tuple(d["vitals"]["hp"]),
        shield=tuple(d["vitals"]["shield"]),
        abilities={k: tuple(v) for k, v in d["abilities"].items()},
        weapons={k: tuple(v) for k, v in d["weapons"].items()},
        spike=tuple(d["spike"]),
        thresholds=dict(d["thresholds"]),
        agents=d["agents"],
        game_version=d.get("game_version", ""),
        description=d.get("description", ""),
        raw=d,
    )


def from_legacy_txt(path: str | Path) -> Layout:
    """Load a 2022-style `screen_config.txt` (key=value ints) on top of the default thresholds."""
    cfg = {}
    for line in Path(path).read_text().splitlines():
        if "=" in line:
            k, v = line.strip().split("=")
            cfg[k.strip()] = int(v)
    base = load_layout(DEFAULT_LAYOUT)
    base.base_resolution = (cfg["resize_width"], cfg["resize_height"])
    base.current_agent = (cfg["agent_start_x"], cfg["agent_start_y"], cfg["agent_end_x"], cfg["agent_end_y"])
    base.roster_slots_left = [(cfg[f"agent{i}_x"], cfg[f"agent{i}_y"]) for i in range(1, 6)]
    base.portrait_size = (cfg["agent_w"], cfg["agent_h"])
    base.roster_area_left = (cfg["agent_area_min_x"], cfg["agent_area_min_y"],
                             cfg["agent_area_max_x"], cfg["agent_area_max_y"])
    base.carrier_row_left = (cfg["carrier_min_x"], cfg["carrier_min_y"], cfg["carrier_max_x"], cfg["carrier_max_y"])
    base.hp = (cfg["hp_start_x"], cfg["hp_start_y"], cfg["hp_end_x"], cfg["hp_end_y"])
    base.shield = (cfg["sh_start_x"], cfg["sh_start_y"], cfg["sh_end_x"], cfg["sh_end_y"])
    for a in ("c", "q", "e", "x", "qe"):
        base.abilities[a] = (cfg[f"ab_{a}_start_x"], cfg[f"ab_{a}_start_y"], cfg[f"ab_{a}_end_x"], cfg[f"ab_{a}_end_y"])
    base.weapons["secondary"] = (cfg["weap1_x_start"], cfg["weap1_y_start"], cfg["weap1_x_end"], cfg["weap1_y_end"])
    base.weapons["primary"] = (cfg["weap2_x_start"], cfg["weap2_y_start"], cfg["weap2_x_end"], cfg["weap2_y_end"])
    base.spike = (cfg["spike_min_x"], cfg["spike_min_y"], cfg["spike_max_x"], cfg["spike_max_y"])
    base.name = f"legacy:{Path(path).name}"
    return base
