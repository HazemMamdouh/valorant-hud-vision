import { useEffect, useRef, useState } from "react";
import type { GameState } from "./types";

export type Status = "connecting" | "live" | "offline" | "replay" | "error";

const params = new URLSearchParams(window.location.search);

function wsUrl(): string {
  const explicit = params.get("ws");
  if (explicit) return explicit;
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws`;
}

declare global {
  interface Window {
    __valovision?: { ready: boolean; frames: number; setFrame: (i: number) => void };
  }
}

/**
 * Live mode (default): subscribe to the engine WebSocket, reconnect with back-off.
 * Replay mode (`?replay=/samples/x.analysis.json`): play recorded states, either
 * on its own clock, synced to a <video> (`?video=`), or stepped externally via
 * `window.__valovision.setFrame(i)` (used to render the demo video headlessly).
 */
export function useGameState(videoRef?: React.RefObject<HTMLVideoElement>) {
  const [state, setState] = useState<GameState | null>(null);
  const [status, setStatus] = useState<Status>(params.get("replay") ? "replay" : "connecting");
  const [error, setError] = useState<string | null>(null);
  const frames = useRef<GameState[]>([]);

  // ---------------------------------------------------------------- replay
  useEffect(() => {
    const src = params.get("replay");
    if (!src) return;
    let raf = 0;
    const external = params.has("step");
    fetch(src)
      .then((r) => {
        if (!r.ok) throw new Error(`Replay file not found: ${src} (HTTP ${r.status})`);
        return r.json();
      })
      .then((data) => {
        const states: GameState[] = data.states ?? data;
        frames.current = states;
        const fps: number = data.fps ?? 30;
        window.__valovision = {
          ready: true,
          frames: states.length,
          setFrame: (i) => setState(states[Math.max(0, Math.min(states.length - 1, i))]),
        };
        if (external) {
          setState(states[0]);
          return;
        }
        const start = performance.now();
        const tick = () => {
          const v = videoRef?.current;
          const t = v && !v.paused ? v.currentTime : ((performance.now() - start) / 1000) % (states.length / fps);
          setState(states[Math.min(states.length - 1, Math.floor(t * fps))]);
          raf = requestAnimationFrame(tick);
        };
        tick();
      })
      .catch((e: Error) => {
        setStatus("error");
        setError(e.message);
      });
    return () => cancelAnimationFrame(raf);
  }, [videoRef]);

  // ---------------------------------------------------------------- live
  useEffect(() => {
    if (params.get("replay")) return;
    let sock: WebSocket | null = null;
    let retry = 0;
    let timer: number | undefined;
    let closed = false;
    const connect = () => {
      setStatus("connecting");
      sock = new WebSocket(wsUrl());
      sock.onopen = () => {
        retry = 0;
        setStatus("live");
        setError(null);
      };
      sock.onmessage = (m) => setState(JSON.parse(m.data));
      sock.onclose = () => {
        if (closed) return;
        setStatus("offline");
        setError(`Engine not reachable at ${wsUrl()}. Start it with: valovision serve`);
        timer = window.setTimeout(connect, Math.min(5000, 500 * 2 ** retry++));
      };
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      sock?.close();
    };
  }, []);

  return { state, status, error };
}

export const urlParams = params;
