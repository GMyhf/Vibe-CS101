#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOL101_DIR="$ROOT/data/sol101"
LOG_DIR="$ROOT/data/logs"
LOCK_DIR="$ROOT/data/locks/sol101-update.lock"
NODE_DIR="$ROOT/data/node-v20.19.5-linux-x64"
NODE_TARBALL="$ROOT/data/node-v20.19.5-linux-x64.tar.xz"
NODE_URL="https://nodejs.org/dist/v20.19.5/node-v20.19.5-linux-x64.tar.xz"
GIT_TIMEOUT_S="${SOL101_GIT_TIMEOUT_S:-180}"
VIBE_UPDATE_TIMEOUT_S="${SOL101_VIBE_UPDATE_TIMEOUT_S:-300}"

mkdir -p "$LOG_DIR"
exec >>"$LOG_DIR/sol101-update.log" 2>&1

echo "[$(date -Is)] sol101 update started"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Another sol101 update is already running; exiting"
  exit 0
fi
trap 'rmdir "$LOCK_DIR"' EXIT

if [[ ! -d "$SOL101_DIR/.git" ]]; then
  echo "Cloning sol101 repository"
  timeout "$GIT_TIMEOUT_S" git clone --depth 1 https://github.com/FuYnAloft/sol101 "$SOL101_DIR"
elif [[ "${SKIP_SOL101_PULL:-0}" == "1" ]]; then
  echo "Skipping sol101 git pull; using existing checkout"
else
  echo "Updating sol101 repository"
  timeout "$GIT_TIMEOUT_S" git -C "$SOL101_DIR" pull --ff-only || echo "WARN: sol101 git pull failed; using existing checkout"
fi

if [[ "${SKIP_VIBE_UPDATE:-0}" == "1" ]]; then
  echo "Skipping Vibe-CS101 solution update; using existing local cache"
else
  echo "Updating Vibe-CS101 solution cache"
  timeout "$VIBE_UPDATE_TIMEOUT_S" python3 -m vibe_cs101 update || echo "WARN: Vibe-CS101 solution update failed; using existing local cache"
fi
echo "Preparing sol101 originals"
python3 "$ROOT/scripts/update_sol101.py"

cd "$SOL101_DIR"
echo "Installing Python dependencies"
uv sync --no-dev

node_major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
if [[ "$node_major" -lt 20 ]]; then
  if [[ ! -x "$NODE_DIR/bin/node" ]]; then
    echo "Installing local Node.js 20 from $NODE_URL"
    curl -fsSL "$NODE_URL" -o "$NODE_TARBALL"
    tar -xJf "$NODE_TARBALL" -C "$ROOT/data"
  fi
  export PATH="$NODE_DIR/bin:$PATH"
fi

echo "Using node $(node --version)"
echo "Installing npm dependencies"
npm ci
echo "Generating VitePress sources"
SITE_BASE="/sol101/" uv run python - <<'PY'
from config import ANSWERS
from generate import generate

wanted = {"oj-dsa", "oj", "cf"}
generate([answer for answer in ANSWERS if answer.name in wanted])
PY

export NODE_OPTIONS=--max-old-space-size=8192
echo "Building VitePress site"
npm run docs:build

echo "[$(date -Is)] sol101 update finished"
