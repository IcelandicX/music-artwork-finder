#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
TAG="v${VERSION}"

cd "$ROOT"
git diff --quiet
git diff --cached --quiet

if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "Tag already exists: $TAG" >&2
    exit 1
fi

git tag -a "$TAG" -m "Music Fix ${VERSION}"
git push origin "$TAG"
echo "Pushed $TAG. GitHub Actions will build and attach the pkg."
