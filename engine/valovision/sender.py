"""Player-side sender: capture -> downscale -> JPEG -> engine. No analysis.

Runs on each player's PC (or, for demos, replays a recording / screenshot
folder). The only image operations are transport ones: resize to at most
1280 px wide (the engine's design resolution, ~2.3x fewer pixels than 1080p)
and JPEG encoding. If the link is slow the engine drops stale frames, so the
sender never waits for acknowledgements.

    valovision send --engine ws://ENGINE_IP:8000/ingest --pid p3 --name Mona --team A --agent Killjoy
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

import cv2

from .hub import FRAME_HDR
from .sources import open_source


def encode(frame, max_width: int = 1280, quality: int = 80) -> bytes:
    h, w = frame.shape[:2]
    if w > max_width:
        frame = cv2.resize(frame, (max_width, int(round(h * max_width / w))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


async def send(engine_url: str, pid: str, name: str, team: str, agent: Optional[str], source: str,
               fps: float = 30.0, max_width: int = 1280, quality: int = 80, token: Optional[str] = None,
               loop: bool = True, duration: Optional[float] = None, verbose: bool = True,
               time_offset: float = 0.0, start_at: Optional[float] = None) -> dict:
    """Stream until the source ends (or `duration` seconds). Reconnects with back-off."""
    import websockets
    if start_at:                      # demo only: line several senders up on one wall-clock instant
        await asyncio.sleep(max(0.0, start_at - time.time()))
    src = open_source(source, realtime=True, loop=loop, fps=fps)
    hello = {"type": "hello", "pid": pid, "name": name, "team": team, "agent": agent, "token": token}
    sent, t_start, backoff = 0, time.time(), 0.5
    frames = iter(src)
    period = 1.0 / fps
    while True:
        try:
            async with websockets.connect(engine_url, max_size=None, ping_interval=10) as ws:
                await ws.send(json.dumps(hello))
                welcome = json.loads(await ws.recv())
                if welcome.get("type") != "welcome":
                    raise RuntimeError(welcome.get("error", "rejected"))
                if verbose:
                    print(f"[{pid}] connected to {engine_url} as {name} (team {team}, {agent})")
                backoff = 0.5

                async def drain():
                    async for m in ws:               # engine stats; printed occasionally
                        if verbose and isinstance(m, str) and sent % (int(fps) * 5) < 2:
                            st = json.loads(m)
                            if st.get("type") == "stats":
                                print(f"[{pid}] engine: {st['engine_fps']} fps, process {st['process_ms']} ms, "
                                      f"dropped {st['dropped']}")
                drainer = asyncio.create_task(drain())
                last = 0.0
                passthrough = getattr(src, "files", None) and all(f.lower().endswith((".jpg", ".jpeg"))
                                                                  for f in src.files)
                if passthrough:     # pre-encoded JPEGs (recordings/demos): forward bytes as they are
                    cache = {f: open(f, "rb").read() for f in set(src.files)}
                    i = 0
                    t_next = time.time()
                    while True:
                        f = src.files[i % len(src.files)]
                        i += 1
                        if not loop and i > len(src.files):
                            return {"pid": pid, "sent": sent}
                        await ws.send(FRAME_HDR.pack(time.time() + time_offset) + cache[f])
                        sent += 1
                        if duration and time.time() - t_start >= duration:
                            return {"pid": pid, "sent": sent}
                        t_next += period
                        await asyncio.sleep(max(0.0, t_next - time.time()))
                try:
                    while True:
                        # sources pace themselves in real time (blocking) -> read in a thread
                        item = await asyncio.to_thread(next, frames, None)
                        if item is None:
                            break
                        frame = item[2]
                        now = time.time()
                        if now - last < period * 0.95:    # skip frames to hold the target fps
                            continue
                        last = now
                        payload = FRAME_HDR.pack(now + time_offset) + encode(frame, max_width, quality)
                        await ws.send(payload)
                        sent += 1
                        if duration and now - t_start >= duration:
                            return {"pid": pid, "sent": sent}
                    return {"pid": pid, "sent": sent}
                finally:
                    drainer.cancel()
        except (OSError, RuntimeError, Exception) as e:   # websockets.ConnectionClosed etc.
            if duration and time.time() - t_start >= duration:
                return {"pid": pid, "sent": sent}
            if verbose:
                print(f"[{pid}] connection problem ({type(e).__name__}: {e}); retrying in {backoff:.1f}s")
            await asyncio.sleep(backoff)
            backoff = min(5.0, backoff * 2)
