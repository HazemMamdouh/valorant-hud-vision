import { useEffect, useRef, useState } from "react";
import type { GameState } from "../types";
import { agentIcon, clamp } from "../util";

/** Telemetry for the player whose HUD is being read. */
export function PlayerCard({ state }: { state: GameState }) {
  const p = state.player;
  const lo = state.loadout;
  const hp = p.hp ?? 0;
  const sh = p.shield ?? 0;

  // brief red flash on the HP bar when damage lands
  const prevHp = useRef(hp);
  const [hit, setHit] = useState(0);
  useEffect(() => {
    if (hp < prevHp.current) setHit(prevHp.current - hp);
    prevHp.current = hp;
  }, [hp]);
  useEffect(() => {
    if (!hit) return;
    const t = window.setTimeout(() => setHit(0), 700);
    return () => window.clearTimeout(t);
  }, [hit]);

  const ultMax = p.ult_max || 7;
  const ultPts = p.ult_ready ? ultMax : p.ult_points ?? 0;

  return (
    <section className="player" aria-label="Player telemetry">
      <div className="player__id">
        {p.agent && <img className="player__portrait" src={agentIcon(p.agent)} alt="" />}
        <div>
          <div className="player__agent">{p.agent ?? "Agent not set"}</div>
          <div className="player__loadout">
            <Weapon name={lo.primary} active={lo.active === "primary"} />
            <Weapon name={lo.secondary} active={lo.active === "secondary"} />
          </div>
        </div>
      </div>

      <div className="vital">
        <span className="vital__num">{p.hp ?? "–"}</span>
        <div className={`bar bar--hp${hit ? " is-hit" : ""}`}>
          <i style={{ width: `${clamp(hp, 0, 100)}%` }} />
        </div>
        {hit > 0 && <span className="vital__hit">−{hit}</span>}
      </div>
      <div className="vital vital--shield">
        <span className="vital__num">{sh}</span>
        <div className="bar bar--shield">
          <i style={{ width: `${(clamp(sh, 0, 50) / 50) * 100}%` }} />
        </div>
      </div>

      <div className="kit">
        {(["c", "q", "e"] as const).map((k) => (
          <div className="kit__key" key={k}>
            <span className="kit__letter">{k.toUpperCase()}</span>
            <span className="kit__pips">
              {Array.from({ length: p.max_charges?.[k] ?? 2 }, (_, i) => (
                <i key={i} className={i < p.abilities[k] ? "on" : ""} />
              ))}
            </span>
          </div>
        ))}
        <div className={`kit__key kit__key--ult${p.ult_ready ? " is-ready" : ""}`}>
          <span className="kit__letter">X</span>
          <span className="kit__ult">
            {Array.from({ length: ultMax }, (_, i) => (
              <i key={i} className={i < ultPts ? "on" : ""} />
            ))}
          </span>
          {p.ult_ready && <span className="kit__ready">Ready</span>}
        </div>
      </div>
    </section>
  );
}

function Weapon({ name, active }: { name: string | null; active: boolean }) {
  if (!name) return null;
  return <span className={`weapon${active ? " is-active" : ""}`}>{name}</span>;
}
