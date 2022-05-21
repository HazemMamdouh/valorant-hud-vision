"""Command line interface: ``valovision <command>`` (or ``python -m valovision``)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cmd_serve(a):
    import uvicorn
    from .server import create_app
    app = create_app(source=a.source, fps=a.fps, loop=not a.no_loop, layout=a.layout, mode=a.mode,
                     agent=a.agent, name=a.name)
    print(f"ValoVision engine on http://{a.host}:{a.port}  (source={a.source})")
    print(f"  overlay  : http://{a.host}:{a.port}/        (after `npm run build` in overlay/)")
    print(f"  websocket: ws://{a.host}:{a.port}/ws")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


def cmd_engine(a):
    import uvicorn
    from .hub import create_hub_app
    app = create_hub_app(token=a.token, forward_fps=a.forward_fps, match_hz=a.match_hz, layout=a.layout)
    print(f"ValoVision ENGINE server on {a.host}:{a.port}")
    print(f"  players connect to   ws://<this-ip>:{a.port}/ingest   (valovision send ...)")
    print(f"  commentator connects ws://<this-ip>:{a.port}/feed     (valovision commentator ...)")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning", ws_max_size=16 * 2 ** 20)


def cmd_send(a):
    import asyncio
    from .sender import send
    asyncio.run(send(a.engine, a.pid, a.name or a.pid, a.team, a.agent, a.source, fps=a.fps,
                     max_width=a.max_width, quality=a.quality, token=a.token, loop=not a.no_loop,
                     duration=a.duration, start_at=a.start_at))


def cmd_commentator(a):
    import uvicorn
    from .commentator import create_commentator_app
    app = create_commentator_app(a.engine, token=a.token)
    print(f"ValoVision COMMENTATOR server on http://{a.host}:{a.port}/  (engine: {a.engine})")
    print(f"  caster UI       http://<this-ip>:{a.port}/")
    print(f"  player feeds    http://<this-ip>:{a.port}/feeds/<pid>.mjpeg")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning", ws_max_size=16 * 2 ** 20)


def cmd_analyze(a):
    from .analysis import analyze_video, save_analysis
    from .evaluate import evaluate
    res = analyze_video(a.video, workers=a.workers, layout=a.layout)
    if a.agent:
        for st in res["states"]:
            st["player"]["agent"] = st["player"].get("agent") or a.agent
    out = Path(a.out or Path(a.video).with_suffix(".analysis.json"))
    if a.groundtruth:
        gt = json.loads(Path(a.groundtruth).read_text())["frames"]
        res["accuracy_raw"] = evaluate(res["raw"], gt)
        res["accuracy_tracked"] = evaluate(res["states"], gt)
    save_analysis(res, out)
    print(f"{res['frames']} frames, {res['throughput_fps']} fps with {a.workers} worker(s); "
          f"median latency {res['latency_ms']['median']} ms; {len(res['events'])} events -> {out}")
    if a.groundtruth:
        acc = res["accuracy_tracked"]
        for k, v in acc.items():
            if not k.startswith("_"):
                print(f"  {k:22s} {v['accuracy'] * 100:6.2f} %")
        print(f"  {'overall':22s} {acc['_overall']['accuracy'] * 100:6.2f} %")
    if a.annotate:
        from .annotate import annotate_video
        from .config import load_layout
        annotate_video(a.video, res["states"], load_layout(a.layout), a.annotate)
        print(f"annotated video -> {a.annotate}")


def cmd_frame(a):
    import cv2
    from .annotate import draw_rois, draw_state
    from .pipeline import Engine
    img = cv2.imread(a.image)
    if img is None:
        sys.exit(f"cannot read {a.image}")
    eng = Engine(a.layout)
    s = eng.process(img)
    print(json.dumps(s, indent=2))
    if a.debug:
        img = cv2.resize(img, eng.layout.base_resolution)
        cv2.imwrite(a.debug, draw_state(draw_rois(img, eng.layout), eng.layout, s))


def cmd_synth(a):
    from .synth import render_video
    out = render_video(Path(a.out), Path(a.groundtruth) if a.groundtruth else None, crf=a.crf)
    print(f"synthetic 2022-Q1 HUD video -> {out}")


def cmd_synth_match(a):
    from .synth import SCENERY_DIR, render_match
    scenery = None if a.scenery == "none" else (SCENERY_DIR if a.scenery == "real" else Path(a.scenery))
    print(f"10 synchronised POVs of one replica round -> {render_match(Path(a.out), crf=a.crf, scenery=scenery)}")


def cmd_make_digits(a):
    from .glyphs import extract_digit_templates, make_digit_templates
    if a.from_image:
        x0, y0, x1, y1 = (int(v) for v in a.rect.split(","))
        print(extract_digit_templates(Path(a.from_image), (x0, y0, x1, y1), a.labels, Path(a.out)))
    else:
        print(make_digit_templates(Path(a.out) if a.out else None))


def main(argv=None):
    ap = argparse.ArgumentParser("valovision", description="Classical-CV VALORANT (2022) HUD reader")
    ap.add_argument("--layout", default=None, help="layout JSON or legacy screen_config.txt")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="single-feed mode: one screen -> engine -> overlay (dev / solo streamer)")
    s.add_argument("--source", default="screen", help="'screen', 'screen:2', a video path, or 'dir/*.png'")
    s.add_argument("--fps", type=float, default=30)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--mode", choices=["sequential", "threaded"], default="sequential")
    s.add_argument("--no-loop", action="store_true", help="do not loop video sources")
    s.add_argument("--agent", help="your agent (the player HUD does not show it)")
    s.add_argument("--name", help="your name for the overlay")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("engine", help="ENGINE server for a 10-player match (all vision runs here)")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--token", help="shared secret players/commentators must present")
    s.add_argument("--forward-fps", type=float, default=10, help="player video forwarded to commentators (0 = off)")
    s.add_argument("--match-hz", type=float, default=15, help="match-state updates per second")
    s.set_defaults(fn=cmd_engine)

    s = sub.add_parser("send", help="PLAYER sender: stream this PC's screen (or a recording) to the engine")
    s.add_argument("--engine", required=True, help="ws://ENGINE_IP:8000/ingest")
    s.add_argument("--pid", required=True, help="stable player id, e.g. p1..p10")
    s.add_argument("--name")
    s.add_argument("--team", required=True, choices=["A", "B"])
    s.add_argument("--agent", help="agent picked in the lobby (links the player to a top-bar portrait)")
    s.add_argument("--source", default="screen", help="'screen', 'screen:2', video, 'dir/*.png' or @list.txt")
    s.add_argument("--fps", type=float, default=30)
    s.add_argument("--max-width", type=int, default=1280)
    s.add_argument("--quality", type=int, default=80)
    s.add_argument("--token")
    s.add_argument("--duration", type=float)
    s.add_argument("--no-loop", action="store_true")
    s.add_argument("--start-at", type=float, help="unix time to start streaming (synchronised demos)")
    s.set_defaults(fn=cmd_send)

    s = sub.add_parser("commentator", help="COMMENTATOR server: receives state + feeds, serves the caster UI")
    s.add_argument("--engine", required=True, help="ws://ENGINE_IP:8000/feed")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=9000)
    s.add_argument("--token")
    s.set_defaults(fn=cmd_commentator)

    s = sub.add_parser("analyze", help="offline analysis of a video (+ accuracy if ground truth given)")
    s.add_argument("video")
    s.add_argument("--out")
    s.add_argument("--workers", type=int, default=1)
    s.add_argument("--groundtruth")
    s.add_argument("--annotate", help="write a debug video with ROIs + readings")
    s.add_argument("--agent", help="the recorded player's agent (not visible in the player HUD)")
    s.set_defaults(fn=cmd_analyze)

    s = sub.add_parser("frame", help="run on a single screenshot and print the state")
    s.add_argument("image")
    s.add_argument("--debug", help="write an annotated PNG")
    s.set_defaults(fn=cmd_frame)

    s = sub.add_parser("synth", help="render the synthetic 2022-Q1 HUD sample video")
    s.add_argument("--out", default="samples/sample_2022q1_30s.mp4")
    s.add_argument("--groundtruth", default="samples/sample_2022q1_30s.groundtruth.json")
    s.add_argument("--crf", type=int, default=20)
    s.set_defaults(fn=cmd_synth)

    s = sub.add_parser("synth-match", help="render 10 synchronised player POVs of one replica round")
    s.add_argument("--out", default="samples/match_replica")
    s.add_argument("--crf", type=int, default=26)
    s.add_argument("--scenery", default="real",
                   help="world behind the HUD: 'real' (2022 screenshot crops, default), 'none' (procedural) or a folder")
    s.set_defaults(fn=cmd_synth_match)

    s = sub.add_parser("make-digits", help="(re)build digit templates from the font or a real screenshot")
    s.add_argument("--out")
    s.add_argument("--from-image")
    s.add_argument("--rect", help="x0,y0,x1,y1 of the digits in the 1280x720 screenshot")
    s.add_argument("--labels", help="the digits visible in that rect, e.g. 100")
    s.set_defaults(fn=cmd_make_digits)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
