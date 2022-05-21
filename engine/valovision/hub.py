"""Engine server for a 10-player match (the only place where vision runs).

    player PC x10 ──JPEG frames──►  ENGINE (this)  ──match state + frames──►  commentator server ──► caster UI
       (valovision send)            /ingest  /feed                            (valovision commentator)

Players and the commentator do **no analysis**: senders capture, downscale to
the 1280x720 design size and JPEG-encode (transport only); the commentator
relays and displays. Everything else happens here:

* one session per player: newest-frame-wins slot -> worker thread ->
  JPEG decode -> Engine.process -> Tracker -> per-player screen state;
* MatchFusion merges the ten screens into one match state;
* a publisher pushes match updates (JSON, up to ``match_hz``) and the players'
  original JPEG frames (binary, up to ``forward_fps`` per player, no
  re-encoding) to every subscribed commentator server.

Wire protocol (all WebSocket)
-----------------------------
``/ingest`` (player -> engine)
    1. text  ``{"type":"hello","pid":"p3","name":"Mona","team":"A","agent":"Killjoy","token":"..."}``
    2. binary frames: 8-byte big-endian float64 capture time (sender clock, s) + JPEG bytes
    engine -> player: text ``{"type":"welcome",...}`` then ``{"type":"stats",...}`` every second
``/feed`` (engine -> commentator)
    1. text ``{"type":"subscribe","token":"...","frames":true}``
    2. engine sends text ``{"type":"match",...}`` and binary
       ``uint16 header_len | header JSON {"pid","frame","capture_ts","recv_ts"} | JPEG``
"""
from __future__ import annotations

import asyncio
import json
import struct
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .match import MatchFusion, PlayerInfo
from .pipeline import Engine
from .tracking import Tracker

FRAME_HDR = struct.Struct(">d")          # capture timestamp prefix on ingest frames


def pack_frame(header: dict, jpeg: bytes) -> bytes:
    h = json.dumps(header, separators=(",", ":")).encode()
    return struct.pack(">H", len(h)) + h + jpeg


def unpack_frame(buf: bytes):
    n = struct.unpack(">H", buf[:2])[0]
    return json.loads(buf[2:2 + n]), buf[2 + n:]


@dataclass
class Session:
    info: PlayerInfo
    engine: Engine
    tracker: Tracker
    lock: threading.Lock = field(default_factory=threading.Lock)
    wake: threading.Event = field(default_factory=threading.Event)
    pending: Optional[tuple] = None        # (jpeg, capture_ts, recv_ts) newest unprocessed
    last_jpeg: Optional[bytes] = None
    last_frame_meta: dict = field(default_factory=dict)
    state: Optional[dict] = None
    frames_in: int = 0
    frames_done: int = 0
    dropped: int = 0
    proc_ms: float = 0.0
    decode_ms: float = 0.0
    clock_offset: Optional[float] = None   # min(recv - capture): sender->server offset + min latency
    connected: bool = False
    forwarded_at: float = 0.0
    forward_seq: int = -1
    _rate: list = field(default_factory=list)
    thread: Optional[threading.Thread] = None


class Hub:
    def __init__(self, token: Optional[str] = None, forward_fps: float = 10.0, match_hz: float = 15.0,
                 layout: Optional[str] = None, max_players: int = 10):
        self.token = token
        self.forward_fps = forward_fps
        self.match_hz = match_hz
        self.layout = layout
        self.max_players = max_players
        self.sessions: Dict[str, Session] = {}
        self.fusion = MatchFusion()
        self.subscribers: Set[asyncio.Queue] = set()
        self.match: Optional[dict] = None
        self.dirty = threading.Event()
        self.running = True

    # ------------------------------------------------------------------ sessions
    def join(self, hello: dict) -> Session:
        pid = str(hello["pid"])
        team = str(hello.get("team", "A")).upper()
        if team not in ("A", "B"):
            raise ValueError("team must be 'A' or 'B'")
        info = PlayerInfo(pid=pid, name=str(hello.get("name", pid)), team=team, agent=hello.get("agent"))
        s = self.sessions.get(pid)
        if s is None:
            if len(self.sessions) >= self.max_players:
                raise ValueError(f"match is full ({self.max_players} players)")
            s = Session(info=info, engine=Engine(self.layout), tracker=Tracker())
            self.sessions[pid] = s
            s.thread = threading.Thread(target=self._worker, args=(s,), daemon=True, name=f"engine-{pid}")
            s.thread.start()
        s.info = info
        s.connected = True
        self.fusion.register(info)
        return s

    def offer(self, s: Session, buf: bytes) -> None:
        """Newest frame wins: an unprocessed older frame is dropped, never queued."""
        recv = time.time()
        cap = FRAME_HDR.unpack(buf[:8])[0]
        with s.lock:
            if s.pending is not None:
                s.dropped += 1
            s.pending = (buf[8:], cap, recv)
            s.frames_in += 1
        d = recv - cap
        s.clock_offset = d if s.clock_offset is None else min(s.clock_offset, d)
        s.wake.set()

    def _worker(self, s: Session) -> None:
        while self.running:
            if not s.wake.wait(timeout=0.5):
                continue
            with s.lock:
                item, s.pending = s.pending, None
                s.wake.clear()
            if item is None:
                continue
            jpeg, cap, recv = item
            t0 = time.perf_counter()
            img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            t1 = time.perf_counter()
            if img is None:
                continue
            raw = s.engine.process(img, index=s.frames_done, timestamp=recv - self.fusion.t0)
            st = s.tracker.update(raw)
            t2 = time.perf_counter()
            s.decode_ms = 0.9 * s.decode_ms + 0.1 * (t1 - t0) * 1000 if s.frames_done else (t1 - t0) * 1000
            s.proc_ms = 0.9 * s.proc_ms + 0.1 * (t2 - t1) * 1000 if s.frames_done else (t2 - t1) * 1000
            now = time.time()
            s._rate = [x for x in s._rate if now - x < 2.0] + [now]
            st["engine_fps"] = round((len(s._rate) - 1) / max(1e-6, s._rate[-1] - s._rate[0]), 1) if len(s._rate) > 1 else 0.0
            st["e2e_ms"] = round((now - recv) * 1000 + max(0.0, (recv - cap) - (s.clock_offset or 0)) * 1000, 1)
            s.state = st
            s.last_jpeg = jpeg
            s.last_frame_meta = {"pid": s.info.pid, "frame": s.frames_done, "capture_ts": cap, "recv_ts": recv}
            s.frames_done += 1
            self.fusion.update(s.info.pid, st, now)
            self.dirty.set()

    def stats(self, s: Session) -> dict:
        return {"pid": s.info.pid, "name": s.info.name, "team": s.info.team, "agent": s.info.agent,
                "connected": s.connected, "frames_in": s.frames_in, "frames_done": s.frames_done,
                "dropped": s.dropped, "engine_fps": s.state.get("engine_fps") if s.state else 0,
                "decode_ms": round(s.decode_ms, 2), "process_ms": round(s.proc_ms, 2),
                "e2e_ms": s.state.get("e2e_ms") if s.state else None}

    # ------------------------------------------------------------------ publishing
    def _broadcast(self, msg) -> None:
        for q in list(self.subscribers):
            if q.full():                    # slow commentator: drop the oldest, never block the engine
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(msg)

    async def publisher(self) -> None:
        period = 1.0 / self.match_hz
        while self.running:
            await asyncio.sleep(period)
            if self.dirty.is_set():
                self.dirty.clear()
                m = self.fusion.fuse()
                m["engine"] = {"players": {pid: self.stats(s) for pid, s in self.sessions.items()}}
                self.match = m
                self._broadcast(json.dumps(m, separators=(",", ":")))
            if self.forward_fps > 0:
                now = time.time()
                for s in self.sessions.values():
                    meta = s.last_frame_meta
                    if s.last_jpeg and meta.get("frame") != s.forward_seq and now - s.forwarded_at >= 1.0 / self.forward_fps:
                        s.forward_seq, s.forwarded_at = meta["frame"], now
                        self._broadcast(pack_frame(meta, s.last_jpeg))

    def check(self, token: Optional[str]) -> bool:
        return self.token is None or token == self.token


def create_hub_app(token: Optional[str] = None, forward_fps: float = 10.0, match_hz: float = 15.0,
                   layout: Optional[str] = None) -> FastAPI:
    # parallelism comes from one worker thread per player; keep OpenCV's own
    # thread pool at 1 so ten workers do not oversubscribe the CPU
    cv2.setNumThreads(1)
    hub = Hub(token=token, forward_fps=forward_fps, match_hz=match_hz, layout=layout)

    @asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(hub.publisher())
        yield
        hub.running = False
        task.cancel()

    app = FastAPI(title="ValoVision engine server", version="2.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.state.hub = hub

    @app.websocket("/ingest")
    async def ingest(ws: WebSocket):
        await ws.accept()
        try:
            hello = json.loads(await ws.receive_text())
            if hello.get("type") != "hello" or not hub.check(hello.get("token")):
                await ws.send_text(json.dumps({"type": "error", "error": "bad hello or token"}))
                await ws.close(code=4001)
                return
            s = hub.join(hello)
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            await ws.send_text(json.dumps({"type": "error", "error": str(e)}))
            await ws.close(code=4002)
            return
        await ws.send_text(json.dumps({"type": "welcome", "pid": s.info.pid, "team": s.info.team,
                                       "hint": {"max_width": 1280, "jpeg_quality": 80}}))
        last = time.time()
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes"):
                    hub.offer(s, msg["bytes"])
                if time.time() - last >= 1.0:
                    last = time.time()
                    await ws.send_text(json.dumps({"type": "stats", **hub.stats(s)}))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            s.connected = False

    @app.websocket("/feed")
    async def feed(ws: WebSocket):
        await ws.accept()
        try:
            sub = json.loads(await ws.receive_text())
        except Exception:
            await ws.close(code=4001)
            return
        if not hub.check(sub.get("token")):
            await ws.close(code=4001)
            return
        want_frames = bool(sub.get("frames", True))
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        hub.subscribers.add(q)
        try:
            if hub.match:
                await ws.send_text(json.dumps(hub.match))
            while True:
                msg = await q.get()
                if isinstance(msg, bytes):
                    if want_frames:
                        await ws.send_bytes(msg)
                else:
                    await ws.send_text(msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.subscribers.discard(q)

    @app.get("/api/health")
    def health():
        return {"ok": True, "players": len(hub.sessions), "subscribers": len(hub.subscribers),
                "sessions": [hub.stats(s) for s in hub.sessions.values()]}

    @app.get("/api/match")
    def match():
        return hub.match or JSONResponse({"detail": "no frames yet"}, status_code=503)

    @app.get("/api/players/{pid}/state")
    def player_state(pid: str):
        s = hub.sessions.get(pid)
        return s.state if s and s.state else JSONResponse({"detail": "unknown player or no frame"}, status_code=404)

    @app.get("/api/players/{pid}/frame.jpg")
    def player_frame(pid: str):
        s = hub.sessions.get(pid)
        if not s or not s.last_jpeg:
            return JSONResponse({"detail": "unknown player or no frame"}, status_code=404)
        return Response(s.last_jpeg, media_type="image/jpeg")

    return app
