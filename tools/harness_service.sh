#!/usr/bin/env bash
set -euo pipefail

LABEL="com.webot.gemma-forge.harness"
PORT="${GFORGE_PORT:-5005}"
HOST="${GFORGE_HOST:-127.0.0.1}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${GFORGE_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_OUT="${GFORGE_LOG_OUT:-/tmp/gemma-forge-server.log}"
LOG_ERR="${GFORGE_LOG_ERR:-/tmp/gemma-forge-server.err.log}"
GUI_DOMAIN="gui/$(id -u)"

usage() {
  cat <<USAGE
Usage: tools/harness_service.sh <start|stop|restart|status|logs|open>

Commands:
  start    Install/update the LaunchAgent and start Gemma Forge on $HOST:$PORT.
  stop     Stop and unload the LaunchAgent.
  restart  Stop, then start.
  status   Show launchd state, port listener, and endpoint health.
  logs     Tail the harness stdout/stderr logs.
  open     Open http://$HOST:$PORT in the default browser.
USAGE
}

require_macos() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This service helper uses macOS launchd." >&2
    exit 1
  fi
}

write_plist() {
  mkdir -p "$(dirname "$PLIST")"
  cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>-m</string>
    <string>chat.server</string>
  </array>

  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key>
    <string>$PROJECT_ROOT</string>
    <key>PATH</key>
    <string>$PROJECT_ROOT/.venv/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>

  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>$LOG_OUT</string>
  <key>StandardErrorPath</key>
  <string>$LOG_ERR</string>
</dict>
</plist>
PLIST
  plutil -lint "$PLIST" >/dev/null
}

is_loaded() {
  launchctl print "$GUI_DOMAIN/$LABEL" >/dev/null 2>&1
}

stop_service() {
  if is_loaded; then
    launchctl bootout "$GUI_DOMAIN/$LABEL" >/dev/null 2>&1 || true
  fi
}

start_service() {
  require_macos
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Python runtime not found or not executable: $PYTHON_BIN" >&2
    echo "Run ./launch_forge.command once to create the virtual environment." >&2
    exit 1
  fi
  write_plist
  if ! is_loaded; then
    launchctl bootstrap "$GUI_DOMAIN" "$PLIST"
  fi
  launchctl kickstart -k "$GUI_DOMAIN/$LABEL"
}

port_listener() {
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true
}

endpoint_status() {
  curl -fsS "http://$HOST:$PORT/api/model/route" >/tmp/gemma-forge-route-check.json 2>/dev/null
}

wait_for_endpoint() {
  local timeout="${GFORGE_START_TIMEOUT:-60}"
  local deadline=$((SECONDS + timeout))
  printf "Waiting for endpoint http://%s:%s" "$HOST" "$PORT"
  until endpoint_status; do
    if (( SECONDS >= deadline )); then
      printf "\nEndpoint did not become ready within %s seconds.\n" "$timeout" >&2
      return 1
    fi
    printf "."
    sleep 1
  done
  printf " ok\n"
}

status_service() {
  require_macos
  echo "LaunchAgent: $PLIST"
  if is_loaded; then
    launchctl print "$GUI_DOMAIN/$LABEL" | sed -n '1,45p'
  else
    echo "launchd: not loaded"
  fi
  echo
  echo "Port:"
  port_listener || true
  echo
  if endpoint_status; then
    echo "Endpoint: ok http://$HOST:$PORT"
    cat /tmp/gemma-forge-route-check.json
    echo
  else
    echo "Endpoint: not responding at http://$HOST:$PORT"
    return 1
  fi
}

case "${1:-}" in
  start)
    start_service
    wait_for_endpoint
    status_service
    ;;
  stop)
    require_macos
    stop_service
    echo "Stopped $LABEL."
    ;;
  restart)
    require_macos
    stop_service
    start_service
    wait_for_endpoint
    status_service
    ;;
  status)
    status_service
    ;;
  logs)
    touch "$LOG_OUT" "$LOG_ERR"
    tail -n 80 -f "$LOG_OUT" "$LOG_ERR"
    ;;
  open)
    open "http://$HOST:$PORT"
    ;;
  *)
    usage
    exit 2
    ;;
esac
