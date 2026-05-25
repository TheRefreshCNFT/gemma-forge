#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP_DIR="${HOME}/Desktop"
ACTION_SCRIPT="$PROJECT_ROOT/tools/desktop_harness_action.sh"

install_shortcut() {
  local name="$1"
  local action="$2"
  local target="$DESKTOP_DIR/$name"
  cat > "$target" <<COMMAND
#!/usr/bin/env bash
exec "$ACTION_SCRIPT" "$action"
COMMAND
  chmod +x "$target"
  printf 'Installed: %s\n' "$target"
}

mkdir -p "$DESKTOP_DIR"
chmod +x "$ACTION_SCRIPT"

install_shortcut "Gemma Forge Start.command" "start"
install_shortcut "Gemma Forge Stop.command" "stop"
install_shortcut "Gemma Forge Restart.command" "restart"
install_shortcut "Gemma Forge Pull Latest + Restart.command" "update"
