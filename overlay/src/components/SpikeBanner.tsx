import type { GameState } from "../types";
import { SpikeGlyph } from "./Roster";

const FUSE = 45; // seconds, 2022

/** The one loud element: planted-spike fuse. Quiet carrier chip otherwise. */
export function SpikeBanner({ state }: { state: GameState }) {
  const { spike } = state;
  if (spike.planted) {
    const left = spike.timer ?? FUSE;
    const urgent = left <= 10;
    return (
      <div className={`fuse${urgent ? " is-urgent" : ""}`} role="status">
        <SpikeGlyph size={16} />
        <span className="fuse__label">Spike planted</span>
        <span className="fuse__time">{left.toFixed(left < 10 ? 1 : 0)}</span>
        <div className="fuse__track">
          <i style={{ transform: `scaleX(${left / FUSE})` }} />
        </div>
      </div>
    );
  }
  const all = [...state.teams.left, ...state.teams.right];
  const carrier = all.find((s) => s.slot === spike.carrier_slot);
  if (!carrier) return null;
  return (
    <div className={`carrier carrier--${carrier.slot <= 5 ? "ally" : "enemy"}`} role="status">
      <SpikeGlyph />
      <span>{carrier.agent ?? `Slot ${carrier.slot}`} has the spike</span>
    </div>
  );
}
