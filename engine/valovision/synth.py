"""Procedural replica of the VALORANT 2022-Q1 player HUD, for one round seen by 10 players.

Why a replica? Real VODs carry no labels and ten synchronised POV recordings of
one 2022 match are not publicly available. The replica gives frame-exact ground
truth for *every* player's screen, so per-player readings and the cross-player
fusion on the engine server can both be scored.

Fidelity: the HUD style was re-derived from 89 real January–February 2022
screenshots (see docs/REAL_FOOTAGE.md), not guessed:
* top bar: living players only, packed towards the centre, a health bar under
  each portrait (white for your team, grey for enemies); dead players vanish;
* ability charges are teal bar segments (grey when spent), ult points are teal
  diamonds, the ult bar turns teal when ready;
* HP/shield use the real HUD digit glyphs; shield sits in a teal hexagon and is
  hidden at 0;
* planted spike = red inverted triangle; the carrier icon (cut from a real
  frame) is drawn under the carrier's portrait;
* the player HUD has no agent portrait in the bottom-left corner;
* a dead player's screen shows the HUD of the teammate they spectate.
Translucent panels, a moving scene, sensor noise and H.264 keep it messy.
"""
from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from .config import Layout, load_layout
from .glyphs import FONT_UI, blit_mask, draw_text, text_mask
from .templates import TEMPLATE_DIR, _read_rgba, display_name, resize_and_pad

ALLY = (178, 205, 92)        # BGR teal-green (your team)
ENEMY = (85, 70, 240)        # BGR red
WHITE = (250, 250, 250)
PANEL = (35, 25, 15)
TEAL = (180, 228, 88)        # charge / ult teal
SPENT = (150, 150, 150)


# ------------------------------------------------------------------ scenario
@dataclass
class Player:
    pid: str
    name: str
    team: str          # "A" or "B"
    agent: str


@dataclass
class MatchScenario:
    """One scripted round. Times in seconds, players referenced by pid."""
    duration: float = 30.0
    fps: int = 30
    players: List[Player] = field(default_factory=list)
    deaths: List[Tuple[float, str, str, str]] = field(default_factory=list)        # t, victim, killer, weapon
    vitals: Dict[str, List[Tuple[float, int, int]]] = field(default_factory=dict)  # pid -> (t, hp, shield)
    abilities: Dict[str, List[Tuple[float, Dict[str, int]]]] = field(default_factory=dict)
    ult: Dict[str, List[Tuple[float, int, bool]]] = field(default_factory=dict)
    loadout: Dict[str, List[Tuple[float, Optional[str], Optional[str], str]]] = field(default_factory=dict)
    spike: List[Tuple[float, Optional[str], bool]] = field(default_factory=list)   # t, carrier pid, planted
    round_clock_start: float = 84.0
    score: Tuple[int, int] = (7, 5)    # team A, team B

    def player(self, pid: str) -> Player:
        return next(p for p in self.players if p.pid == pid)

    def team(self, team: str) -> List[Player]:
        return [p for p in self.players if p.team == team]


def _at(seq, t):
    cur = seq[0]
    for item in seq:
        if item[0] <= t + 1e-9:
            cur = item
    return cur


AGENT_KITS = {  # max charges (c, q, e) used by the script, from the 2022 layout table
    "Jett": (2, 2, 1), "Sova": (1, 2, 1), "Killjoy": (2, 1, 1), "Omen": (2, 1, 2), "Skye": (1, 1, 2),
    "Reyna": (1, 2, 2), "Neon": (1, 2, 1), "Chamber": (2, 1, 1), "Viper": (2, 1, 1), "Breach": (1, 2, 1),
}


def default_match(seed: int = 7) -> MatchScenario:
    """Team A: Jett (p1, the original 2022 script), Sova, Killjoy, Omen, Skye.
    Team B: Reyna, Neon, Chamber, Viper, Breach. Deterministic."""
    rng = np.random.default_rng(seed)
    names = ["Hazem", "Nour", "Kareem", "Mona", "Ziad", "Lina", "Omar", "Sara", "Youssef", "Dina"]
    agents = ["Jett", "Sova", "Killjoy", "Omen", "Skye", "Reyna", "Neon", "Chamber", "Viper", "Breach"]
    sc = MatchScenario()
    sc.players = [Player(f"p{i + 1}", names[i], "A" if i < 5 else "B", agents[i]) for i in range(10)]
    sc.deaths = [(3.0, "p6", "p2", "Vandal"), (8.0, "p7", "p1", "Vandal"), (9.5, "p4", "p8", "Operator"),
                 (20.5, "p5", "p9", "Phantom"), (22.0, "p9", "p1", "Vandal"), (24.0, "p8", "p1", "Vandal"),
                 (27.0, "p2", "p10", "Spectre")]
    sc.spike = [(0.0, "p3", False), (11.0, None, False), (12.0, "p1", False), (19.0, None, True)]
    primaries = ["Vandal", "Phantom", "Spectre", "Bulldog", "Operator", "Vandal", "Phantom", "Operator", "Phantom", "Spectre"]
    secondaries = ["Ghost", "Classic", "Sheriff", "Ghost", "Classic", "Sheriff", "Ghost", "Frenzy", "Classic", "Ghost"]
    death_t = {v: t for t, v, _, _ in sc.deaths}
    for i, p in enumerate(sc.players):
        kit = AGENT_KITS[p.agent]
        if p.pid == "p1":   # the original 30 s Jett script
            sc.vitals[p.pid] = [(0.0, 100, 50), (6.5, 88, 31), (7.0, 73, 31), (17.0, 56, 0), (17.4, 41, 0), (26.2, 26, 0)]
            sc.abilities[p.pid] = [(0.0, {"c": 2, "q": 2, "e": 1}), (5.0, {"c": 2, "q": 1, "e": 1}),
                                   (15.5, {"c": 1, "q": 1, "e": 1}), (25.5, {"c": 1, "q": 1, "e": 0})]
            sc.ult[p.pid] = [(0.0, 4, False), (8.0, 5, False), (22.0, 6, False), (24.0, 7, True), (28.5, 0, False)]
            sc.loadout[p.pid] = [(0.0, "Vandal", "Ghost", "primary"), (14.0, "Vandal", "Ghost", "secondary"),
                                 (16.0, "Vandal", "Ghost", "primary")]
            continue
        end = death_t.get(p.pid, sc.duration)
        hp, sh, vit = 100, int(rng.choice([25, 50, 50])), []
        vit.append((0.0, hp, sh))
        for t in sorted(rng.uniform(2, max(2.5, end - 0.5), size=int(rng.integers(1, 4)))):
            dmg = int(rng.integers(12, 40))
            take = min(sh, dmg // 2)
            sh -= take
            hp = max(1, hp - (dmg - take))
            vit.append((round(float(t), 2), hp, sh))
        if p.pid in death_t:
            vit.append((death_t[p.pid], 0, 0))
        sc.vitals[p.pid] = vit
        cur = {"c": kit[0], "q": kit[1], "e": kit[2]}
        ab = [(0.0, dict(cur))]
        for t in sorted(rng.uniform(1, end, size=int(rng.integers(1, 4)))):
            k = str(rng.choice(["c", "q", "e"]))
            if cur[k] > 0:
                cur[k] -= 1
                ab.append((round(float(t), 2), dict(cur)))
        sc.abilities[p.pid] = ab
        pts = int(rng.integers(1, 7))
        sc.ult[p.pid] = [(0.0, pts, False)] + ([(round(float(rng.uniform(5, 25)), 2), 7, True)] if pts >= 5 else [])
        sc.loadout[p.pid] = [(0.0, primaries[i], secondaries[i], "primary")]
        if rng.random() < 0.4:
            t = round(float(rng.uniform(3, end)), 2)
            sc.loadout[p.pid].append((t, primaries[i], secondaries[i], "secondary"))
    return sc


def player_truth(sc: MatchScenario, pid: str, t: float) -> dict:
    """What player `pid` really has at time t (independent of whose screen shows it)."""
    p = sc.player(pid)
    _, hp, sh = _at(sc.vitals[pid], t)
    _, ab = _at(sc.abilities[pid], t)
    _, pts, ready = _at(sc.ult[pid], t)
    _, prim, sec, active = _at(sc.loadout[pid], t)
    alive = not any(v == pid and td <= t + 1e-9 for td, v, _, _ in sc.deaths)
    return {"pid": pid, "name": p.name, "team": p.team, "agent": display_name(p.agent), "alive": alive,
            "hp": hp if alive else 0, "shield": sh if alive else 0, "abilities": dict(ab),
            "ult_points": pts, "ult_ready": ready,
            "loadout": {"primary": prim, "secondary": sec, "active": active}}


def spectated(sc: MatchScenario, pid: str, t: float) -> str:
    """Whose HUD is on `pid`'s screen: their own, or a living teammate's after death."""
    if player_truth(sc, pid, t)["alive"]:
        return pid
    mates = [q.pid for q in sc.team(sc.player(pid).team) if q.pid != pid and player_truth(sc, q.pid, t)["alive"]]
    return mates[0] if mates else pid


def screen_truth(sc: MatchScenario, pid: str, t: float) -> dict:
    """Ground truth of what `pid`'s screen shows (same schema as the single-feed engine)."""
    me = sc.player(pid)
    shown = spectated(sc, pid, t)
    st = player_truth(sc, shown, t)
    hud_visible = st["alive"]
    _, carrier, planted = _at(sc.spike, t)
    teams = {}
    for side, team in (("left", me.team), ("right", "B" if me.team == "A" else "A")):
        living = [q for q in sc.team(team) if player_truth(sc, q.pid, t)["alive"]]
        k = len(living)
        slots = list(range(6 - k, 6)) if side == "left" else list(range(6, 6 + k))   # packed towards the centre
        occupied = dict(zip(slots, living))
        rng = range(1, 6) if side == "left" else range(6, 11)
        teams[side] = [{"slot": s, "agent": display_name(occupied[s].agent) if s in occupied else None,
                        "alive": s in occupied, "pid": occupied[s].pid if s in occupied else None,
                        "has_spike": s in occupied and occupied[s].pid == carrier} for s in rng]
    carrier_slot = next((x["slot"] for side in ("left", "right") for x in teams[side] if x["has_spike"]), None)
    return {"t": round(t, 4), "pov": pid, "spectating": None if shown == pid else shown,
            "player": {"agent": st["agent"], "team": "ally", "hp": st["hp"] if hud_visible else None,
                       "shield": st["shield"] if hud_visible else None, "abilities": st["abilities"],
                       "ult_points": st["ult_points"], "ult_ready": st["ult_ready"]},
            "loadout": st["loadout"], "teams": teams,
            "spike": {"planted": planted, "carrier_slot": None if planted else carrier_slot}}


# backwards-compatible single-POV API -----------------------------------------
def Scenario():   # noqa: N802  (kept for old call sites / tests)
    return default_match()


def ground_truth(sc: MatchScenario, t: float, pid: str = "p1") -> dict:
    return screen_truth(sc, pid, t)


# ------------------------------------------------------------------- renderer
SCENERY_DIR = Path(__file__).parent / "assets" / "scenery_2022"


class HudRenderer:
    """Draws the 2022-Q1 player HUD. The world behind it is procedural by default; with
    `scenery` (a folder of scene_*.jpg, e.g. SCENERY_DIR) each player's world view is a real
    2022 screenshot crop (HUD removed, tools/make_scenery.py) with aim sway applied."""

    def __init__(self, layout: Layout | None = None, seed: int = 2022, scenery: str | Path | None = None):
        self.L = layout or load_layout()
        self.W, self.H = self.L.base_resolution
        self.rng = np.random.default_rng(seed)
        self.icons = {p.name.split("_icon")[0]: cv2.resize(_read_rgba(p), tuple(self.L.portrait_size),
                                                           interpolation=cv2.INTER_AREA)
                      for p in (TEMPLATE_DIR / "agents").glob("*_icon.png")}
        self.weapon_alpha = {}
        for folder in ("mainarms", "sidearms"):
            for p in (TEMPLATE_DIR / folder).glob("*_killfeed.png"):
                a = _read_rgba(p)[:, :, 3]
                ys, xs = np.nonzero(a > 127)
                self.weapon_alpha[p.name.split("_killfeed")[0]] = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        self.digits = {str(d): cv2.imread(str(TEMPLATE_DIR / "digits_valorant" / f"{d}.png"), 0) for d in range(10)}
        self.carrier = cv2.imread(str(TEMPLATE_DIR / "hud" / "spike_carrier.png"), 0)
        self.scene = self._make_scene()
        self.scenery = ([cv2.imread(str(p)) for p in sorted(Path(scenery).glob("scene_*.jpg"))]
                        if scenery else None)

    # ---------------------------------------------------------------- scene
    def _make_scene(self) -> np.ndarray:
        W, H = 2800, self.H + 80
        rng = np.random.default_rng(7)
        img = np.zeros((H, W, 3), np.float32)
        sky_top, sky_bot = np.array([235, 205, 160]), np.array([215, 225, 235])
        for y in range(H):
            a = min(1, y / (H * 0.55))
            img[y] = sky_top * (1 - a) + sky_bot * a
        horizon = int(H * 0.52)
        palette = [(150, 185, 215), (90, 120, 175), (175, 195, 205), (120, 150, 160), (95, 105, 140), (165, 160, 120)]
        x = 0
        while x < W:
            w = int(rng.integers(120, 340)); h = int(rng.integers(140, 330))
            col = np.array(palette[int(rng.integers(len(palette)))], np.float32)
            y0 = horizon - h
            img[y0:horizon, x:x + w] = col
            img[y0:y0 + 10, x:x + w] = col * 0.75
            for wy in range(y0 + 30, horizon - 40, 55):
                for wx in range(x + 18, x + w - 30, 48):
                    img[wy:wy + 30, wx:wx + 20] = col * 0.45
            x += w + int(rng.integers(0, 40))
        for y in range(horizon, H):
            a = (y - horizon) / (H - horizon)
            img[y] = np.array([120, 145, 165]) * (0.8 + 0.2 * a)
        for k in range(-40, 80):
            x0 = k * 70
            cv2.line(img, (W // 2 + (x0 - W // 2) // 6, horizon), (x0, H), (95, 115, 135), 2, cv2.LINE_AA)
        for _ in range(14):
            cx = int(rng.integers(0, W - 160)); s = int(rng.integers(70, 150))
            y1 = horizon + int(rng.integers(30, 160)); y0 = y1 - s
            img[y0:y1, cx:cx + s] = (60, 95, 130)
            img[y0:y0 + 12, cx:cx + s] = (80, 120, 155)
            cv2.rectangle(img, (cx, y0), (cx + s - 1, y1 - 1), (40, 60, 85), 3)
        return np.clip(img, 0, 255).astype(np.uint8)

    def _background(self, t: float, phase: float, k: int = 0) -> np.ndarray:
        if self.scenery:                     # real world view; the camera sways like a held aim
            s = self.scenery[k % len(self.scenery)]
            mx, my = (s.shape[1] - self.W) // 2, (s.shape[0] - self.H) // 2
            ox = mx + int(mx * (0.6 * math.sin(t * 0.45 + phase) + 0.3 * math.sin(t * 2.3 + 2 * phase)))
            oy = my + int(my * (0.5 * math.sin(t * 0.7 + phase) + 0.35 * math.sin(t * 3.1 + phase)))
            return s[oy:oy + self.H, ox:ox + self.W].copy()
        ox = int(900 + 520 * math.sin(t * 0.33 + phase) + 60 * math.sin(t * 1.7 + phase))
        oy = int(40 + 12 * math.sin(t * 2.1 + phase))
        ox = max(0, min(self.scene.shape[1] - self.W, ox))
        return self.scene[oy:oy + self.H, ox:ox + self.W].copy()

    @staticmethod
    def _panel(f, x0, y0, x1, y1, alpha=0.72, color=PANEL):
        roi = f[y0:y1, x0:x1].astype(np.float32)
        f[y0:y1, x0:x1] = (roi * (1 - alpha) + np.array(color, np.float32) * alpha).astype(np.uint8)

    @staticmethod
    def _paste_bgra(f, bgra, x, y):
        h, w = bgra.shape[:2]
        a = bgra[:, :, 3:4].astype(np.float32) / 255.0
        roi = f[y:y + h, x:x + w].astype(np.float32)
        f[y:y + h, x:x + w] = (roi * (1 - a) + bgra[:, :, :3].astype(np.float32) * a).astype(np.uint8)

    def _number(self, f, value: int, cx: int, cy: int, height: int, color=WHITE):
        """Draw a number with the real HUD digit glyphs, centred at (cx, cy)."""
        glyphs = []
        for ch in str(value):
            g = self.digits[ch]
            w = max(1, int(round(g.shape[1] * height / g.shape[0])))
            glyphs.append(cv2.resize(g, (w, height), interpolation=cv2.INTER_AREA))
        gap = max(1, height // 10)
        total = sum(g.shape[1] for g in glyphs) + gap * (len(glyphs) - 1)
        x = cx - total // 2
        for g in glyphs:
            blit_mask(f, g, x, cy - height // 2, color)
            x += g.shape[1] + gap

    # ---------------------------------------------------------------- HUD parts
    def _top_bar(self, f, gt, sc: MatchScenario, t: float):
        L = self.L
        self._panel(f, 286, 12, self.W - 286, 92, alpha=0.6)
        for side in ("left", "right"):
            col = ALLY if side == "left" else ENEMY
            for (x0, y0, x1, y1), s in zip(L.roster_slot_rects(side), gt["teams"][side]):
                if not s["alive"]:
                    continue
                agent = sc.player(s["pid"]).agent
                icon = self.icons[agent if agent != "KAY/O" else "KAYO"]
                if side == "right":
                    icon = cv2.flip(icon, 1)
                f[y0:y1, x0:x1] = (np.array(col) * 0.55).astype(np.uint8)
                self._paste_bgra(f, icon, x0, y0)
                hp = player_truth(sc, s["pid"], t)["hp"]
                bar_col = (250, 250, 250) if side == "left" else (160, 160, 160)
                cv2.rectangle(f, (x0 + 1, y1 + 4), (x1 - 2, y1 + 7), (90, 90, 90), -1)
                cv2.rectangle(f, (x0 + 1, y1 + 4), (x0 + 1 + int((x1 - x0 - 3) * hp / 100), y1 + 7), bar_col, -1)
                if s["has_spike"]:
                    ch, cw = self.carrier.shape
                    cx = (x0 + x1) // 2 - cw // 2
                    roi = f[62:62 + ch, cx:cx + cw].astype(np.float32)
                    a = (self.carrier > 70).astype(np.float32)[..., None] * 0.95
                    g = np.repeat(self.carrier[:, :, None], 3, 2).astype(np.float32)
                    f[62:62 + ch, cx:cx + cw] = (roi * (1 - a) + g * a).astype(np.uint8)
        sx0, sy0, sx1, sy1 = L.spike
        if gt["spike"]["planted"]:
            cx = (sx0 + sx1) // 2
            tri = np.array([[sx0 + 2, sy0 + 4], [sx1 - 2, sy0 + 4], [cx, sy1 - 2]], np.int32)
            pulse = 0.85 + 0.15 * math.sin(t * 10)
            cv2.fillConvexPoly(f, tri, (int(40 * pulse), int(30 * pulse), int(225 * pulse)), cv2.LINE_AA)
            cv2.circle(f, (cx, sy0 + 20), 8, (30, 20, 110), 2, cv2.LINE_AA)
        else:
            left = max(0.0, sc.round_clock_start - t)
            draw_text(f, f"{int(left // 60)}:{int(left % 60):02d}", (sx0 + sx1) // 2, (sy0 + sy1) // 2 + 2, 17,
                      WHITE, "mm")
        a, b = sc.score
        mine = gt["_team"]
        draw_text(f, str(a if mine == "A" else b), sx0 - 22, 36, 22, ALLY, "mm")
        draw_text(f, str(b if mine == "A" else a), sx1 + 22, 36, 22, ENEMY, "mm")

    def _minimap(self, f, t):
        self._panel(f, 8, 8, 236, 236, alpha=0.55, color=(40, 40, 40))
        pts = [(30, 40), (200, 40), (200, 120), (150, 120), (150, 210), (40, 210), (40, 130), (30, 130)]
        cv2.polylines(f, [np.array(pts, np.int32)], True, (150, 150, 150), 2, cv2.LINE_AA)
        for k, (bx, by) in enumerate([(60, 180), (90, 160), (120, 190), (70, 70), (170, 80)]):
            cv2.circle(f, (bx + int(8 * math.sin(t * 0.7 + k)), by), 5, ALLY, -1, cv2.LINE_AA)

    def _killfeed(self, f, sc: MatchScenario, pov_team: str, t: float):
        y = 100
        for (tk, victim, killer, weapon) in sc.deaths:
            if not (tk <= t < tk + 5.0):
                continue
            K, V = sc.player(killer), sc.player(victim)
            kc = ALLY if K.team == pov_team else ENEMY
            vc = ALLY if V.team == pov_team else ENEMY
            km = text_mask(K.agent.upper(), 13, FONT_UI)
            vm = text_mask(V.agent.upper(), 13, FONT_UI)
            wa = self.weapon_alpha[weapon]
            wa = cv2.resize(wa, (int(wa.shape[1] * 16 / wa.shape[0]), 16), interpolation=cv2.INTER_AREA)
            width = km.shape[1] + wa.shape[1] + vm.shape[1] + 40
            x1 = self.W - 14
            x0 = x1 - width
            self._panel(f, x0, y, x1, y + 26, alpha=0.75)
            blit_mask(f, km, x0 + 10, y + 7, kc)
            blit_mask(f, wa, x0 + 20 + km.shape[1], y + 5, WHITE)
            blit_mask(f, vm, x1 - 10 - vm.shape[1], y + 7, vc)
            y += 31

    def _bottom(self, f, gt, sc: MatchScenario, shown_pid: str, t: float):
        L, p = self.L, gt["player"]
        self._panel(f, 340, 638, 800, 714, alpha=0.55)
        if p["hp"] is not None:
            hx0, hy0, hx1, hy1 = L.hp
            self._number(f, p["hp"], (hx0 + hx1) // 2, (hy0 + hy1) // 2, 22,
                         WHITE if p["hp"] >= 50 else (170, 235, 240))
            sx0, sy0, sx1, sy1 = L.shield
            if p["shield"]:
                cx, cy, r = (sx0 + sx1) // 2, (sy0 + sy1) // 2, 10
                hexa = np.array([[cx + r * math.cos(a), cy + r * math.sin(a)]
                                 for a in np.linspace(0, 2 * math.pi, 7)[:-1] + math.pi / 6], np.int32)
                cv2.polylines(f, [hexa], True, TEAL, 1, cv2.LINE_AA)
                self._number(f, p["shield"], cx, cy, 9)
        kit = AGENT_KITS.get(sc.player(shown_pid).agent, (2, 2, 2))
        maxes = {"c": kit[0], "q": kit[1], "e": kit[2]}
        for key in ("c", "q", "e", "x"):
            ax0, ay0, ax1, ay1 = L.abilities[key]
            cx = (ax0 + ax1) // 2
            draw_text(f, key.upper(), cx, 664, 15, (215, 215, 215), "mm", font=FONT_UI)
            if key == "x":
                n = 7
                for i in range(n):
                    xx = cx + int((i - (n - 1) / 2) * 7)
                    on = p["ult_ready"] or i < p["ult_points"]
                    cv2.fillConvexPoly(f, np.array([[xx, ay0 + 2], [xx + 2, ay0 + 4], [xx, ay0 + 6], [xx - 2, ay0 + 4]],
                                                   np.int32), TEAL if on else SPENT)
                cv2.rectangle(f, (ax0 + 4, ay0 + 10), (ax1 - 4, ay0 + 14), TEAL if p["ult_ready"] else SPENT, -1)
                continue
            n, have = maxes[key], p["abilities"][key]
            x_start, x_end = ax0 + 5, ax1 - 5
            gap = 2
            seg = (x_end - x_start - gap * (n - 1)) / n
            for i in range(n):
                a = int(round(x_start + i * (seg + gap)))
                b = int(round(x_start + i * (seg + gap) + seg)) - 1
                cv2.rectangle(f, (a, ay0 + 7), (b, ay0 + 12), TEAL if i < have else SPENT, -1)

    def _weapons(self, f, gt):
        L, lo = self.L, gt["loadout"]
        self._panel(f, 1070, 474, self.W - 8, 662, alpha=0.5)
        for slot, key in (("secondary", "2"), ("primary", "1")):
            name = lo[slot]
            x0, y0, x1, y1 = L.weapons[slot]
            draw_text(f, key, x1 + 14, (y0 + y1) // 2, 11, (180, 180, 180), "mm", font=FONT_UI)
            if not name:
                continue
            fitted = resize_and_pad(self.weapon_alpha[name], y1 - y0, x1 - x0)
            blit_mask(f, fitted, x0, y0, (252, 252, 252) if lo["active"] == slot else (178, 178, 178))

    # ---------------------------------------------------------------- frame
    def render_pov(self, sc: MatchScenario, pid: str, t: float) -> Tuple[np.ndarray, dict]:
        gt = screen_truth(sc, pid, t)
        me = sc.player(pid)
        gt["_team"] = me.team
        shown = gt["spectating"] or pid
        phase = int(shown[1:]) * 1.37         # a spectator sees the spectated player's view
        f = self._background(t, phase, int(shown[1:]) - 1)
        self._minimap(f, t)
        self._top_bar(f, gt, sc, t)
        self._killfeed(f, sc, me.team, t)
        self._bottom(f, gt, sc, shown, t)
        self._weapons(f, gt)
        if gt["spectating"]:
            draw_text(f, f"SPECTATING  {sc.player(shown).name.upper()}", self.W // 2, 600, 16, WHITE, "mm", font=FONT_UI)
        cx, cy = self.W // 2, self.H // 2
        cv2.line(f, (cx - 7, cy), (cx + 7, cy), (255, 255, 0), 2)
        cv2.line(f, (cx, cy - 7), (cx, cy + 7), (255, 255, 0), 2)
        noise = self.rng.normal(0, 3.0, f.shape).astype(np.float32)
        f = np.clip(f.astype(np.float32) + noise, 0, 255).astype(np.uint8)
        del gt["_team"]
        return f, gt

    def render(self, sc: MatchScenario, t: float, pid: str = "p1") -> Tuple[np.ndarray, dict]:
        return self.render_pov(sc, pid, t)


def _encode(path: Path, W: int, H: int, fps: int, crf: int) -> subprocess.Popen:
    return subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                             "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                             "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)],
                            stdin=subprocess.PIPE)


def render_video(out_path: Path, gt_path: Path | None = None, sc: MatchScenario | None = None,
                 crf: int = 20, layout: Layout | None = None, pid: str = "p1") -> Path:
    """One player's screen as a video (+ per-frame ground truth)."""
    sc = sc or default_match()
    r = HudRenderer(layout)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = _encode(out_path, r.W, r.H, sc.fps, crf)
    frames = []
    for i in range(int(sc.duration * sc.fps)):
        frame, gt = r.render_pov(sc, pid, i / sc.fps)
        gt["frame"] = i
        frames.append(gt)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    if gt_path:
        Path(gt_path).write_text(json.dumps(_meta(sc, r, out_path.name, pid) | {"frames": frames}))
    return out_path


def render_match(out_dir: Path, sc: MatchScenario | None = None, crf: int = 23,
                 layout: Layout | None = None, scenery: str | Path | None = None) -> Path:
    """All ten players' screens of one round: p1.mp4 … p10.mp4 + match ground truth."""
    sc = sc or default_match()
    r = HudRenderer(layout, scenery=scenery)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = int(sc.duration * sc.fps)
    for p in sc.players:
        proc = _encode(out_dir / f"{p.pid}.mp4", r.W, r.H, sc.fps, crf)
        for i in range(n):
            proc.stdin.write(r.render_pov(sc, p.pid, i / sc.fps)[0].tobytes())
        proc.stdin.close()
        proc.wait()
    truth = []
    for i in range(0, n, 3):                       # 10 Hz match truth
        t = i / sc.fps
        _, carrier, planted = _at(sc.spike, t)
        truth.append({"t": round(t, 3), "players": {p.pid: player_truth(sc, p.pid, t) for p in sc.players},
                      "alive": {tm: sum(player_truth(sc, q.pid, t)["alive"] for q in sc.team(tm)) for tm in "AB"},
                      "spike": {"planted": planted, "carrier": None if planted else carrier}})
    meta = {"fps": sc.fps, "duration": sc.duration, "resolution": [r.W, r.H], "layout": r.L.name,
            "players": [p.__dict__ for p in sc.players],
            "deaths": [{"t": t, "victim": v, "killer": k, "weapon": w} for t, v, k, w in sc.deaths],
            "truth": truth}
    (out_dir / "match.json").write_text(json.dumps(meta))
    return out_dir


def _meta(sc, r, name, pid):
    return {"video": name, "pov": pid, "fps": sc.fps, "duration": sc.duration, "resolution": [r.W, r.H],
            "layout": r.L.name, "game_version": r.L.game_version,
            "players": [p.__dict__ for p in sc.players],
            "deaths": [{"t": t, "victim": v, "killer": k, "weapon": w} for t, v, k, w in sc.deaths]}
