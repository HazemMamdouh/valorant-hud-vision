"""Realtime server: capture loop -> engine -> tracker -> WebSocket fan-out.

2022: Flask-SocketIO + eventlet; the engine only ran when a client sent a chat
message, and the result travelled as a stringified JSON chat message.
Now: a dedicated capture thread runs continuously at the target FPS and every
connected overlay receives each new state as a JSON frame on ``/ws``.

Endpoints
---------
GET  /api/health         engine status, fps, latency
GET  /api/state          latest state (``?format=legacy`` -> 2022 keys)
GET  /api/layout         ROIs in use (handy for calibration tools)
WS   /ws                 push stream of states
GET  /                   the built React overlay (if overlay/dist exists)
GET  /samples/...        sample media + analysis JSON (for replay mode)
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .legacy_compat import to_legacy
from .pipeline import Engine
from .sources import open_source
from .tracking import Tracker

import os

REPO_ROOT = Path(os.environ.get("VALOVISION_ROOT", Path(__file__).resolve().parents[2]))


class Runner(threading.Thread):
    def __init__(self, source: str, fps: float = 30.0, loop: bool = True, layout: Optional[str] = None,
                 mode: str = "sequential", agent: Optional[str] = None, name: Optional[str] = None):
        super().__init__(daemon=True, name="capture")
        self.source_spec, self.fps, self.loop = source, fps, loop
        self.engine = Engine(layout, mode=mode)
        self.agent, self.name = agent, name     # the player HUD does not show who you are: declared
        self.tracker = Tracker(fps=fps)
        self.latest: Optional[dict] = None
        self.version = 0
        self.running = True
        self.error: Optional[str] = None
        self._lat = deque(maxlen=120)
        self._ticks = deque(maxlen=120)

    def run(self):
        try:
            src = open_source(self.source_spec, realtime=True, loop=self.loop, fps=self.fps)
            for i, ts, frame in src:
                if not self.running:
                    break
                raw = self.engine.process(frame, index=i, timestamp=ts)
                st = self.tracker.update(raw)
                if i == 0:
                    self.tracker = Tracker(fps=self.fps)   # new loop of a looping video
                    st = self.tracker.update(raw)
                self._lat.append(raw["latency_ms"])
                self._ticks.append(time.perf_counter())
                st["engine"] = self.stats()
                if self.agent and not st["player"].get("agent"):
                    st["player"]["agent"] = self.agent
                st["player"]["name"] = self.name
                self.latest = st
                self.version += 1
        except Exception as e:   # surfaced on /api/health
            self.error = f"{type(e).__name__}: {e}"
            raise

    def stats(self) -> dict:
        fps = 0.0
        if len(self._ticks) > 1:
            fps = (len(self._ticks) - 1) / (self._ticks[-1] - self._ticks[0] + 1e-9)
        lat = sorted(self._lat)
        return {"fps": round(fps, 1), "latency_ms": round(lat[len(lat) // 2], 2) if lat else None,
                "source": self.source_spec, "layout": self.engine.layout.name}


def create_app(source: str = "screen", fps: float = 30.0, loop: bool = True, layout: Optional[str] = None,
               mode: str = "sequential", start: bool = True, agent: Optional[str] = None,
               name: Optional[str] = None) -> FastAPI:
    runner = Runner(source, fps, loop, layout, mode, agent=agent, name=name)

    @asynccontextmanager
    async def lifespan(_app):
        if start:
            runner.start()
        yield
        runner.running = False
        runner.engine.close()

    app = FastAPI(title="ValoVision engine", version="2.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.state.runner = runner

    @app.get("/api/health")
    def health():
        return {"ok": runner.error is None, "error": runner.error, "frames": runner.version, **runner.stats()}

    @app.get("/api/state")
    def state(format: str = "v2"):
        if runner.latest is None:
            return JSONResponse({"detail": "no frame yet"}, status_code=503)
        return to_legacy(runner.latest) if format == "legacy" else runner.latest

    @app.get("/api/layout")
    def layout_info():
        L = runner.engine.layout
        return {"name": L.name, "game_version": L.game_version, "base_resolution": L.base_resolution,
                "rois": L.all_rois()}

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        seen = -1
        try:
            while True:
                if runner.version != seen and runner.latest is not None:
                    seen = runner.version
                    await sock.send_text(json.dumps(runner.latest, separators=(",", ":")))
                await asyncio.sleep(0.004)
        except (WebSocketDisconnect, RuntimeError):
            return

    samples = REPO_ROOT / "samples"
    if samples.exists():
        app.mount("/samples", StaticFiles(directory=samples), name="samples")
    dist = REPO_ROOT / "overlay" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="overlay")
    return app
