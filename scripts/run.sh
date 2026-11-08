#!/usr/bin/env bash
# Launch the BotOffice desktop app.
#
# Creates the virtual environment on first run, installs dependencies, then
# starts the native window. The user never needs a terminal afterwards.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
VENV="$ROOT/.venv"

if [ ! -d "$VENV" ]; then
  echo "Creating the virtual environment..."
  if command -v uv >/dev/null 2>&1; then
    uv venv "$VENV"
  else
    python -m venv "$VENV"
  fi
fi

PY="$VENV/Scripts/python.exe"
[ -x "$PY" ] || PY="$VENV/bin/python"

if [ ! -f "$VENV/.deps-ok" ]; then
  echo "Installing dependencies..."
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$PY" "PySide6==6.12.0" httpx fastapi uvicorn pyyaml
  else
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install "PySide6==6.12.0" httpx fastapi uvicorn pyyaml
  fi
  touch "$VENV/.deps-ok"
fi

echo "Starting BotOffice..."
exec "$PY" -m botoffice.gui
