#!/usr/bin/env bash
# Start Second Observer sender (Whisper.py) inside its virtual environment.
# Usage: ./start_whisper.sh [session_id] [pc_host]
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/venv"
SESSION_ID="${1:-patient-$(date +%Y%m%d-%H%M%S)}"
PC_HOST="${2:-69.69.69.2}"
PC_PORT=8765

cd "$APP_DIR"

if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "Virtual environment not found at $VENV_DIR"
    echo "Create it with: python3 -m venv --system-site-packages venv && source venv/bin/activate && pip install sounddevice numpy piper-tts"
    exit 1
fi
if [ ! -f "$APP_DIR/Whisper.py" ]; then
    echo "Whisper.py not found in $APP_DIR"
    exit 1
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "Session : $SESSION_ID"
echo "PC      : $PC_HOST:$PC_PORT"
if ! timeout 3 bash -c "</dev/tcp/$PC_HOST/$PC_PORT" 2>/dev/null; then
    echo "WARNING: cannot reach $PC_HOST:$PC_PORT yet. Whisper.py will keep retrying."
fi

exec python "$APP_DIR/Whisper.py" "$SESSION_ID" --host "$PC_HOST" --port "$PC_PORT"
