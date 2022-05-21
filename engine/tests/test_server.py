from fastapi.testclient import TestClient

from valovision.pipeline import Engine
from valovision.server import create_app
from valovision.synth import HudRenderer, Scenario
from valovision.tracking import Tracker


def test_api_and_websocket():
    app = create_app(source="screen", start=False)
    frame, _ = HudRenderer().render_pov(Scenario(), "p1", 1.0)
    st = Tracker().update(Engine().process(frame, index=0, timestamp=1.0))
    runner = app.state.runner
    runner.latest, runner.version = st, 1
    with TestClient(app) as c:
        assert c.get("/api/health").json()["ok"] is True
        assert c.get("/api/state").json()["player"]["hp"] == 100
        legacy = c.get("/api/state?format=legacy").json()
        assert legacy["HP"] == "100" and legacy["SHIELD"] == "50" and legacy["ALIVE_AGENTS"]["agent1"] is True
        assert "hp" in c.get("/api/layout").json()["rois"]
        with c.websocket_connect("/ws") as ws:
            assert ws.receive_json()["frame"] == 0
