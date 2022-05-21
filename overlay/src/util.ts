export function agentIcon(name: string): string {
  return `${import.meta.env.BASE_URL}agents/${name.replace("/", "")}.png`;
}

export function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}
