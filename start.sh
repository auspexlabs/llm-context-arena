#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
API_HOST="${CURIA_API_HOST:-127.0.0.1}"
API_PORT="${CURIA_API_PORT:-8001}"
WEB_HOST="${CURIA_WEB_HOST:-127.0.0.1}"

declare -a CURIA_PIDS=()

stop_curia() {
  local pid
  for pid in "${CURIA_PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait "${CURIA_PIDS[@]:-}" 2>/dev/null || true
}

trap stop_curia EXIT INT TERM

cd "$ROOT_DIR"
echo "Curia API:         http://${API_HOST}:${API_PORT}"
uv run uvicorn backend.main:app --host "$API_HOST" --port "$API_PORT" &
CURIA_PIDS+=("$!")

cd "$ROOT_DIR/frontend"
echo "Curia Observatory: http://${WEB_HOST}:5173"
npm run dev -- --host "$WEB_HOST" &
CURIA_PIDS+=("$!")

echo "Press Ctrl+C to stop Curia."
wait -n "${CURIA_PIDS[@]}"
