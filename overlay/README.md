# ValoVision overlay

React 18 + Vite + TypeScript. A transparent 1280x720 stage that scales to the window,
meant for an OBS browser source.

```bash
npm install
npm run build     # -> dist/, served by `valovision serve` at http://127.0.0.1:8000/
npm run dev       # http://localhost:5173, proxies /ws /api /samples to :8000
```

URL parameters:

| Parameter | Effect |
|---|---|
| `?ws=ws://host:port/ws` | connect to an engine elsewhere |
| `?replay=/samples/x.analysis.json` | play recorded states instead of live |
| `&video=/samples/x.mp4` | show the video under the overlay, synced to the replay |
| `&step` | do not play; wait for `window.__valovision.setFrame(i)` (headless rendering) |
| `?debug` (or press D) | raw state JSON panel |

Components: `Roster` (team columns, alive and spike carrier), `PlayerCard` (HP, shield,
C/Q/E pips, ult, loadout), `SpikeBanner` (carrier chip or planted fuse), `Callouts`
(deaths, spike, ult), engine status chip.
