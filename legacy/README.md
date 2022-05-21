# Recovered 2022 engine

Decompiled from the May 2022 `server.exe` (PyInstaller 4.10, CPython 3.9) with pycdc/pycdas.
The logic is kept as it was, including its bugs, so it can be benchmarked and compared
against v2. See [docs/ORIGINAL_ANALYSIS.md](../docs/ORIGINAL_ANALYSIS.md).

It expects to run from a folder containing `Engine/screen_config.txt` and `Engine/templates/`.
`tools/benchmark.py` and `tools/robustness.py` assemble that folder in a temp directory
automatically. They need Tesseract installed (`pip install -e "engine[legacy]"` plus the
Tesseract binary).

The Angular `chat-example` client from 2022 is not included: it was a stock Socket.IO chat
demo that displayed the engine's JSON as chat messages. The React overlay in `overlay/`
replaces it.
