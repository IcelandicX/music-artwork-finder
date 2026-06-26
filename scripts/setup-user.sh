#!/bin/bash
# User-level setup shared by install.sh and the macOS pkg postinstall script.

MUSIC_FIX_LABEL="com.music-artwork-finder"
MUSIC_FIX_PYTHON="${MUSIC_FIX_PYTHON:-$(command -v python3)}"

music_fix_console_user() {
    stat -f%Su /dev/console 2>/dev/null || true
}

music_fix_user_home() {
    local user="$1"
    local home
    home=$(dscl . -read "/Users/$user" NFSHomeDirectory 2>/dev/null | awk '{print $2}')
    if [[ -n "$home" ]]; then
        printf '%s\n' "$home"
    fi
}

music_fix_chmod_scripts() {
    local project_dir="$1"
    chmod +x \
        "$project_dir/find_artwork.py" \
        "$project_dir/find_tags.py" \
        "$project_dir/fix_album.py" \
        "$project_dir/resolve_splits.py" \
        "$project_dir/undo_last.py" \
        "$project_dir/menu_bar.py"
}

music_fix_install_cli_links() {
    local project_dir="$1"
    local bin_dir="$2"

    mkdir -p "$bin_dir"
    ln -sf "$project_dir/find_artwork.py" "$bin_dir/music-artwork"
    ln -sf "$project_dir/find_artwork.py" "$bin_dir/find-album-artwork"
    ln -sf "$project_dir/find_tags.py" "$bin_dir/music-tags"
    ln -sf "$project_dir/fix_album.py" "$bin_dir/music-fix"
    ln -sf "$project_dir/resolve_splits.py" "$bin_dir/music-splits"
    ln -sf "$project_dir/undo_last.py" "$bin_dir/music-undo"
}

music_fix_install_python_deps() {
    local project_dir="$1"
    "$MUSIC_FIX_PYTHON" -m pip install --user -r "$project_dir/requirements.txt"
}

music_fix_ensure_path() {
    local bin_dir="$1"
    local home="${HOME:?HOME is required}"

    if echo ":$PATH:" | grep -q ":$bin_dir:"; then
        return 0
    fi

    local shell_profile="$home/.zprofile"
    if [[ -f "$home/.zshrc" && ! -f "$shell_profile" ]]; then
        shell_profile="$home/.zshrc"
    fi

    if [[ -f "$shell_profile" ]] && grep -Fq "music-artwork-finder" "$shell_profile"; then
        return 0
    fi

    {
        echo
        echo "# Added by music-artwork-finder"
        echo "export PATH=\"$bin_dir:\$PATH\""
    } >> "$shell_profile"
    echo "Added $bin_dir to PATH in $shell_profile"
}

music_fix_write_launch_agent() {
    local project_dir="$1"
    local home="${HOME:?HOME is required}"
    local plist_path="$home/Library/LaunchAgents/${MUSIC_FIX_LABEL}.plist"

    mkdir -p "$home/Library/LaunchAgents"
    cat > "$plist_path" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${MUSIC_FIX_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${MUSIC_FIX_PYTHON}</string>
        <string>${project_dir}/menu_bar.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
EOF
}

music_fix_start_launch_agent() {
    local home="${HOME:?HOME is required}"
    local uid
    uid=$(id -u)
    launchctl bootout "gui/$uid/${MUSIC_FIX_LABEL}" 2>/dev/null || true
    launchctl bootstrap "gui/$uid" "$home/Library/LaunchAgents/${MUSIC_FIX_LABEL}.plist"
}

music_fix_setup() {
    local project_dir="$1"
    local bin_dir="${2:-}"

    music_fix_chmod_scripts "$project_dir"
    if [[ -n "$bin_dir" ]]; then
        music_fix_install_cli_links "$project_dir" "$bin_dir"
        music_fix_ensure_path "$bin_dir"
    fi
    music_fix_install_python_deps "$project_dir"
    music_fix_write_launch_agent "$project_dir"
    music_fix_start_launch_agent
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -euo pipefail
    if [[ "${1:-}" != "--setup" || -z "${2:-}" ]]; then
        echo "Usage: $0 --setup /path/to/project [--bin /path/to/bin]" >&2
        exit 1
    fi
    music_fix_setup "$2" "${3:-}"
fi
