#!/usr/bin/env bash
# Build the shared web UI and stage it into each plugin tree so the
# VSCode and JetBrains clients can serve it from their own bundle.
#
# Run from the repo root:   scripts/build-clients.sh
# Or from anywhere:         /abs/path/to/scripts/build-clients.sh
#
# Side effects:
#   • npm run build in clients/web/         (fresh dist/)
#   • clients/vscode/media/                  ← copy of dist/
#   • clients/jetbrains/src/main/resources/webui/   ← copy of dist/
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

WEB_DIR="$ROOT/clients/web"
WEB_DIST="$WEB_DIR/dist"
VSCODE_MEDIA="$ROOT/clients/vscode/media"
JETBRAINS_WEBUI="$ROOT/clients/jetbrains/src/main/resources/webui"

echo "→ Building web client…"
(cd "$WEB_DIR" && npm run build)

if [[ ! -d "$WEB_DIST" ]]; then
    echo "ERROR: $WEB_DIST not produced by the web build" >&2
    exit 1
fi

stage() {
    local dest="$1"
    echo "→ Staging $(basename "$(dirname "$dest")")/$(basename "$dest")…"
    rm -rf "$dest"
    mkdir -p "$dest"
    # Copy contents (not the dist dir itself) into dest.
    cp -R "$WEB_DIST"/. "$dest"/
}

stage "$VSCODE_MEDIA"
stage "$JETBRAINS_WEBUI"

echo "✓ Done. VSCode media + JetBrains webui resources refreshed."
