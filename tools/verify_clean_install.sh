#!/bin/bash
# verify_clean_install.sh — end-to-end clean-install verification for Gemma Forge.
#
# Run this INSIDE a fresh VM (or fresh user account) after `./launch_forge.command`
# has finished. It checks every external tool the harness depends on, confirms
# the server is reachable, and exercises the API with a tiny test project.
#
# Usage:
#   ./tools/verify_clean_install.sh                 # check current install state
#   GFORGE_PORT=5005 ./tools/verify_clean_install.sh
#
# Exit codes:
#   0  all checks passed
#   1+ N checks failed (count == exit code)

set -uo pipefail

# In an SSH session, /opt/homebrew/bin isn't on PATH by default — brew
# installs everything there on Apple Silicon. Source the shellenv so the
# binaries the launcher installed are visible to this script.
if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
fi

PORT="${GFORGE_PORT:-5005}"
OLLAMA_PORT="${OLLAMA_PORT:-11434}"
DEFAULT_MODEL="${GFORGE_DEFAULT_MODEL:-gemma-4-e4b-it}"
TEST_MODEL="${TEST_MODEL:-$DEFAULT_MODEL}"
FAILS=0

pass() { printf "\033[1;32m  ✓\033[0m %s\n" "$*"; }
fail() { printf "\033[1;31m  ✗\033[0m %s\n" "$*"; FAILS=$((FAILS + 1)); }
warn() { printf "\033[1;33m  ⚠\033[0m %s\n" "$*"; }
section() { printf "\n\033[1;34m== %s ==\033[0m\n" "$*"; }

check_bin() {
    local name="$1"; local extra_path="${2:-}"
    if command -v "$name" >/dev/null 2>&1; then
        pass "$name on PATH at $(command -v "$name")"
    elif [ -n "$extra_path" ] && [ -x "$extra_path" ]; then
        pass "$name at $extra_path"
    else
        fail "$name not found"
    fi
}

check_url() {
    local label="$1"; local url="$2"; local expect="${3:-200}"
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "000")
    if [ "$code" = "$expect" ]; then
        pass "$label → HTTP $code"
    else
        fail "$label → HTTP $code (expected $expect)"
    fi
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

# --- 1. System tools -------------------------------------------------------

section "1. System tools"
check_bin brew
check_bin ollama
check_bin node
# Docker on macOS installs Docker.app to /Applications/. The `docker` CLI
# lives inside Docker.app and only joins PATH after the app is launched
# once (kernel-extension approval — needs a GUI session). Report the
# installed-but-not-launched state distinctly so the "fail" doesn't lie.
if command -v docker >/dev/null 2>&1; then
    pass "docker on PATH at $(command -v docker)"
    if docker info >/dev/null 2>&1; then
        pass "docker daemon ready"
    else
        fail "docker daemon not ready"
    fi
elif [ -d /Applications/Docker.app ]; then
    fail "docker installed at /Applications/Docker.app but CLI/daemon not ready"
else
    fail "docker not found"
fi
check_bin python3
check_bin curl

# --- 2. Python venv + harness deps -----------------------------------------

section "2. Python venv + harness deps"
PROJECT_ROOT="${GFORGE_PROJECT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
VENV_PATH="${GFORGE_VENV:-$PROJECT_ROOT/.venv}"
if [ -d "$VENV_PATH" ]; then
    pass "venv exists at $VENV_PATH"
    # shellcheck disable=SC1091
    source "$VENV_PATH/bin/activate"
    for pkg in flask flask_cors yaml requests scrapling; do
        if python -c "import $pkg" 2>/dev/null; then
            pass "python imports $pkg"
        else
            fail "python cannot import $pkg"
        fi
    done
    if python -m pip show axoniq >/dev/null 2>&1; then
        pass "axoniq installed in venv"
    else
        fail "axoniq not installed"
    fi
    if [ -f "$VENV_PATH/.scrapling-browsers-installed" ]; then
        pass "scrapling browsers sentinel file present"
    else
        fail "scrapling browsers sentinel missing"
    fi
else
    fail "venv does NOT exist at $VENV_PATH"
fi

# --- 3. SocratiCode --------------------------------------------------------

section "3. SocratiCode MCP"
SOCRATICODE_BIN="${GFORGE_TOOLS_ROOT:-$HOME/.gforge/tools}/node_modules/.bin/socraticode"
check_bin socraticode "$SOCRATICODE_BIN"

# --- 4. Bundled skills staged ----------------------------------------------

section "4. Bundled skills"
SKILLS_DIR="${GFORGE_HOME:-$HOME/.gforge}/harness/skills"
for skill in logo-generator scrapling-official ui-ux-pro-max axon pdf mcp-builder; do
    if [ -d "$SKILLS_DIR/$skill" ]; then
        pass "skill staged: $skill"
    else
        fail "skill missing: $skill"
    fi
done

# --- 5. Ollama service -----------------------------------------------------

section "5. Ollama service"
check_url "ollama version" "http://localhost:${OLLAMA_PORT}/api/version"
check_url "ollama tags"    "http://localhost:${OLLAMA_PORT}/api/tags"
if ollama_model_installed "$DEFAULT_MODEL"; then
    pass "default model installed: $DEFAULT_MODEL"
else
    fail "default model missing from Ollama: $DEFAULT_MODEL"
fi

# --- 6. Harness server -----------------------------------------------------

section "6. Harness server"
check_url "harness root"      "http://localhost:${PORT}/"
check_url "workspace status"  "http://localhost:${PORT}/api/workspace/status"
check_url "events recent"     "http://localhost:${PORT}/api/events/recent"

# --- 7. Harness readiness --------------------------------------------------

section "7. Harness readiness"
READINESS_JSON=$(curl -s --max-time 30 "http://localhost:${PORT}/api/workspace/status" 2>/dev/null)
if READINESS_JSON="$READINESS_JSON" python3 - "$DEFAULT_MODEL" <<'PY'
import json
import os
import sys

default_model = sys.argv[1]
data = json.loads(os.environ.get("READINESS_JSON", "{}"))
models = data.get("modelOptions", [])
tools = data.get("tools", {})
default = next((m for m in models if m.get("ollamaName") == default_model), None)
errors = []

if not default:
    errors.append(f"default model option missing: {default_model}")
else:
    for key in ("selected", "recommended", "installed", "supported"):
        if not default.get(key):
            errors.append(f"default model {key} is not true")

for key in ("socraticodeInstalled", "socraticodeExecutable", "socraticodeMcpReady", "socraticodeQdrantRunning"):
    if not tools.get(key):
        errors.append(f"{key} is not true")

if not tools.get("axonExecutable"):
    errors.append("axonExecutable is not true")

if errors:
    print("\n".join(errors))
    sys.exit(1)
sys.exit(0)
PY
then
    pass "workspace status reports default model, SocratiCode, and Axon install readiness"
else
    fail "workspace readiness check failed: $(READINESS_JSON="$READINESS_JSON" python3 - "$DEFAULT_MODEL" <<'PY'
import json
import os
import sys

default_model = sys.argv[1]
try:
    data = json.loads(os.environ.get("READINESS_JSON", "{}"))
except Exception as exc:
    print(f"invalid workspace status JSON: {exc}")
    sys.exit(0)
models = data.get("modelOptions", [])
tools = data.get("tools", {})
default = next((m for m in models if m.get("ollamaName") == default_model), {})
parts = [
    f"default.installed={default.get('installed')}",
    f"default.selected={default.get('selected')}",
    f"socraticodeInstalled={tools.get('socraticodeInstalled')}",
    f"socraticodeMcpReady={tools.get('socraticodeMcpReady')}",
    f"socraticodeQdrantRunning={tools.get('socraticodeQdrantRunning')}",
    f"axonExecutable={tools.get('axonExecutable')}",
]
print(", ".join(parts))
PY
)"
fi

# --- 8. End-to-end: default model test project -----------------------------

section "8. End-to-end test project"

if ! curl -sf --max-time 2 "http://localhost:${OLLAMA_PORT}/api/tags" >/dev/null 2>&1; then
    fail "skipping E2E test — Ollama not reachable"
fi

if ollama_model_installed "$TEST_MODEL"; then
    pass "test model $TEST_MODEL available"

    SESSION_RESP=$(curl -s -X POST "http://localhost:${PORT}/api/sessions" \
        -H 'Content-Type: application/json' \
        -d '{"project":"Write a one-paragraph plain text description of a coffee shop named Steamline.","model":"'"$TEST_MODEL"'"}' 2>/dev/null)
    SESSION_ID=$(echo "$SESSION_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>/dev/null)

    if [ -n "$SESSION_ID" ]; then
        pass "created session $SESSION_ID"
        printf "  ⏳ Running intake card (model inference, may take 30-60s)...\n"
        INTAKE_RESP=$(curl -s -X POST "http://localhost:${PORT}/api/sessions/${SESSION_ID}/cards/intake/run" \
            -H 'Content-Type: application/json' \
            -d '{}' --max-time 1200 2>/dev/null)
        if echo "$INTAKE_RESP" | grep -q '"status"'; then
            STATUS=$(echo "$INTAKE_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); c=d.get('session',{}).get('cards',[]); print(next((card.get('status') for card in c if card.get('id')=='intake'),''))" 2>/dev/null)
            # Any of these statuses means the harness ran the card end-to-end:
            #   complete         → model output passed the deterministic + reviewer checks
            #   awaiting-human   → Human Verify is on; card ran cleanly and is paused for user
            #   needs-attention  → card ran, but the validator / reviewer flagged the output
            #                      (this IS the harness doing its job, not a crash — small 1B
            #                      models often trip the claim validator)
            # The only failure is when the card crashed mid-run (status: error / unset).
            case "$STATUS" in
                complete|awaiting-human|needs-attention)
                    pass "intake card finished — status: $STATUS"
                    ;;
                *)
                    fail "intake card did not complete cleanly (status: $STATUS)"
                    ;;
            esac
        else
            fail "intake card response malformed"
        fi
    else
        fail "could not create session — response: $SESSION_RESP"
    fi
else
    fail "test model $TEST_MODEL not available — skipping E2E"
fi

# --- Final report ----------------------------------------------------------

printf "\n"
if [ "$FAILS" -eq 0 ]; then
    printf "\033[1;32m=== ALL CHECKS PASSED ===\033[0m\n"
    exit 0
else
    printf "\033[1;31m=== %d CHECK(S) FAILED ===\033[0m\n" "$FAILS"
    exit "$FAILS"
fi
