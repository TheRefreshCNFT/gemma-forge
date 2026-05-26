#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-}"
REPO="${GFORGE_PROJECT_ROOT:-/Users/webot/Projects/gemma-forge}"
HOST="${GFORGE_HOST:-127.0.0.1}"
PORT="${GFORGE_PORT:-5005}"
URL="http://$HOST:$PORT/"

section() {
  printf "\n\033[1;34m[Gemma Forge]\033[0m %s\n" "$*"
}

warn() {
  printf "\033[1;33m[Gemma Forge warn]\033[0m %s\n" "$*"
}

fail() {
  printf "\033[1;31m[Gemma Forge fail]\033[0m %s\n" "$*" >&2
  exit 1
}

pause_before_exit() {
  [[ "${GFORGE_NO_PAUSE:-0}" == "1" ]] && return 0
  [[ -t 0 ]] || return 0
  printf "\nPress Return to close this window..."
  read -r _ || true
}

usage() {
  cat <<USAGE
Usage: tools/desktop_harness_action.sh <start|stop|restart|update>

Actions:
  start    Start/open the harness from the canonical repo.
  stop     Stop the LaunchAgent and clear any port 5005 listener.
  restart  Stop, clear port 5005, then start/open the harness.
  update   Fetch/pull origin/main, then restart/open the harness.
USAGE
}

require_repo() {
  [[ -d "$REPO/.git" ]] || fail "Canonical repo not found: $REPO"
  cd "$REPO"
}

listener_pids() {
  lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true
}

has_listener() {
  [[ -n "$(listener_pids)" ]]
}

pid_cwd() {
  local pid="$1"
  lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1
}

kill_pid() {
  local pid="$1"
  local label="${2:-process}"
  warn "Stopping $label PID $pid."
  kill "$pid" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.4
  done
  warn "Force-stopping stubborn PID $pid."
  kill -9 "$pid" 2>/dev/null || true
}

clear_wrong_repo_listeners() {
  local pid cwd
  while read -r pid; do
    [[ -n "$pid" ]] || continue
    cwd="$(pid_cwd "$pid")"
    if [[ "$cwd" != "$REPO" ]]; then
      kill_pid "$pid" "wrong-repo harness listener from ${cwd:-unknown cwd}"
    fi
  done < <(listener_pids)
}

clear_all_listeners() {
  local pid cwd
  while read -r pid; do
    [[ -n "$pid" ]] || continue
    cwd="$(pid_cwd "$pid")"
    kill_pid "$pid" "harness listener from ${cwd:-unknown cwd}"
  done < <(listener_pids)
}

working_tree_clean() {
  git diff --quiet --ignore-submodules -- &&
    git diff --cached --quiet --ignore-submodules --
}

show_repo_state() {
  section "Repo"
  git status --short --branch
  printf "HEAD: "
  git rev-parse --short HEAD
  if git rev-parse --verify origin/main >/dev/null 2>&1; then
    printf "origin/main: "
    git rev-parse --short origin/main
  fi
}

show_service_state() {
  section "Service status"
  npm run harness:status || true
}

open_harness() {
  open "$URL" >/dev/null 2>&1 || true
}

warn_if_not_current() {
  git fetch origin main --quiet || {
    warn "Could not fetch origin/main. Continuing with local repo state."
    return 0
  }
  local head remote
  head="$(git rev-parse HEAD)"
  remote="$(git rev-parse origin/main)"
  if [[ "$head" != "$remote" ]]; then
    warn "This checkout is not at origin/main. Use 'Gemma Forge Pull Latest + Restart.command' before testing a pushed update."
  fi
}

start_harness() {
  require_repo
  show_repo_state
  warn_if_not_current
  clear_wrong_repo_listeners
  if has_listener; then
    section "Harness already listening on $URL"
    show_service_state
    open_harness
    return 0
  fi
  section "Starting from $REPO"
  npm run harness:start
  open_harness
}

stop_harness() {
  require_repo
  section "Stopping managed service"
  npm run harness:stop || true
  clear_all_listeners
  show_service_state
}

restart_harness() {
  require_repo
  section "Restarting from $REPO"
  npm run harness:stop || true
  clear_all_listeners
  npm run harness:start
  open_harness
}

update_harness() {
  require_repo
  show_repo_state
  if ! working_tree_clean; then
    git status --short
    fail "Working tree has local changes. Commit, stash, or clear them before pulling a live update."
  fi
  section "Fetching origin/main"
  git fetch origin main
  section "Pulling latest pushed main"
  git pull --ff-only origin main
  if [[ -x ".venv/bin/python" ]]; then
    section "Refreshing Python requirements"
    .venv/bin/python -m pip install -r requirements.txt >/dev/null
  else
    warn "No .venv found. Run ./launch_forge.command once if start fails."
  fi
  restart_harness
}

main() {
  case "$ACTION" in
    start) start_harness ;;
    stop) stop_harness ;;
    restart) restart_harness ;;
    update) update_harness ;;
    ""|-h|--help|help)
      usage
      ;;
    *)
      usage
      fail "Unknown action: $ACTION"
      ;;
  esac
}

trap pause_before_exit EXIT
main
