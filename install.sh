#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$PROJECT_DIR/scripts/setup-user.sh"

music_fix_setup "$PROJECT_DIR" "$HOME/.local/bin"

echo
echo "Installed."
echo "  App: ~/Applications/Music Fix.app"
echo "  CLI: music-ai, music-analyze, music-artwork, music-tags, music-fix, music-splits, music-combine, music-resplit, music-duplicates, music-undo, music-cache, music-prefs, music-doctor"
echo "  Menu bar app: started (look for “Music Fix” near the clock)"
echo
echo "Usage:"
echo "  1. Open Music and select album/albums or songs"
echo "  2. Run: music-ai"
echo "     or click Music Fix → AI All-in-One Fix"
