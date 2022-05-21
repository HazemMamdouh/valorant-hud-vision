// Fused match state published by the engine server (relayed by the commentator server).
export interface MatchPlayer {
  pid: string;
  name: string;
  team: "A" | "B";
  agent: string | null;
  online: boolean;
  alive: boolean | null;
  has_spike: boolean;
  hp: number | null;
  shield: number | null;
  abilities: { c: number; q: number; e: number };
  ult_points: number | null;
  ult_max: number;
  ult_ready: boolean;
  loadout: { primary: string | null; secondary: string | null; active: string | null };
  latency_ms?: number | null;
}

export interface MatchEvent {
  t: number;
  type: string;
  pid?: string;
  name?: string;
  team?: string;
  agent?: string | null;
  [k: string]: unknown;
}

export interface EngineStats {
  pid: string;
  engine_fps: number;
  process_ms: number;
  decode_ms: number;
  dropped: number;
  e2e_ms: number | null;
  connected: boolean;
}

export interface MatchState {
  type: "match";
  t: number;
  teams: Record<"A" | "B", { alive: number | null; alive_agents: string[]; views: number }>;
  spike: { planted: boolean; timer: number | null; carrier_agent: string | null; carrier_pid: string | null };
  players: MatchPlayer[];
  events: MatchEvent[];
  recent_events: MatchEvent[];
  engine?: { players: Record<string, EngineStats> };
}
