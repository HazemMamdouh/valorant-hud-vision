// Shape of one state message from the engine (`/ws` or analysis JSON).
export interface Slot {
  slot: number;
  agent: string | null;
  alive: boolean;
  has_spike: boolean;
}

export interface GameEvent {
  t: number;
  type:
    | "death" | "revive" | "spike_planted" | "spike_dropped" | "spike_picked_up"
    | "ability_used" | "ult_ready" | "ult_used" | "ult_point" | "damage"
    | "shield_broken" | "weapon_switch";
  [k: string]: unknown;
}

export interface GameState {
  frame: number;
  t: number;
  player: {
    agent: string | null;
    team: "ally" | "enemy";
    hp: number | null;
    shield: number | null;
    abilities: { c: number; q: number; e: number };
    ult_points: number | null;
    ult_max: number;
    ult_ready: boolean;
    max_charges: { c: number; q: number; e: number; x: number };
  };
  loadout: { primary: string | null; secondary: string | null; active: "primary" | "secondary" | null };
  teams: { left: Slot[]; right: Slot[] };
  spike: { planted: boolean; carrier_slot: number | null; timer: number | null };
  alive_count?: { left: number; right: number };
  events: GameEvent[];
  recent_events?: GameEvent[];
  latency_ms?: number;
  engine?: { fps: number; latency_ms: number | null; source: string };
}
