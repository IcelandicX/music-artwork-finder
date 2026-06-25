#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/.local/bin"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/com.music-artwork-finder.plist"

mkdir -p "$BIN_DIR"
chmod +x "$PROJECT_DIR/find_artwork.py" "$PROJECT_DIR/find_tags.py" "$PROJECT_DIR/fix_album.py" "$PROJECT_DIR/menu_bar.py"

ln -sf "$PROJECT_DIR/find_artwork.py" "$BIN_DIR/music-artwork"
ln -sf "$PROJECT_DIR/find_artwork.py" "$BIN_DIR/find-album-artwork"
ln -sf "$PROJECT_DIR/find_tags.py" "$BIN_DIR/music-tags"
ln -sf "$PROJECT_DIR/fix_album.py" "$BIN_DIR/music-fix"

python3 -m pip install --user -r "$PROJECT_DIR/requirements.txt"

if ! echo ":$PATH:" | grep -q ":$BIN_DIR:"; then
  SHELL_PROFILE="$HOME/.zprofile"
  if [[ -f "$HOME/.zshrc" && ! -f "$SHELL_PROFILE" ]]; then
    SHELL_PROFILE="$HOME/.zshrc"
  fi
  {
    echo
    echo "# Added by music-artwork-finder install.sh"
    echo "export PATH=\"$BIN_DIR:\$PATH\""
  } >> "$SHELL_PROFILE"
  echo "Added $BIN_DIR to PATH in $SHELL_PROFILE"
fi

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.music-artwork-finder</string>
    <key>ProgramArguments</key>
    <array>
        <string>$(command -v python3)</string>
        <string>$PROJECT_DIR/menu_bar.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/com.music-artwork-finder" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

echo
echo "Installed."
echo "  CLI: music-artwork, music-tags, music-fix"
echo "  Menu bar app: started (look for “Music Fix” near the clock)"
echo
echo "Usage:"
echo "  1. Open Music and select any track from an album"
echo "  2. Run: music-artwork"
echo "     or click Artwork → Find Artwork for Selected Album"
