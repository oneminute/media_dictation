#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

python3 -m pip install -r requirements.txt

python3 app.py &
APP_PID=$!

cleanup() {
  kill "$APP_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

sleep 1

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open http://127.0.0.1:8765 >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then
  open http://127.0.0.1:8765 >/dev/null 2>&1 || true
fi

wait "$APP_PID"
