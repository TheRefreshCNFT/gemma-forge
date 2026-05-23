#!/bin/bash
# Gemma Forge — one-command installer + launcher.
#
# Checks for every external tool the harness uses and installs anything
# missing, then starts the server. Idempotent: rerunning is a no-op once
# everything is in place. macOS only.
#
# Tools installed / verified by this script:
#   - Homebrew (prompts to install if missing)
#   - Ollama (brew install ollama, brew services start ollama)
#   - Node.js 22 (brew install node@22) — needed for SocratiCode MCP
#   - Docker Desktop (brew install --cask docker) — needed for SocratiCode Qdrant
#   - Python venv + requirements.txt (flask, scrapling[all], huggingface_hub, etc.)
#   - Playwright browsers (via `scrapling install --force`)
#   - Axon CLI (pip install axoniq into the venv)
#   - SocratiCode (npm install socraticode@latest into ~/.gforge/tools/)
#   - Bundled protocol skills (skills/* → ~/.gforge/harness/skills/)
#
# Model pulls (Gemma 4 etc.) happen in-app via the harness UI or `ollama pull`
# directly. The harness supports HuggingFace repo IDs (e.g. google/gemma-4-E2B)
# through the Settings → Provision model card.

set -euo pipefail

PROJECT_ROOT="${GFORGE_PROJECT_ROOT:-$(cd "$(dirname "$0")" && pwd)}"
VENV_PATH="${GFORGE_VENV:-$PROJECT_ROOT/.venv}"
GFORGE_HOME="${GFORGE_HOME:-$HOME/.gforge}"
GFORGE_TOOLS_ROOT="${GFORGE_TOOLS_ROOT:-$GFORGE_HOME/tools}"
HARNESS_SKILLS_DIR="$GFORGE_HOME/harness/skills"

cd "$PROJECT_ROOT"

# --- Helpers ---------------------------------------------------------------

step() { printf "\n\033[1;34m[forge install]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[forge warn]\033[0m %s\n" "$*"; }
fail() { printf "\033[1;31m[forge fail]\033[0m %s\n" "$*" >&2; exit 1; }

is_macos() { [[ "$(uname -s)" == "Darwin" ]]; }
have()     { command -v "$1" >/dev/null 2>&1; }

is_macos || fail "This installer is macOS-only. Linux/Windows users: see the README for manual setup."

# --- 1. Homebrew -----------------------------------------------------------

if ! have brew; then
    step "Installing Homebrew (one-time)..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for the rest of this shell on Apple Silicon
    if [ -x /opt/homebrew/bin/brew ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x /usr/local/bin/brew ]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
fi

# --- 2. Ollama -------------------------------------------------------------

if ! have ollama; then
    step "Installing Ollama via Homebrew..."
    brew install ollama
fi

# Start Ollama service if not already serving on port 11434.
if ! curl -sf --max-time 2 http://localhost:11434/api/version >/dev/null 2>&1; then
    step "Starting Ollama service..."
    brew services start ollama >/dev/null 2>&1 || true
    # Wait briefly for it to come up.
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        sleep 1
        if curl -sf --max-time 2 http://localhost:11434/api/version >/dev/null 2>&1; then
            break
        fi
    done
fi

# Note: models are pulled in-app via the harness Settings → Provision model
# card (supports HuggingFace repo IDs like google/gemma-4-E2B) or directly
# via `ollama pull <name>`. Not auto-pulled here.

# --- 3. Node.js (for SocratiCode MCP) --------------------------------------

if ! have node; then
    step "Installing Node.js 22 via Homebrew..."
    brew install node@22
    brew link --force --overwrite node@22 >/dev/null 2>&1 || true
fi

# --- 4. Docker Desktop (for SocratiCode Qdrant) ----------------------------

if ! have docker; then
    step "Installing Docker Desktop via Homebrew cask..."
    brew install --cask docker
    warn "Docker Desktop was just installed. Open Docker.app once so it can"
    warn "grant kernel permissions, then re-run this script. The Forge will"
    warn "boot without Docker, but SocratiCode card will be unavailable."
fi

# --- 5. Python venv + deps -------------------------------------------------

if [ ! -d "$VENV_PATH" ]; then
    step "Creating Python venv at $VENV_PATH..."
    python3 -m venv "$VENV_PATH"
fi

# shellcheck disable=SC1091
source "$VENV_PATH/bin/activate"
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt >/dev/null

# --- 6. Playwright browsers (via scrapling) --------------------------------

if [ ! -f "$VENV_PATH/.scrapling-browsers-installed" ]; then
    step "Installing scrapling Playwright browsers (one-time, ~1-2 min)..."
    scrapling install --force && touch "$VENV_PATH/.scrapling-browsers-installed"
fi

# --- 7. Axon CLI (axoniq on PyPI) ------------------------------------------

if ! python -m pip show axoniq >/dev/null 2>&1; then
    step "Installing Axon (axoniq) into venv..."
    python -m pip install axoniq >/dev/null
fi

# --- 8. SocratiCode (npm) --------------------------------------------------

SOCRATICODE_BIN="$GFORGE_TOOLS_ROOT/node_modules/.bin/socraticode"
if [ ! -x "$SOCRATICODE_BIN" ]; then
    if have npm; then
        step "Installing SocratiCode MCP into $GFORGE_TOOLS_ROOT..."
        mkdir -p "$GFORGE_TOOLS_ROOT"
        npm install --prefix "$GFORGE_TOOLS_ROOT" socraticode@latest >/dev/null 2>&1 \
            && echo "SocratiCode installed: $SOCRATICODE_BIN" \
            || warn "SocratiCode install via npm failed. The harness will retry on first use."
    else
        warn "npm not on PATH — skipping SocratiCode preinstall. The harness will retry."
    fi
fi

# --- 9. Stage bundled protocol skills --------------------------------------

mkdir -p "$HARNESS_SKILLS_DIR"
if [ -d "$PROJECT_ROOT/skills" ]; then
    for skill_dir in "$PROJECT_ROOT/skills"/*/; do
        [ -d "$skill_dir" ] || continue
        skill_name="$(basename "$skill_dir")"
        if [ ! -d "$HARNESS_SKILLS_DIR/$skill_name" ]; then
            step "Staging skill: $skill_name"
            cp -R "$skill_dir" "$HARNESS_SKILLS_DIR/$skill_name"
        fi
    done
fi

# --- 10. Launch ------------------------------------------------------------

export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

step "All dependencies verified. Launching Gemma Forge Harness at http://127.0.0.1:5005/"
python -m chat.server
