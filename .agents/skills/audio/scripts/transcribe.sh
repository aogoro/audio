#!/usr/bin/env bash
set -euo pipefail

AGENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ERROR: ffmpeg not found in PATH. Install: brew install ffmpeg" >&2
  exit 2
fi

PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3.13; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON_BIN="$candidate"
    break
  fi
done
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: Python >= 3.10 required. Install: brew install python@3.12" >&2
  exit 3
fi

NEEDS_REBUILD=0
if [[ -x "$AGENT_DIR/.venv/bin/python" ]]; then
  if ! "$AGENT_DIR/.venv/bin/python" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
    NEEDS_REBUILD=1
  fi
else
  NEEDS_REBUILD=1
fi

REQ_HASH=$(shasum -a 256 "$AGENT_DIR/requirements.txt" | cut -d' ' -f1)
STAMP_FILE="$AGENT_DIR/.venv/.requirements.sha256"
if [[ "$NEEDS_REBUILD" -eq 0 ]] && { [[ ! -f "$STAMP_FILE" ]] || [[ "$(cat "$STAMP_FILE")" != "$REQ_HASH" ]]; }; then
  NEEDS_REBUILD=1
fi

if [[ "$NEEDS_REBUILD" -eq 1 ]]; then
  echo "[warm-up] пересоздаю venv ($PYTHON_BIN) + ставлю зависимости..." >&2
  rm -rf "$AGENT_DIR/.venv"
  "$PYTHON_BIN" -m venv "$AGENT_DIR/.venv"
  "$AGENT_DIR/.venv/bin/pip" install --upgrade pip >&2
  "$AGENT_DIR/.venv/bin/pip" install -r "$AGENT_DIR/requirements.txt" >&2
  "$AGENT_DIR/.venv/bin/pip" check >&2
  echo "$REQ_HASH" > "$STAMP_FILE"
fi

exec "$AGENT_DIR/.venv/bin/python" "$AGENT_DIR/scripts/transcribe.py" "$@"
