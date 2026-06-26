#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Checking Python syntax..."
python3 -m py_compile \
    find_artwork.py \
    find_tags.py \
    music_ai.py \
    music_analyze.py \
    music_cache.py \
    music_combine.py \
    music_doctor.py \
    music_duplicates.py \
    music_prefs.py \
    music_resplit.py \
    fix_album.py \
    menu_bar.py \
    music_common.py \
    preferences.py \
    run_report.py \
    search_cache.py \
    search_providers.py \
    resolve_splits.py \
    undo_history.py \
    undo_last.py \
    assets/generate-icons.py

echo "Checking shell syntax..."
bash -n install.sh
bash -n scripts/setup-user.sh
bash -n scripts/tag-release.sh
bash -n packaging/build-pkg.sh
bash -n packaging/scripts/preinstall
bash -n packaging/scripts/postinstall

echo "Checking required files..."
required=(
    README.md
    VERSION
    requirements.txt
    assets/menubar-template@2x.png
    assets/MusicFix.icns
    packaging/distribution.xml.in
)
for file in "${required[@]}"; do
    if [[ ! -e "$file" ]]; then
        echo "Missing required file: $file" >&2
        exit 1
    fi
done

echo "Building installer package..."
./packaging/build-pkg.sh

OUTPUT_PKG="dist/MusicFix-$(tr -d '[:space:]' < VERSION).pkg"
if [[ ! -f "$OUTPUT_PKG" ]]; then
    echo "Expected package was not created: $OUTPUT_PKG" >&2
    exit 1
fi

if tar -tf build/pkg/MusicFix-component.pkg/Payload 2>/dev/null | grep -q '__pycache__'; then
    echo "Package payload unexpectedly contains __pycache__" >&2
    exit 1
fi

echo "Verification passed."
echo "Release artifact: $OUTPUT_PKG"
