#!/bin/bash
# Reinstall the menu bar app and CLI after agent changes in this project.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL_SCRIPT="$PROJECT_ROOT/install.sh"
LOG_FILE="$PROJECT_ROOT/.cursor/install-hook.log"

if [[ ! -x "$INSTALL_SCRIPT" ]]; then
  exit 0
fi

# Consume hook stdin if present.
if [[ ! -t 0 ]]; then
  cat > /dev/null || true
fi

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') ====="
  "$INSTALL_SCRIPT"
} >> "$LOG_FILE" 2>&1

exit 0
