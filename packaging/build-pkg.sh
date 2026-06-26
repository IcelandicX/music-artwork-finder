#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
IDENTIFIER="com.icelandick.music-artwork-finder"
BUILD_DIR="$ROOT/build/pkg"
PAYLOAD="$BUILD_DIR/payload"
DIST_DIR="$ROOT/dist"
COMPONENT_PKG="$BUILD_DIR/MusicFix-component.pkg"
DISTRIBUTION_XML="$BUILD_DIR/distribution.xml"
OUTPUT_PKG="$DIST_DIR/MusicFix-${VERSION}.pkg"

APP_FILES=(
    find_artwork.py
    find_tags.py
    music_ai.py
    music_cache.py
    fix_album.py
    menu_bar.py
    music_common.py
    search_cache.py
    search_providers.py
    resolve_splits.py
    undo_history.py
    undo_last.py
    requirements.txt
)

rm -rf "$BUILD_DIR" "$DIST_DIR"
mkdir -p "$PAYLOAD/usr/local/share/music-artwork-finder/scripts"
mkdir -p "$PAYLOAD/usr/local/bin"
mkdir -p "$DIST_DIR"

for file in "${APP_FILES[@]}"; do
    cp "$ROOT/$file" "$PAYLOAD/usr/local/share/music-artwork-finder/"
done
cp "$ROOT/scripts/setup-user.sh" "$PAYLOAD/usr/local/share/music-artwork-finder/scripts/"
mkdir -p "$PAYLOAD/usr/local/share/music-artwork-finder/assets"
rsync -a \
    --exclude '__pycache__/' \
    --exclude 'icon.iconset/' \
    "$ROOT/assets/" "$PAYLOAD/usr/local/share/music-artwork-finder/assets/"

ln -sf /usr/local/share/music-artwork-finder/find_artwork.py "$PAYLOAD/usr/local/bin/music-artwork"
ln -sf /usr/local/share/music-artwork-finder/find_artwork.py "$PAYLOAD/usr/local/bin/find-album-artwork"
ln -sf /usr/local/share/music-artwork-finder/find_tags.py "$PAYLOAD/usr/local/bin/music-tags"
ln -sf /usr/local/share/music-artwork-finder/music_ai.py "$PAYLOAD/usr/local/bin/music-ai"
ln -sf /usr/local/share/music-artwork-finder/music_cache.py "$PAYLOAD/usr/local/bin/music-cache"
ln -sf /usr/local/share/music-artwork-finder/fix_album.py "$PAYLOAD/usr/local/bin/music-fix"
ln -sf /usr/local/share/music-artwork-finder/resolve_splits.py "$PAYLOAD/usr/local/bin/music-splits"
ln -sf /usr/local/share/music-artwork-finder/undo_last.py "$PAYLOAD/usr/local/bin/music-undo"

chmod +x "$ROOT/packaging/scripts/preinstall" "$ROOT/packaging/scripts/postinstall"
chmod +x "$PAYLOAD/usr/local/share/music-artwork-finder/scripts/setup-user.sh"
chmod +x "$PAYLOAD/usr/local/share/music-artwork-finder/"*.py

sed "s/@VERSION@/$VERSION/g" "$ROOT/packaging/distribution.xml.in" > "$DISTRIBUTION_XML"

pkgbuild \
    --root "$PAYLOAD" \
    --scripts "$ROOT/packaging/scripts" \
    --identifier "$IDENTIFIER" \
    --version "$VERSION" \
    --install-location / \
    "$COMPONENT_PKG"

productbuild \
    --distribution "$DISTRIBUTION_XML" \
    --package-path "$BUILD_DIR" \
    --resources "$ROOT/packaging/resources" \
    "$OUTPUT_PKG"

echo "Built $OUTPUT_PKG"
