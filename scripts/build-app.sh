#!/bin/bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo "Usage: $0 /path/to/source-project '/path/to/Music Fix.app' [/runtime/project/path]" >&2
    exit 1
fi

PROJECT_DIR="$1"
APP_PATH="$2"
RUNTIME_PROJECT_DIR="${3:-$PROJECT_DIR}"
APP_NAME="Music Fix"
EXECUTABLE="$APP_PATH/Contents/MacOS/$APP_NAME"
RESOURCES="$APP_PATH/Contents/Resources"

rm -rf "$APP_PATH"
mkdir -p "$APP_PATH/Contents/MacOS" "$RESOURCES"

if [[ -f "$PROJECT_DIR/assets/MusicFix.icns" ]]; then
    cp "$PROJECT_DIR/assets/MusicFix.icns" "$RESOURCES/MusicFix.icns"
fi

cat > "$APP_PATH/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Music Fix</string>
    <key>CFBundleDisplayName</key>
    <string>Music Fix</string>
    <key>CFBundleIdentifier</key>
    <string>com.icelandick.music-artwork-finder.app</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>Music Fix</string>
    <key>CFBundleIconFile</key>
    <string>MusicFix</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSAppleEventsUsageDescription</key>
    <string>Music Fix needs Automation access to inspect and organize your Apple Music library.</string>
</dict>
</plist>
EOF

cat > "$EXECUTABLE" <<EOF
#!/bin/bash
set -euo pipefail

PROJECT_DIR="$RUNTIME_PROJECT_DIR"
PYTHON="\${MUSIC_FIX_PYTHON:-}"
if [[ -z "\$PYTHON" ]]; then
    PYTHON="\$(command -v python3 || true)"
fi
if [[ -z "\$PYTHON" ]]; then
    PYTHON="/usr/bin/python3"
fi

exec "\$PYTHON" "\$PROJECT_DIR/menu_bar.py"
EOF

chmod +x "$EXECUTABLE"
echo "Built $APP_PATH"
