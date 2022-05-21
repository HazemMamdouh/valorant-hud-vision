# valovision (engine)

Classical computer-vision engine that reads the VALORANT HUD (2022 Q1 layout) and serves
it as JSON over a WebSocket. No neural networks: template matching, colour gating, Sobel
energy, connected components and morphology.

```bash
pip install -e ".[dev]"
valovision serve --source screen          # or a video path
valovision analyze video.mp4 --workers 8
```

Full documentation: see the repository README and `docs/INSTALLATION.md`.
