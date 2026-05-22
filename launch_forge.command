#!/bin/bash
set -euo pipefail

PROJECT_ROOT="${GFORGE_PROJECT_ROOT:-$(cd "$(dirname "$0")" && pwd)}"
VENV_PATH="${GFORGE_VENV:-$PROJECT_ROOT/.venv}"

cd "$PROJECT_ROOT"

if [ ! -d "$VENV_PATH" ]; then
    python3 -m venv "$VENV_PATH"
fi

source "$VENV_PATH/bin/activate"
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt >/dev/null

# Scrapling needs Playwright browser dependencies installed once per venv.
# Idempotent — `--force` is safe to rerun and only refetches missing pieces.
if [ ! -f "$VENV_PATH/.scrapling-browsers-installed" ]; then
    echo "Installing scrapling browser dependencies (one-time, ~1-2 min)..."
    scrapling install --force && touch "$VENV_PATH/.scrapling-browsers-installed"
fi

export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

echo "Launching Gemma Forge Harness at http://127.0.0.1:5005/"
python -m chat.server
