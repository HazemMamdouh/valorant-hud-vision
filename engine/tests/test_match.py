"""Fusion of ten player screens, and the engine/commentator wire protocol."""
import json
import struct
import time

import cv2
import numpy as np
from fastapi.testclient import TestClient

from valovision.hub import create_hub_app, unpack_frame
from valovision.match import MatchFusion, PlayerInfo
from valovision.pipeline import Engine
from valovision.synth import HudRenderer, default_match, player_truth
from valovision.tracking import Tracker


def _views(sc, t, r, eng):
    out = {}
    for p in sc.players:
        f, _ = r.render_pov(sc, p.pid, t)
        out[p.pid] = Tracker().update(eng.process(f, index=0, timestamp=t))
    return out


def test_fusion_matches_truth_and_freezes_dead_players():
    sc, r, eng = default_match(), HudRenderer(), Engine()
    fusion = MatchFusion()
    for p in sc.players:
        fusion.register(PlayerInfo(p.pid, p.name, p.team, p.agent))
    for t in (2.0, 21.0):
        now = time.time()
        for pid, st in _views(sc, t, r, eng).items():
            fusion.update(pid, st, now)
        m = fusion.fuse(now)
        for team in "AB":
            assert m["teams"][team]["alive"] == sum(player_truth(sc, q.pid, t)["alive"] for q in sc.team(team))
        for p in m["players"]:
            truth = player_truth(sc, p["pid"], t)
            assert p["alive"] == truth["alive"], (t, p["pid"])
            if truth["alive"]:
                assert p["hp"] == truth["hp"] and p["abilities"] == truth["abilities"]
            else:
                assert p["hp"] == 0      # its screen shows a teammate's HUD, which must not leak in
    assert m["spike"]["planted"] is True


def test_hub_ingest_and_feed_roundtrip():
    sc, r = default_match(), HudRenderer()
    app = create_hub_app(forward_fps=50, match_hz=50)
    with TestClient(app) as c:
        with c.websocket_connect("/feed") as feed:
            feed.send_text(json.dumps({"type": "subscribe", "frames": True}))
            with c.websocket_connect("/ingest") as ing:
                ing.send_text(json.dumps({"type": "hello", "pid": "p1", "name": "Hazem", "team": "A", "agent": "Jett"}))
                assert json.loads(ing.receive_text())["type"] == "welcome"
                f, _ = r.render_pov(sc, "p1", 1.0)
                jpg = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
                ing.send_bytes(struct.pack(">d", time.time()) + jpg)
                got_match = got_frame = False
                for _ in range(40):
                    msg = feed.receive()
                    if msg.get("text"):
                        m = json.loads(msg["text"])
                        p1 = next(p for p in m["players"] if p["pid"] == "p1")
                        if p1["hp"] == 100:
                            got_match = True
                    elif msg.get("bytes"):
                        hdr, body = unpack_frame(msg["bytes"])
                        got_frame = hdr["pid"] == "p1" and body == jpg     # forwarded unchanged
                    if got_match and got_frame:
                        break
                assert got_match and got_frame
        h = c.get("/api/health").json()
        assert h["players"] == 1 and h["sessions"][0]["frames_done"] >= 1


def test_hub_rejects_bad_token():
    app = create_hub_app(token="secret")
    with TestClient(app) as c:
        with c.websocket_connect("/ingest") as ing:
            ing.send_text(json.dumps({"type": "hello", "pid": "p1", "team": "A", "token": "wrong"}))
            assert json.loads(ing.receive_text())["type"] == "error"
