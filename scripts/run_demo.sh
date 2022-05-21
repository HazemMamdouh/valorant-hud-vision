#!/usr/bin/env bash
# Build the overlay if needed and serve the sample round as if it were the screen.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f overlay/dist/index.html ]; then
  (cd overlay && npm install && npm run build)
fi
echo "Overlay: http://127.0.0.1:8000/   (press D for raw JSON)"
exec valovision serve --source samples/sample_2022q1_30s.mp4 "$@"
