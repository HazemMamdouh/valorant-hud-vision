import type { Slot } from "../types";
import { agentIcon } from "../util";

interface Props {
  side: "left" | "right";
  slots: Slot[];
}

/** Compact team column. Left = your team (teal), right = enemies (red). */
export function Roster({ side, slots }: Props) {
  // The 2022 HUD packs survivors towards the centre: list the living first, then empty rows.
  const ordered = [...slots].sort((a, b) => Number(b.alive) - Number(a.alive));
  const alive = slots.filter((s) => s.alive).length;
  return (
    <section className={`roster roster--${side}`} aria-label={side === "left" ? "Your team" : "Enemy team"}>
      <header className="roster__head">
        <span className="roster__count">{alive}</span>
        <span className="roster__label">{side === "left" ? "alive" : "alive"}</span>
      </header>
      <ol className="roster__list">
        {ordered.map((s) => (
          <li key={s.slot} className={`roster__row${s.alive ? "" : " is-dead"}${s.has_spike ? " has-spike" : ""}`}>
            <span className="roster__portrait">
              {s.agent && <img src={agentIcon(s.agent)} alt="" />}
            </span>
            <span className="roster__name">{s.alive ? s.agent ?? "Unknown" : ""}</span>
            {s.has_spike && <SpikeGlyph />}
          </li>
        ))}
      </ol>
    </section>
  );
}

export function SpikeGlyph({ size = 12 }: { size?: number }) {
  return (
    <svg className="spike-glyph" width={size} height={size} viewBox="0 0 12 12" aria-label="carries the spike">
      <path d="M6 0 L12 6 L6 12 L0 6 Z" />
      <path d="M6 2.2 V9.8" className="spike-glyph__core" />
    </svg>
  );
}
