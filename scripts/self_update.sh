#!/usr/bin/env bash
# Self-update script for Azelia Clips.
#
# Called from POST /api/system/update (server/routes/system.py).
# - Pulls latest main from GitHub
# - Reinstalls Python deps
# - Rebuilds frontend
# - Signals server to restart via ~/.azelia/data/.restart sentinel
#
# Critically: never touches ~/.azelia/data/ — that's user content (clips,
# SQLite DBs, secrets). Only the git checkout and venv are modified.

set -euo pipefail

AZELIA_HOME="${AZELIA_HOME:-$HOME/.azelia}"

# Checkout can be either:
#   $AZELIA_HOME/azelia/.git  (new layout, clean separation from data/)
#   $AZELIA_HOME/.git         (legacy layout, install.sh clones into root)
if [ -n "${AZELIA_CHECKOUT:-}" ]; then
    CHECKOUT_DIR="$AZELIA_CHECKOUT"
elif [ -d "$AZELIA_HOME/azelia/.git" ]; then
    CHECKOUT_DIR="$AZELIA_HOME/azelia"
else
    CHECKOUT_DIR="$AZELIA_HOME"
fi

VENV_DIR="${AZELIA_VENV:-$AZELIA_HOME/venv}"
DATA_DIR="${AZELIA_DATA_DIR:-$AZELIA_HOME/data}"
LOG="$DATA_DIR/update.log"
LOCK="$DATA_DIR/update.lock"
RESTART_SENTINEL="$DATA_DIR/.restart"

mkdir -p "$DATA_DIR"

# Ensure lock is cleared on exit no matter what
trap 'rm -f "$LOCK"' EXIT
touch "$LOCK"

# All output goes to log
exec >> "$LOG" 2>&1
echo "=== Update started $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "AZELIA_HOME=$AZELIA_HOME"
echo "CHECKOUT_DIR=$CHECKOUT_DIR"
echo "VENV_DIR=$VENV_DIR"

cd "$CHECKOUT_DIR"

# Refuse if not a git checkout (dev mode wouldn't have run this anyway)
if [ ! -d .git ]; then
    echo "Error: $CHECKOUT_DIR is not a git checkout. Aborting."
    exit 1
fi

# Refuse if working tree is dirty — user has local edits
if [ -n "$(git status --porcelain)" ]; then
    echo "Error: working tree is dirty in $CHECKOUT_DIR. Refusing to overwrite local changes."
    echo "Resolve manually with 'git stash' or 'git reset --hard origin/main' before retrying."
    exit 1
fi

echo "[fetching] git fetch origin main"
# --force on tags: a tag that moved upstream (a re-cut release, a corrected tag)
# is otherwise rejected with "would clobber existing tag", git exits 1, and
# `set -e` aborts the whole update before it starts. We hard-reset to
# origin/main below anyway, so upstream is always the authority on tags too.
git fetch origin main --tags --force

CURRENT_SHA="$(git rev-parse HEAD)"
LATEST_SHA="$(git rev-parse origin/main)"
if [ "$CURRENT_SHA" = "$LATEST_SHA" ]; then
    echo "Already on latest commit ($CURRENT_SHA). Nothing to do."
    echo "=== Update done (no-op) $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
    exit 0
fi

echo "[fetching] $CURRENT_SHA -> $LATEST_SHA"
git reset --hard origin/main

echo "[installing] pip install -e ."
if [ -d "$VENV_DIR" ]; then
    "$VENV_DIR/bin/pip" install -e . --quiet
else
    # dev fallback
    pip install -e . --quiet
fi

echo "[building] npm install + npm run build"
if [ -d "$CHECKOUT_DIR/web" ]; then
    cd "$CHECKOUT_DIR/web"
    npm install --silent
    npm run build
    cd "$CHECKOUT_DIR"
fi

echo "[restarting] signaling server"
touch "$RESTART_SENTINEL"

echo "=== Update done $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
