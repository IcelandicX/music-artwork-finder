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
LOG_DIR="\$HOME/Library/Logs"
LOG_FILE="\$LOG_DIR/Music Fix.log"
mkdir -p "\$LOG_DIR"
exec >>"\$LOG_FILE" 2>&1

echo "---- Music Fix launch \$(date) ----"
export PATH="/Library/Frameworks/Python.framework/Versions/Current/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:\${PATH:-}"

if [[ ! -f "\$PROJECT_DIR/menu_bar.py" && -f "/usr/local/share/music-artwork-finder/menu_bar.py" ]]; then
    PROJECT_DIR="/usr/local/share/music-artwork-finder"
fi

if [[ ! -f "\$PROJECT_DIR/menu_bar.py" ]]; then
    echo "Missing menu_bar.py at \$PROJECT_DIR/menu_bar.py"
    exit 1
fi

python_can_run_music_fix() {
    local candidate="\$1"
    [[ -x "\$candidate" ]] || return 1
    "\$candidate" -c 'import rumps' >/dev/null 2>&1
}

PYTHON="\${MUSIC_FIX_PYTHON:-}"
if [[ -n "\$PYTHON" ]] && ! python_can_run_music_fix "\$PYTHON"; then
    echo "Configured MUSIC_FIX_PYTHON cannot import rumps: \$PYTHON"
    PYTHON=""
fi

if [[ -z "\$PYTHON" ]]; then
    for candidate in \
        "/Library/Frameworks/Python.framework/Versions/Current/bin/python3" \
        "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3" \
        "/opt/homebrew/bin/python3" \
        "/usr/local/bin/python3" \
        "\$(command -v python3 || true)" \
        "/usr/bin/python3"; do
        if python_can_run_music_fix "\$candidate"; then
            PYTHON="\$candidate"
            break
        fi
    done
fi

if [[ -z "\$PYTHON" ]]; then
    echo "No Python interpreter with rumps installed was found."
    echo "Run ./install.sh or python3 -m pip install --user -r \$PROJECT_DIR/requirements.txt"
    exit 1
fi

echo "Using Python: \$PYTHON"
echo "Using project: \$PROJECT_DIR"
exec "\$PYTHON" "\$PROJECT_DIR/menu_bar.py"
EOF

chmod +x "$EXECUTABLE"
echo "Built $APP_PATH"
