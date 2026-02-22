#!/usr/bin/env sh
set -eu

if ! command -v codex >/dev/null 2>&1; then
  echo "codex binary not found in PATH" >&2
  exit 1
fi

APP_HOME="${APP_HOME:-/app/data/home}"
mkdir -p "$APP_HOME" "$APP_HOME/.config"

if [ -d /root/.codex ] && [ ! -e "$APP_HOME/.codex" ]; then
  cp -R /root/.codex "$APP_HOME/.codex"
fi

export HOME="$APP_HOME"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$APP_HOME/.config}"

node /app/sidecar/src/index.js &
SIDECAR_PID=$!

cleanup() {
  kill "$SIDECAR_PID" 2>/dev/null || true
}

trap cleanup INT TERM EXIT

exec uv run uvicorn app.main:app --app-dir /app/src --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8000}"
