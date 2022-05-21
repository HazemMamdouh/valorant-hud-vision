import { useEffect, useRef, useState } from "react";
import type { MatchState } from "./types";

/**
 * Connects to the commentator server's /ws. Text messages carry the fused match
 * state; binary messages carry one player's JPEG frame:
 *   uint16 header length | header JSON {pid, frame, capture_ts, recv_ts} | JPEG
 * Frames become object URLs (the previous URL of that player is revoked).
 */
export function useCasterFeed(url: string) {
  const [match, setMatch] = useState<MatchState | null>(null);
  const [frames, setFrames] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<"connecting" | "live" | "offline">("connecting");
  const urls = useRef<Record<string, string>>({});

  useEffect(() => {
    let sock: WebSocket | null = null;
    let closed = false;
    let retry = 0;
    let timer: number | undefined;
    const connect = () => {
      setStatus("connecting");
      sock = new WebSocket(url);
      sock.binaryType = "arraybuffer";
      sock.onopen = () => {
        retry = 0;
        setStatus("live");
      };
      sock.onmessage = (m) => {
        if (typeof m.data === "string") {
          setMatch(JSON.parse(m.data));
          return;
        }
        const buf = m.data as ArrayBuffer;
        const n = new DataView(buf).getUint16(0);
        const hdr = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 2, n)));
        const blob = new Blob([new Uint8Array(buf, 2 + n)], { type: "image/jpeg" });
        const u = URL.createObjectURL(blob);
        const old = urls.current[hdr.pid];
        urls.current[hdr.pid] = u;
        setFrames((f) => ({ ...f, [hdr.pid]: u }));
        if (old) setTimeout(() => URL.revokeObjectURL(old), 1000);
      };
      sock.onclose = () => {
        if (closed) return;
        setStatus("offline");
        timer = window.setTimeout(connect, Math.min(5000, 500 * 2 ** retry++));
      };
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      sock?.close();
    };
  }, [url]);

  return { match, frames, status };
}
