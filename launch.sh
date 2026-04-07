#!/bin/bash
# PhotoSync launcher
# Starts the FastAPI backend and opens the UI in the default browser.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND="$SCRIPT_DIR/frontend/index.html"
VENV="$SCRIPT_DIR/.venv"
PORT=8000

# Check Python
if ! command -v python3 &>/dev/null; then
  osascript -e 'display alert "Python 3 not found" message "Please install Python 3 from python.org"'
  exit 1
fi

# Create venv if it doesn't exist
if [ ! -d "$VENV" ]; then
  echo "Setting up environment (first run only)…"
  python3 -m venv "$VENV"
fi

# Activate venv
source "$VENV/bin/activate"

# Install dependencies if needed
if ! python3 -c "import fastapi, uvicorn, osxphotos" 2>/dev/null; then
  echo ""
  echo "First run: installing dependencies (this takes about a minute)…"
  echo ""
  pip install fastapi uvicorn osxphotos
  echo ""
  echo "Done. Starting PhotoSync…"
  echo ""
fi

# Kill any existing instance on this port
lsof -ti tcp:$PORT | xargs kill -9 2>/dev/null || true
sleep 0.5

# Start backend in background
python3 -m uvicorn main:app --host 127.0.0.1 --port $PORT --app-dir "$SCRIPT_DIR/backend" &
BACKEND_PID=$!

# Wait for it to be ready
for i in {1..20}; do
  curl -s http://localhost:$PORT/api/status >/dev/null 2>&1 && break
  sleep 0.3
done

# Open the frontend HTML directly in browser
open "$FRONTEND"

# Keep alive and clean up on exit
trap "kill $BACKEND_PID 2>/dev/null" EXIT
wait $BACKEND_PID
