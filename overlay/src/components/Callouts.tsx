import type { GameEvent, GameState } from "../types";

const SHOW_FOR = 3.5; // seconds

function describe(e: GameEvent, state: GameState): { text: string; tone: "ally" | "enemy" | "neutral" } | null {
  switch (e.type) {
    case "death":
      // an enemy going down is good news (teal); a teammate going down is red
      return { text: `${e.agent ?? "Agent"} down`, tone: e.side === "right" ? "ally" : "enemy" };
    case "spike_picked_up": {
      const s = [...state.teams.left, ...state.teams.right].find((x) => x.slot === e.slot);
      return { text: `${s?.agent ?? "Someone"} picked up the spike`, tone: "neutral" };
    }
    case "spike_dropped":
      return { text: "Spike dropped", tone: "neutral" };
    case "ult_ready":
      return { text: "Ultimate ready", tone: "ally" };
    case "ult_used":
      return { text: "Ultimate used", tone: "ally" };
    default:
      return null;
  }
}

export function Callouts({ state }: { state: GameState }) {
  const recent = (state.recent_events ?? [])
    .filter((e) => state.t - e.t >= 0 && state.t - e.t < SHOW_FOR)
    .map((e) => ({ e, d: describe(e, state) }))
    .filter((x) => x.d)
    .slice(-3);
  return (
    <ul className="callouts" aria-live="polite">
      {recent.map(({ e, d }, i) => (
        <li key={`${e.t}-${e.type}-${String(e.agent ?? e.slot ?? "")}-${i}`} className={`callout callout--${d!.tone}`}
            style={{ opacity: Math.min(1, (SHOW_FOR - (state.t - e.t)) / 0.6) }}>
          {d!.text}
        </li>
      ))}
    </ul>
  );
}
