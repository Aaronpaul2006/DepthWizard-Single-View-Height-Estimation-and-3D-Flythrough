#!/usr/bin/env sh
# DepthWizard in local web mode: backend + viewer on http://127.0.0.1:8000; the browser opens by
# itself once the model has loaded. Fallback for the desktop app. Needs the one-time setup in
# README.md (Quickstart). Extra arguments go to scripts/serve.py, e.g. --port 8001.
cd "$(dirname "$0")" || exit 1
PY=.venv/bin/python
[ -x "$PY" ] || PY=.venv/Scripts/python.exe
if [ ! -x "$PY" ]; then
  echo "The Python environment is missing. Follow the Quickstart in README.md first."
  exit 1
fi
if [ ! -f viewer/dist/index.html ]; then
  echo "The viewer is not built. Run: (cd viewer && npm ci && npm run build)"
  exit 1
fi
exec "$PY" scripts/serve.py "$@"
