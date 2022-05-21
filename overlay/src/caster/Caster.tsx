import { useEffect, useMemo, useState } from "react";
import { SpikeGlyph } from "../components/Roster";
import { agentIcon, clamp } from "../util";
import type { MatchEvent, MatchPlayer, MatchState } from "./types";
import { useCasterFeed } from "./useCasterFeed";
import "./caster.css";

const BASE_W = 1920;
const BASE_H = 1080;

function wsUrl(): string {
  const p = new URLSearchParams(window.location.search).get("ws");
  if (p) return p.startsWith("/") ? `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${p}` : p;
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
}

/** Caster view: everything the engine sends, for the commentator. No analysis happens here. */
export default function Caster() {
  const { match, frames, status } = useCasterFeed(useMemo(wsUrl, []));
  const [focus, setFocus] = useState<string | null>(null);
  const [fit, setFit] = useState({ s: 1, x: 0, y: 0 });
  useEffect(() => {
    const f = () => {
      const s = Math.min(window.innerWidth / BASE_W, window.innerHeight / BASE_H);
      setFit({ s, x: (window.innerWidth - BASE_W * s) / 2, y: (window.innerHeight - BASE_H * s) / 2 });
    };
    f();
    window.addEventListener("resize", f);
    return () => window.removeEventListener("resize", f);
  }, []);

  const players = match?.players ?? [];
  const teamA = players.filter((p) => p.team === "A");
  const teamB = players.filter((p) => p.team === "B");
  const focused = players.find((p) => p.pid === focus) ?? players.find((p) => p.alive) ?? players[0];

  return (
    <div className="caster-viewport">
      <div className="caster" style={{ transform: `translate(${fit.x}px, ${fit.y}px) scale(${fit.s})` }}>
        <MatchBar match={match} />
        <div className="caster__cols">
          <TeamColumn side="A" players={teamA} frames={frames} focus={focused?.pid} onFocus={setFocus} match={match} />
          <div className="caster__center">
            {focused ? <Focus p={focused} frame={frames[focused.pid]} match={match} /> : <Empty status={status} />}
            <EventLog events={match?.recent_events ?? []} players={players} />
          </div>
          <TeamColumn side="B" players={teamB} frames={frames} focus={focused?.pid} onFocus={setFocus} match={match} />
        </div>
        <footer className="caster__foot">
          <span className={`dot dot--${status}`} />
          <span>{status === "live" ? "Receiving from the engine server" : status === "connecting" ? "Connecting to the commentator server" : "Commentator server unreachable, retrying"}</span>
          <span className="caster__foot-stats">{engineSummary(match)}</span>
        </footer>
      </div>
    </div>
  );
}

function engineSummary(m: MatchState | null) {
  if (!m?.engine) return "";
  const s = Object.values(m.engine.players);
  if (!s.length) return "";
  const fps = s.reduce((a, x) => a + (x.engine_fps || 0), 0);
  const proc = s.reduce((a, x) => a + (x.process_ms || 0), 0) / s.length;
  return `${s.length} feeds · ${fps.toFixed(0)} frames/s analysed · ${proc.toFixed(1)} ms per frame`;
}

function MatchBar({ match }: { match: MatchState | null }) {
  const a = match?.teams.A;
  const b = match?.teams.B;
  return (
    <header className="matchbar">
      <div className="matchbar__team matchbar__team--a">
        <span className="matchbar__name">Team A</span>
        <span className="matchbar__alive">{a?.alive ?? "–"}</span>
        <span className="matchbar__label">alive</span>
      </div>
      <div className="matchbar__mid">
        <span className={`live${match ? "" : " live--off"}`}><i />Live</span>
        {match?.spike.planted ? (
          <div className="matchbar__fuse">
            <SpikeGlyph size={18} />
            <span>Spike planted</span>
            <b>{(match.spike.timer ?? 45).toFixed(1)}</b>
            <i style={{ transform: `scaleX(${(match.spike.timer ?? 45) / 45})` }} />
          </div>
        ) : match?.spike.carrier_agent ? (
          <div className="matchbar__carrier">
            <SpikeGlyph />
            {match.players.find((p) => p.pid === match.spike.carrier_pid)?.name ?? match.spike.carrier_agent} has the spike
          </div>
        ) : (
          <div className="matchbar__carrier matchbar__carrier--none">Spike not seen</div>
        )}
      </div>
      <div className="matchbar__team matchbar__team--b">
        <span className="matchbar__label">alive</span>
        <span className="matchbar__alive">{b?.alive ?? "–"}</span>
        <span className="matchbar__name">Team B</span>
      </div>
    </header>
  );
}

function TeamColumn(props: { side: "A" | "B"; players: MatchPlayer[]; frames: Record<string, string>;
  focus?: string; onFocus: (pid: string) => void; match: MatchState | null }) {
  return (
    <section className={`col col--${props.side.toLowerCase()}`} aria-label={`Team ${props.side}`}>
      {props.players.map((p) => (
        <Tile key={p.pid} p={p} frame={props.frames[p.pid]} active={p.pid === props.focus}
              onClick={() => props.onFocus(p.pid)} stats={props.match?.engine?.players[p.pid]} />
      ))}
    </section>
  );
}

function Tile({ p, frame, active, onClick, stats }: { p: MatchPlayer; frame?: string; active: boolean;
  onClick: () => void; stats?: { engine_fps: number; process_ms: number } }) {
  const dead = p.alive === false;
  return (
    <button className={`tile${active ? " is-active" : ""}${dead ? " is-dead" : ""}${!p.online ? " is-offline" : ""}`}
            onClick={onClick}>
      <div className="tile__feed">
        {frame ? <img src={frame} alt={`${p.name} live feed`} /> : <span className="tile__nofeed">No video yet</span>}
        {dead && <span className="tile__badge">Dead, spectating</span>}
        {!p.online && <span className="tile__badge tile__badge--off">Offline</span>}
      </div>
      <div className="tile__info">
        <div className="tile__who">
          {p.agent && <img className="tile__agent" src={agentIcon(p.agent)} alt="" />}
          <span className="tile__name">{p.name}</span>
          {p.has_spike && <SpikeGlyph />}
        </div>
        <div className="tile__agentname">{p.agent ?? "Agent not registered"}</div>
        <Vital value={p.hp} max={100} kind="hp" />
        <Vital value={p.shield} max={50} kind="sh" />
        <Kit p={p} />
        <div className="tile__loadout">
          {p.loadout.primary && <span className={p.loadout.active === "primary" ? "on" : ""}>{p.loadout.primary}</span>}
          {p.loadout.secondary && <span className={p.loadout.active === "secondary" ? "on" : ""}>{p.loadout.secondary}</span>}
          {stats && <span className="tile__fps">{stats.engine_fps.toFixed(0)} fps</span>}
        </div>
      </div>
    </button>
  );
}

function Vital({ value, max, kind }: { value: number | null; max: number; kind: "hp" | "sh" }) {
  return (
    <div className={`vbar vbar--${kind}`}>
      <span>{value ?? "–"}</span>
      <div><i style={{ width: `${(clamp(value ?? 0, 0, max) / max) * 100}%` }} /></div>
    </div>
  );
}

function Kit({ p }: { p: MatchPlayer }) {
  const ult = p.ult_ready ? p.ult_max : p.ult_points ?? 0;
  return (
    <div className="kit2">
      {(["c", "q", "e"] as const).map((k) => (
        <span key={k} className="kit2__key">
          {k.toUpperCase()}
          {Array.from({ length: Math.max(p.abilities[k], 0) }, (_, i) => <i key={i} />)}
        </span>
      ))}
      <span className={`kit2__ult${p.ult_ready ? " is-ready" : ""}`}>
        X {p.ult_ready ? "ready" : `${ult}/${p.ult_max}`}
      </span>
    </div>
  );
}

function Focus({ p, frame, match }: { p: MatchPlayer; frame?: string; match: MatchState | null }) {
  return (
    <div className="focus">
      <div className="focus__feed">
        {frame ? <img src={frame} alt={`${p.name} live feed, focused`} /> : <span className="tile__nofeed">No video yet</span>}
        <div className="focus__label">
          <span className={`focus__team focus__team--${p.team.toLowerCase()}`}>Team {p.team}</span>
          <b>{p.name}</b> {p.agent && <span>{p.agent}</span>}
          {p.alive === false && <span className="focus__dead">dead, this feed shows a teammate</span>}
        </div>
      </div>
      <div className="focus__strip">
        <Vital value={p.hp} max={100} kind="hp" />
        <Vital value={p.shield} max={50} kind="sh" />
        <Kit p={p} />
        <span className="focus__lat">{match?.engine?.players[p.pid]?.e2e_ms != null ? `engine delay ${match.engine.players[p.pid].e2e_ms} ms` : ""}</span>
      </div>
    </div>
  );
}

function describe(e: MatchEvent, players: MatchPlayer[]): string | null {
  const who = e.name ?? players.find((p) => p.pid === e.pid)?.name ?? e.agent ?? "Someone";
  switch (e.type) {
    case "death": return `${who} (${e.agent ?? "?"}) died`;
    case "spike_planted": return "Spike planted";
    case "spike_picked_up": return `${who} picked up the spike`;
    case "spike_dropped": return `${who} dropped the spike`;
    case "ult_ready": return `${who}'s ultimate is ready`;
    case "ult_used": return `${who} used their ultimate`;
    case "ability_used": return `${who} used ${e.key}`;
    case "damage": return `${who} took ${e.amount} damage (${e.hp} HP)`;
    default: return null;
  }
}

function EventLog({ events, players }: { events: MatchEvent[]; players: MatchPlayer[] }) {
  const rows = events.map((e) => ({ e, text: describe(e, players) })).filter((x) => x.text)
    .sort((a, b) => b.e.t - a.e.t).slice(0, 7);
  return (
    <ol className="elog" aria-label="Match events">
      {rows.length === 0 && <li className="elog__empty">Events appear here as the engine detects them</li>}
      {rows.map(({ e, text }, i) => (
        <li key={`${e.t}-${e.type}-${e.pid ?? ""}-${String(e.key ?? "")}-${i}`} className={`elog__row elog__row--${e.team === "A" ? "a" : e.team === "B" ? "b" : "n"}`}>
          <span className="elog__t">{e.t.toFixed(1)}s</span>{text}
        </li>
      ))}
    </ol>
  );
}

function Empty({ status }: { status: string }) {
  return (
    <div className="focus focus--empty">
      <strong>{status === "live" ? "Waiting for the first player feed" : "Connecting to the commentator server"}</strong>
      <span>Players start sending with <code>valovision send --engine ws://ENGINE:8000/ingest …</code></span>
    </div>
  );
}
