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
#   - Python 3.13 venv + requirements.txt (flask, scrapling[all], huggingface_hub, etc.)
#   - Playwright browsers (via `scrapling install --force`)
#   - Axon CLI (pip install axoniq into the venv)
#   - SocratiCode (npm install socraticode@latest into ~/.gforge/tools/)
#   - Bundled protocol skills (skills/* → ~/.gforge/harness/skills/)
#   - Default Forge Brain model (`gemma4:e4b` copied to `gemma-4-e4b-it`)
#   - Embedding model + SocratiCode/Qdrant index + Axon project index

set -euo pipefail

PROJECT_ROOT="${GFORGE_PROJECT_ROOT:-$(cd "$(dirname "$0")" && pwd)}"
VENV_PATH="${GFORGE_VENV:-$PROJECT_ROOT/.venv}"
GFORGE_HOME="${GFORGE_HOME:-$HOME/.gforge}"
GFORGE_TOOLS_ROOT="${GFORGE_TOOLS_ROOT:-$GFORGE_HOME/tools}"
HARNESS_SKILLS_DIR="$GFORGE_HOME/harness/skills"
DEFAULT_MODEL="${GFORGE_DEFAULT_MODEL:-gemma-4-e4b-it}"
DEFAULT_MODEL_SOURCE="${GFORGE_DEFAULT_MODEL_SOURCE:-gemma4:e4b}"
SKIP_DEFAULT_MODEL_PULL="${GFORGE_SKIP_DEFAULT_MODEL_PULL:-0}"
POSTINSTALL_PROVISION="${GFORGE_POSTINSTALL_PROVISION:-1}"
ALLOW_DEGRADED_TOOLS="${GFORGE_ALLOW_DEGRADED_TOOLS:-0}"
DOCKER_WAIT_SECONDS="${GFORGE_DOCKER_WAIT_SECONDS:-600}"
PYTHON_BIN="${GFORGE_PYTHON:-}"

cd "$PROJECT_ROOT"

# --- Helpers ---------------------------------------------------------------

step() { printf "\n\033[1;34m[forge install]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[forge warn]\033[0m %s\n" "$*"; }
fail() { printf "\033[1;31m[forge fail]\033[0m %s\n" "$*" >&2; exit 1; }

is_macos() { [[ "$(uname -s)" == "Darwin" ]]; }
have()     { command -v "$1" >/dev/null 2>&1; }

docker_cli() {
    if have docker; then
        command -v docker
    elif [ -x /Applications/Docker.app/Contents/Resources/bin/docker ]; then
        printf '%s\n' /Applications/Docker.app/Contents/Resources/bin/docker
    else
        return 1
    fi
}

docker_ready() {
    local cli
    cli="$(docker_cli)" || return 1
    "$cli" info >/dev/null 2>&1
}

admin_run() {
    if [ "$(id -u)" = "0" ]; then
        "$@"
        return
    fi
    if have sudo && sudo -n true >/dev/null 2>&1; then
        sudo -n "$@"
        return
    fi
    if have sudo && [ -t 0 ]; then
        sudo "$@"
        return
    fi
    return 1
}

clear_app_quarantine() {
    local app_path="$1"
    [ -e "$app_path" ] || return 0
    if xattr -p com.apple.quarantine "$app_path" >/dev/null 2>&1; then
        step "Clearing macOS quarantine from $(basename "$app_path")..."
        xattr -dr com.apple.quarantine "$app_path" >/dev/null 2>&1 \
            || admin_run xattr -dr com.apple.quarantine "$app_path"
    fi
}

configure_docker_desktop() {
    [ -d /Applications/Docker.app ] || return 0
    clear_app_quarantine /Applications/Docker.app \
        || warn "Could not clear Docker Desktop quarantine; macOS may ask to approve first launch."

    local installer="/Applications/Docker.app/Contents/MacOS/install"
    if [ -x "$installer" ]; then
        step "Configuring Docker Desktop admin components..."
        admin_run "$installer" --accept-license --user "$USER" >/dev/null 2>&1 \
            || warn "Docker Desktop admin preconfiguration failed; Docker may need a manual first-run approval."
    fi
}

wait_for_url() {
    local url="$1"
    local attempts="${2:-30}"
    for _ in $(seq 1 "$attempts"); do
        if curl -sf --max-time 2 "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

ollama_model_installed() {
    local model="$1"
    local name
    while read -r name _; do
        [ -n "$name" ] || continue
        if [ "$name" = "$model" ] || [ "$name" = "$model:latest" ] || [[ "$name" == "$model:"* ]]; then
            return 0
        fi
    done < <(ollama list 2>/dev/null | tail -n +2)
    return 1
}

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
    wait_for_url http://localhost:11434/api/version 30 \
        || fail "Ollama did not start on http://localhost:11434."
fi

# First-run users should land with the default Forge Brain runnable. Ollama's
# public tag is `gemma4:e4b`; Gemma Forge uses a stable local alias.
if [ "$SKIP_DEFAULT_MODEL_PULL" != "1" ]; then
    if ! ollama_model_installed "$DEFAULT_MODEL"; then
        if ! ollama_model_installed "$DEFAULT_MODEL_SOURCE"; then
            step "Pulling default Forge Brain model: $DEFAULT_MODEL_SOURCE (~10 GB one-time download)..."
            ollama pull "$DEFAULT_MODEL_SOURCE"
        fi
        if [ "$DEFAULT_MODEL_SOURCE" != "$DEFAULT_MODEL" ]; then
            step "Creating local model alias: $DEFAULT_MODEL..."
            ollama cp "$DEFAULT_MODEL_SOURCE" "$DEFAULT_MODEL"
        fi
    fi
    ollama_model_installed "$DEFAULT_MODEL" \
        || fail "Default Forge Brain model $DEFAULT_MODEL is not installed."
else
    warn "Skipping default model pull because GFORGE_SKIP_DEFAULT_MODEL_PULL=1."
fi

# --- 3. Node.js (for SocratiCode MCP) --------------------------------------

if ! have node; then
    step "Installing Node.js 22 via Homebrew..."
    brew install node@22
    brew link --force --overwrite node@22 >/dev/null 2>&1 || true
fi

# --- 4. Docker Desktop (for SocratiCode Qdrant) ----------------------------

if ! docker_cli >/dev/null 2>&1 && [ ! -d /Applications/Docker.app ]; then
    step "Installing Docker Desktop via Homebrew cask..."
    brew install --cask docker
fi

configure_docker_desktop

if [ -d /Applications/Docker.app ] && ! docker_ready; then
    if [ -d /Applications/Docker.app ]; then
        step "Starting Docker Desktop for SocratiCode..."
        open -gj -a Docker >/dev/null 2>&1 || open -a Docker >/dev/null 2>&1 || true
        DOCKER_WAIT_ATTEMPTS=$((DOCKER_WAIT_SECONDS / 5))
        if [ "$DOCKER_WAIT_ATTEMPTS" -lt 1 ]; then
            DOCKER_WAIT_ATTEMPTS=1
        fi
        for _ in $(seq 1 "$DOCKER_WAIT_ATTEMPTS"); do
            if docker_ready; then
                break
            fi
            sleep 5
        done
    fi
    if ! docker_ready; then
        warn "Docker is installed but not running yet. SocratiCode may report unavailable until Docker Desktop finishes first-run startup."
    fi
fi

# --- 5. Python 3.13 venv + deps -------------------------------------------

if [ -z "$PYTHON_BIN" ]; then
    if have python3.13; then
        PYTHON_BIN="$(command -v python3.13)"
    else
        step "Installing Python 3.13 via Homebrew..."
        brew install python@3.13
        PYTHON_BIN="$(brew --prefix python@3.13)/bin/python3.13"
    fi
fi

if [ ! -x "$PYTHON_BIN" ]; then
    fail "Python interpreter not executable: $PYTHON_BIN"
fi

if [ -d "$VENV_PATH" ]; then
    VENV_PYTHON_VERSION="$("$VENV_PATH/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "unknown")"
    if [ "$VENV_PYTHON_VERSION" != "3.13" ]; then
        step "Recreating Python venv with Python 3.13 (found $VENV_PYTHON_VERSION)..."
        rm -rf "$VENV_PATH"
    fi
fi

if [ ! -d "$VENV_PATH" ]; then
    step "Creating Python venv at $VENV_PATH..."
    "$PYTHON_BIN" -m venv "$VENV_PATH"
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
        skill_destination="$HARNESS_SKILLS_DIR/$skill_name"
        if [ -d "$skill_destination" ] && [ ! -f "$skill_destination/SKILL.md" ] && [ ! -f "$skill_destination/skill.json" ]; then
            warn "Refreshing incomplete staged skill: $skill_name"
            rm -rf "$skill_destination"
        fi
        if [ ! -d "$skill_destination" ]; then
            step "Staging skill: $skill_name"
            cp -R "$skill_dir" "$skill_destination"
        fi
    done
fi

# --- 10. First-use provisioning -------------------------------------------

if [ "$POSTINSTALL_PROVISION" != "0" ]; then
    step "Provisioning embedding model, SocratiCode/Qdrant, Axon index, and bundled skills..."
    if [ "$ALLOW_DEGRADED_TOOLS" = "1" ]; then
        python tools/provision_clean_install.py --allow-degraded
    else
        python tools/provision_clean_install.py
    fi
else
    warn "Skipping post-install provisioning because GFORGE_POSTINSTALL_PROVISION=0."
fi

# --- 11. Launch ------------------------------------------------------------

export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

step "All dependencies verified. Launching Gemma Forge Harness at http://127.0.0.1:5005/"
python -m chat.server
