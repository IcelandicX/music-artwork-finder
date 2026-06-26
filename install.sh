#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$PROJECT_DIR/scripts/setup-user.sh"

music_fix_setup "$PROJECT_DIR" "$HOME/.local/bin"

echo
echo "Installed."
echo "  CLI: music-artwork, music-tags, music-fix, music-splits, music-undo"
echo "  Menu bar app: started (look for “Music Fix” near the clock)"
echo
echo "Usage:"
echo "  1. Open Music and select album/albums or songs"
echo "  2. Run: music-artwork"
echo "     or click Music Fix → Find Artwork for Selected Album(s)"
