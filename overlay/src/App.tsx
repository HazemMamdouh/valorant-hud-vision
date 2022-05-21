import { useEffect, useRef, useState } from "react";
import { Callouts } from "./components/Callouts";
import { PlayerCard } from "./components/PlayerCard";
import { Roster } from "./components/Roster";
import { SpikeBanner } from "./components/SpikeBanner";
import { urlParams, useGameState } from "./useGameState";

const BASE_W = 1280;
const BASE_H = 720;

/** Scale the 1280x720 design stage to whatever size OBS / the browser gives us. */
function useStageScale() {
  const [s, setS] = useState({ s: 1, x: 0, y: 0 });
  useEffect(() => {
    const f = () => {
      const k = Math.min(window.innerWidth / BASE_W, window.innerHeight / BASE_H);
      setS({ s: k, x: (window.innerWidth - BASE_W * k) / 2, y: (window.innerHeight - BASE_H * k) / 2 });
    };
    f();
    window.addEventListener("resize", f);
    return () => window.removeEventListener("resize", f);
  }, []);
  return s;
}

export default function App() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const { state, status, error } = useGameState(videoRef);
  const scale = useStageScale();
  const video = urlParams.get("video");
  const [debug, setDebug] = useState(urlParams.has("debug"));

  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key.toLowerCase() === "d" && setDebug((v) => !v);
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);

  return (
    <div className="viewport">
      <div className="stage" style={{ transform: `translate(${scale.x}px, ${scale.y}px) scale(${scale.s})` }}>
        {video && <video ref={videoRef} className="stage__video" src={video} autoPlay muted loop playsInline />}
        {state ? (
          <>
            <Roster side="left" slots={state.teams.left} />
            <Roster side="right" slots={state.teams.right} />
            <div className="center-top">
              <SpikeBanner state={state} />
              <Callouts state={state} />
            </div>
            <PlayerCard state={state} />
          </>
        ) : (
          status !== "replay" && <Waiting status={status} error={error} />
        )}
        <EngineChip status={status} latency={state?.engine?.latency_ms ?? state?.latency_ms} fps={state?.engine?.fps} />
        {debug && state && <pre className="debug">{JSON.stringify(state, null, 1)}</pre>}
      </div>
    </div>
  );
}

function Waiting({ status, error }: { status: string; error: string | null }) {
  return (
    <div className="waiting" role="status">
      <strong>{status === "connecting" ? "Connecting to the engine" : "Engine offline"}</strong>
      {error && <span>{error}</span>}
    </div>
  );
}

function EngineChip({ status, latency, fps }: { status: string; latency?: number | null; fps?: number }) {
  return (
    <div className={`chip chip--${status}`}>
      <i className="chip__dot" />
      <span>ValoVision</span>
      {latency != null && <span className="chip__num">{latency.toFixed(1)} ms</span>}
      {fps ? <span className="chip__num">{fps.toFixed(0)} fps</span> : null}
      {status === "replay" && <span>replay</span>}
    </div>
  );
}
