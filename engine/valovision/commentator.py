"""Commentator server: receives everything from the engine, analyses nothing.

    engine /feed ──► commentator server ──► caster browser(s) / OBS

* subscribes to the engine's ``/feed`` (match state JSON + player JPEG frames);
* relays both, unchanged, to any number of browsers on ``/ws``;
* serves the caster UI (``/`` -> React overlay in caster view, all 10 feeds);
* exposes each player's live feed as ``/feeds/<pid>.jpg`` and
  ``/feeds/<pid>.mjpeg`` (an MJPEG stream OBS can use as a media source);
* ``/api/match`` returns the latest fused match state.

    valovision commentator --engine ws://ENGINE_IP:8000/feed --port 9000
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .hub import unpack_frame

REPO_ROOT = Path(os.environ.get("VALOVISION_ROOT", Path(__file__).resolve().parents[2]))


class Relay:
    def __init__(self, engine_url: str, token: Optional[str] = None):
        self.engine_url = engine_url
        self.token = token
        self.match: Optional[dict] = None
        self.frames: Dict[str, bytes] = {}
        self.frame_meta: Dict[str, dict] = {}
        self.clients: Set[asyncio.Queue] = set()
        self.frame_events: Dict[str, asyncio.Event] = {}
        self.connected = False
        self.last_rx = 0.0
        self.rx_frames = 0

    def _push(self, msg) -> None:
        for q in list(self.clients):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(msg)

    async def run(self) -> None:
        import websockets
        backoff = 0.5
        while True:
            try:
                async with websockets.connect(self.engine_url, max_size=None, ping_interval=10) as ws:
                    await ws.send(json.dumps({"type": "subscribe", "token": self.token, "frames": True}))
                    self.connected, backoff = True, 0.5
                    async for msg in ws:
                        self.last_rx = time.time()
                        if isinstance(msg, bytes):
                            hdr, jpeg = unpack_frame(msg)
                            pid = hdr["pid"]
                            self.frames[pid], self.frame_meta[pid] = jpeg, hdr
                            self.rx_frames += 1
                            self.frame_events.setdefault(pid, asyncio.Event()).set()
                        else:
                            self.match = json.loads(msg)
                        self._push(msg)
            except Exception:
                self.connected = False
                await asyncio.sleep(backoff)
                backoff = min(5.0, backoff * 2)


def create_commentator_app(engine_url: str, token: Optional[str] = None) -> FastAPI:
    relay = Relay(engine_url, token)

    @asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(relay.run())
        yield
        task.cancel()

    app = FastAPI(title="ValoVision commentator server", version="2.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.state.relay = relay

    @app.get("/")
    def root():
        return RedirectResponse("/index.html?view=caster")

    @app.get("/api/health")
    def health():
        return {"ok": relay.connected, "engine": relay.engine_url, "browsers": len(relay.clients),
                "players_with_video": sorted(relay.frames), "frames_received": relay.rx_frames,
                "last_message_s_ago": round(time.time() - relay.last_rx, 2) if relay.last_rx else None}

    @app.get("/api/match")
    def match():
        return relay.match or JSONResponse({"detail": "no match state yet"}, status_code=503)

    @app.get("/feeds/{pid}.jpg")
    def frame(pid: str):
        if pid not in relay.frames:
            return JSONResponse({"detail": "no frame for this player yet"}, status_code=404)
        return Response(relay.frames[pid], media_type="image/jpeg")

    @app.get("/feeds/{pid}.mjpeg")
    async def mjpeg(pid: str):
        ev = relay.frame_events.setdefault(pid, asyncio.Event())

        async def gen():
            while True:
                await ev.wait()
                ev.clear()
                jpg = relay.frames.get(pid)
                if jpg:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + \
                          b"\r\n\r\n" + jpg + b"\r\n"
        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        relay.clients.add(q)
        try:
            if relay.match:
                await sock.send_text(json.dumps(relay.match))
            for pid, jpg in relay.frames.items():
                from .hub import pack_frame
                await sock.send_bytes(pack_frame(relay.frame_meta[pid], jpg))
            while True:
                msg = await q.get()
                if isinstance(msg, bytes):
                    await sock.send_bytes(msg)
                else:
                    await sock.send_text(msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            relay.clients.discard(q)

    dist = REPO_ROOT / "overlay" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="caster")
    return app
