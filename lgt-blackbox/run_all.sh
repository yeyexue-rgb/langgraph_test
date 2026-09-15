#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${VENV:-$HERE/../.venv-lgt}"
PORT="${LGT_PORT:-8088}"
export LGT_FILE_ROOT="${LGT_FILE_ROOT:-$HERE/sandbox_files}"
"$VENV/bin/uvicorn" api_server:app --host 127.0.0.1 --port "$PORT" --app-dir "$HERE" >/tmp/lgt-server.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
for i in $(seq 1 30); do
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break
  sleep 1
done
"$VENV/bin/python" "$HERE/eval/run_eval.py" --api "http://127.0.0.1:$PORT" "$@"
