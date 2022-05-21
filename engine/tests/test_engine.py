import numpy as np
import pytest

from valovision.config import DEFAULT_LAYOUT, LAYOUT_DIR, from_legacy_txt, load_layout
from valovision.glyphs import text_mask
from valovision.ocr import read_number
from valovision.pipeline import Engine
from valovision.synth import HudRenderer, Scenario
from valovision.templates import AgentBank, DigitBank, TEMPLATE_DIR, WeaponBank
from valovision.tracking import Tracker


@pytest.fixture(scope="module")
def engine():
    return Engine()


@pytest.fixture(scope="module")
def renderer():
    return HudRenderer()


def test_legacy_config_matches_json_layout():
    a = load_layout(DEFAULT_LAYOUT)
    b = from_legacy_txt(LAYOUT_DIR / "legacy_screen_config_2022.txt")
    assert a.all_rois() == b.all_rois()


def test_vectorised_agent_ncc_equals_opencv():
    bank = AgentBank()
    rng = np.random.default_rng(0)
    for _ in range(5):
        crop = rng.integers(0, 255, (55, 55), dtype=np.uint8)
        assert np.allclose(bank.match(crop)[2], bank.match_opencv(crop)[2], atol=1e-4)
    t = bank.templates[3]
    assert bank.match(t.gray)[0] == t.name


def test_vectorised_weapon_ncc_equals_opencv():
    bank = WeaponBank(TEMPLATE_DIR / "mainarms", (27, 131))
    for t in bank.templates:
        assert bank.match(t.fitted) == (t.name, pytest.approx(1.0, abs=1e-4))
        assert bank.match(t.fitted)[0] == bank.match_opencv(t.fitted)[0]


@pytest.mark.parametrize("value,size", [(100, 28), (73, 28), (8, 28), (50, 12), (31, 12)])
def test_digit_reader_dejavu(value, size):
    m = text_mask(str(value), size)
    roi = np.zeros((m.shape[0] + 8, m.shape[1] + 8), np.uint8) + 30
    roi[4:4 + m.shape[0], 4:4 + m.shape[1]] = np.maximum(30, m)
    v, conf = read_number(roi, DigitBank(TEMPLATE_DIR / "digits"))
    assert v == value and conf > 0.55


def test_flat_crop_scores_zero_not_inf():
    """Regression: a flat crop made the vectorised NCC divide by ~0 (found on real frames)."""
    bank = AgentBank()
    _, score, scores = bank.match(np.full((55, 55), 200, np.uint8))
    assert np.all(np.abs(scores) <= 1.0) and score == 0.0


@pytest.mark.parametrize("pid,t", [("p1", 0.5), ("p1", 6.6), ("p1", 13.0), ("p1", 15.0), ("p1", 19.5),
                                   ("p1", 24.5), ("p1", 29.0), ("p4", 12.0), ("p7", 21.0), ("p9", 2.0)])
def test_engine_reads_replica_hud(engine, renderer, pid, t):
    frame, gt = renderer.render_pov(Scenario(), pid, t)
    s = engine.process(frame, index=0)
    p, g = s["player"], gt["player"]
    assert (p["hp"], p["shield"]) == (g["hp"], g["shield"])
    assert p["abilities"] == g["abilities"]
    assert p["ult_ready"] == g["ult_ready"]
    for k in ("primary", "secondary", "active"):
        assert s["loadout"][k] == gt["loadout"][k]
    assert s["spike"]["planted"] == gt["spike"]["planted"]
    assert s["spike"]["carrier_slot"] == gt["spike"]["carrier_slot"]
    for side in ("left", "right"):
        assert [x["alive"] for x in s["teams"][side]] == [x["alive"] for x in gt["teams"][side]]
        assert [x["agent"] for x in s["teams"][side]] == [x["agent"] for x in gt["teams"][side]]


def test_16x10_frames_are_normalised(engine, renderer):
    """A 1920x1200 capture: HUD is height-scaled and centred (as in the game)."""
    import cv2
    frame, gt = renderer.render_pov(Scenario(), "p1", 1.0)
    big = cv2.resize(frame, (1920, 1080))
    tall = cv2.copyMakeBorder(big, 0, 0, 0, 0, cv2.BORDER_CONSTANT)
    canvas = np.zeros((1200, 1920, 3), np.uint8)
    hud = cv2.resize(big, (int(1920 * 1200 / 1080), 1200))
    x0 = (hud.shape[1] - 1920) // 2
    canvas[:] = hud[:, x0:x0 + 1920]
    s = engine.process(canvas, index=0)
    assert s["player"]["hp"] == 100 and s["player"]["shield"] == 50


def test_registration_recovers_hud_offset(renderer):
    """Registration (spectator HUD only) anchors on the bottom-left agent portrait."""
    import cv2
    frame, _ = renderer.render_pov(Scenario(), "p1", 1.0)
    e = Engine(register=True)
    x0, y0, x1, y1 = e.layout.current_agent
    icon = cv2.resize(cv2.imread(str(TEMPLATE_DIR / "agents" / "Jett_icon.png"), cv2.IMREAD_UNCHANGED), (x1 - x0, y1 - y0))
    frame[y0:y1, x0:x1] = (178, 205, 92)
    a = icon[:, :, 3:4] / 255.0
    frame[y0:y1, x0:x1] = (frame[y0:y1, x0:x1] * (1 - a) + icon[:, :, :3] * a).astype(np.uint8)
    shifted = np.roll(np.roll(frame, 3, axis=1), 2, axis=0)
    s = e.process(shifted, index=0)
    assert s["hud_offset"] == [3, 2]
    assert s["player"]["hp"] == 100


def test_tracker_emits_death_by_name(renderer):
    e, tr = Engine(), Tracker()
    events = []
    for i, t in enumerate(np.arange(2.8, 3.4, 1 / 30)):
        frame, _ = renderer.render_pov(Scenario(), "p1", float(t))
        events += tr.update(e.process(frame, index=i, timestamp=float(t)))["events"]
    deaths = [x for x in events if x["type"] == "death"]
    assert len(deaths) == 1 and deaths[0]["agent"] == "Reyna" and deaths[0]["side"] == "right"
