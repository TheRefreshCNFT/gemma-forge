#!/bin/bash
# run_clean_install_test.sh — host-side orchestrator for the Gemma Forge
# clean-install VM test.
#
# Spins up a fresh macOS VM via tart, mounts the project read-only, runs
# launch_forge.command inside the VM, then runs the verify script. Reports
# pass/fail and leaves the VM in place for inspection (it can be deleted
# afterwards with `tart delete forge-clean-test`).
#
# Usage:
#   tools/run_clean_install_test.sh                  # default — full test
#   tools/run_clean_install_test.sh --keep-vm        # don't suggest deletion
#   tools/run_clean_install_test.sh --no-pull-model  # skip the gemma3:1b pull
#
# Prerequisites on the host:
#   - tart installed (brew install cirruslabs/cli/tart)
#   - sshpass installed (brew install hudochenkov/sshpass/sshpass)
#   - Base image pulled (tart pull ghcr.io/cirruslabs/macos-sequoia-base:latest)

set -uo pipefail

VM_NAME="${TART_VM_NAME:-forge-clean-test}"
BASE_IMAGE="${TART_BASE_IMAGE:-ghcr.io/cirruslabs/macos-sequoia-base:latest}"
PROJECT_ROOT="${GFORGE_PROJECT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
VM_USER="admin"
VM_PASS="admin"
KEEP_VM=0
NO_PULL_MODEL=0

for arg in "$@"; do
    case "$arg" in
        --keep-vm) KEEP_VM=1 ;;
        --no-pull-model) NO_PULL_MODEL=1 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

step()  { printf "\n\033[1;34m[host]\033[0m %s\n" "$*"; }
warn()  { printf "\033[1;33m[host warn]\033[0m %s\n" "$*"; }
fail()  { printf "\033[1;31m[host fail]\033[0m %s\n" "$*" >&2; }

# --- 0. Preflight ----------------------------------------------------------

step "Preflight: checking host tools..."
for bin in tart sshpass; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        fail "$bin not installed on host. See script header."
        exit 1
    fi
done

if ! tart list 2>/dev/null | tail -n +2 | awk '{print $2}' | grep -qFx "$(basename "$BASE_IMAGE" | sed 's/:.*//')"; then
    # Try the more reliable check
    if ! tart list 2>/dev/null | grep -qF "${BASE_IMAGE##*/}" 2>/dev/null; then
        warn "Base image $BASE_IMAGE may not be pulled yet."
        warn "If the next tart-clone step hangs, run: tart pull $BASE_IMAGE"
    fi
fi

# --- 1. Clone fresh VM from base ------------------------------------------

if tart list 2>/dev/null | grep -qFw "$VM_NAME"; then
    step "VM '$VM_NAME' already exists. Deleting and recreating..."
    tart delete "$VM_NAME" 2>/dev/null || true
fi

step "Cloning fresh VM '$VM_NAME' from base..."
tart clone "$BASE_IMAGE" "$VM_NAME"

# --- 2. Boot VM with project mounted read-only ----------------------------

step "Booting VM with $PROJECT_ROOT mounted at /Volumes/My Shared Files/gemma-forge (read-only)..."
tart run \
    --no-graphics \
    --dir="gemma-forge:$PROJECT_ROOT:ro" \
    "$VM_NAME" > /tmp/forge-vm.log 2>&1 &
TART_PID=$!

cleanup() {
    step "Stopping VM (tart PID $TART_PID)..."
    kill "$TART_PID" 2>/dev/null || true
    wait "$TART_PID" 2>/dev/null || true
    if [ "$KEEP_VM" = "0" ]; then
        step "To delete the VM: tart delete $VM_NAME"
    fi
}
trap cleanup EXIT INT TERM

# --- 3. Wait for VM SSH to come up ----------------------------------------

step "Waiting for VM IP + SSH (up to 3 min)..."
VM_IP=""
for i in $(seq 1 90); do
    VM_IP=$(tart ip "$VM_NAME" 2>/dev/null || echo "")
    if [ -n "$VM_IP" ]; then
        if sshpass -p "$VM_PASS" ssh \
            -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null \
            -o ConnectTimeout=3 \
            -o LogLevel=ERROR \
            "$VM_USER@$VM_IP" "echo ssh-ready" >/dev/null 2>&1; then
            step "VM up at $VM_IP — SSH ready."
            break
        fi
    fi
    sleep 2
done

if [ -z "$VM_IP" ]; then
    fail "VM did not get an IP after 3 min."
    exit 1
fi

ssh_run() {
    sshpass -p "$VM_PASS" ssh \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR \
        "$VM_USER@$VM_IP" "$@"
}

# --- 4. Copy project into VM (writable) -----------------------------------

step "Copying project from shared mount to a writable location inside VM..."
ssh_run "rm -rf ~/gemma-forge && cp -R '/Volumes/My Shared Files/gemma-forge' ~/gemma-forge && ls -la ~/gemma-forge/launch_forge.command"

# --- 5. Run launcher inside VM (background, log to /tmp/forge.log) --------

step "Starting ./launch_forge.command in the VM (background, logging to /tmp/forge.log)..."
ssh_run "cd ~/gemma-forge && nohup ./launch_forge.command > /tmp/forge.log 2>&1 < /dev/null & echo started"

# --- 6. Tail the launcher log + wait for server to come up ----------------

step "Tailing launcher log + waiting for harness server on port 5005..."
SERVER_UP=0
for i in $(seq 1 180); do
    # 180 * 5s = 15 min budget for the full install
    LATEST=$(ssh_run "tail -n 1 /tmp/forge.log 2>/dev/null || echo '(no log yet)'" 2>/dev/null)
    printf "\r  [%3d/180] %s\033[K" "$i" "$LATEST"

    if ssh_run "curl -sf --max-time 2 http://localhost:5005/api/workspace/status >/dev/null 2>&1 && echo up" 2>/dev/null | grep -q up; then
        SERVER_UP=1
        printf "\n"
        step "Harness server is up inside the VM."
        break
    fi
    sleep 5
done

if [ "$SERVER_UP" = "0" ]; then
    fail "Harness server didn't come up within 15 min. Last 80 lines of launcher log:"
    ssh_run "tail -n 80 /tmp/forge.log"
    exit 1
fi

# --- 7. Run the verify script inside the VM -------------------------------

step "Running verify_clean_install.sh inside the VM..."
EXTRA_ARG=""
if [ "$NO_PULL_MODEL" = "1" ]; then
    EXTRA_ARG="TEST_MODEL=__skip__"
fi
ssh_run "cd ~/gemma-forge && $EXTRA_ARG ./tools/verify_clean_install.sh"
VERIFY_EXIT=$?

# --- 8. Final report ------------------------------------------------------

printf "\n"
if [ "$VERIFY_EXIT" -eq 0 ]; then
    step "ALL CHECKS PASSED ✓"
    step "VM is still running at $VM_IP. Open Safari → http://$VM_IP:5005/ to inspect the UI manually."
    step "When done: tart delete $VM_NAME"
    exit 0
else
    fail "$VERIFY_EXIT check(s) failed."
    step "VM left running for inspection. SSH: sshpass -p admin ssh admin@$VM_IP"
    step "Launcher log: ssh admin@$VM_IP 'tail -n 100 /tmp/forge.log'"
    exit "$VERIFY_EXIT"
fi
