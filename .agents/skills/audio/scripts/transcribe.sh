#!/usr/bin/env bash
# Тонкая bash-обёртка. Весь CLI разбор — в transcribe.py (argparse).
set -euo pipefail

AGENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ERROR: ffmpeg not found in PATH. Install: brew install ffmpeg" >&2
  exit 2
fi

if [[ ! -x "$AGENT_DIR/.venv/bin/python" ]]; then
  echo "[warm-up] создаю venv + ставлю gigaam[longform]==0.1.0 (~1-2 мин, ~1ГБ скачивания при первом запуске)..." >&2
  python3 -m venv "$AGENT_DIR/.venv"
  "$AGENT_DIR/.venv/bin/pip" install --upgrade pip >&2
  "$AGENT_DIR/.venv/bin/pip" install -r "$AGENT_DIR/requirements.txt" >&2
fi

exec "$AGENT_DIR/.venv/bin/python" "$AGENT_DIR/scripts/transcribe.py" "$@"
