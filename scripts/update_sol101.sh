#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOL101_DIR="$ROOT/data/sol101"
LOG_DIR="$ROOT/data/logs"
LOCK_PARENT="$ROOT/data/locks"
LOCK_DIR="$LOCK_PARENT/sol101-update.lock"
NODE_DIR="$ROOT/data/node-v20.19.5-linux-x64"
NODE_TARBALL="$ROOT/data/node-v20.19.5-linux-x64.tar.xz"
NODE_URL="https://nodejs.org/dist/v20.19.5/node-v20.19.5-linux-x64.tar.xz"
GIT_TIMEOUT_S="${SOL101_GIT_TIMEOUT_S:-180}"
VIBE_UPDATE_TIMEOUT_S="${SOL101_VIBE_UPDATE_TIMEOUT_S:-300}"

mkdir -p "$LOG_DIR" "$LOCK_PARENT"
exec >>"$LOG_DIR/sol101-update.log" 2>&1

echo "[$(date -Is)] sol101 update started"

acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$$" >"$LOCK_DIR/pid"
    return 0
  fi

  if [[ -f "$LOCK_DIR/pid" ]]; then
    old_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
    if [[ "$old_pid" =~ ^[0-9]+$ ]] && ! kill -0 "$old_pid" 2>/dev/null; then
      echo "Removing stale sol101 update lock for pid $old_pid"
      rm -f "$LOCK_DIR/pid"
      rmdir "$LOCK_DIR" 2>/dev/null || true
      if mkdir "$LOCK_DIR" 2>/dev/null; then
        echo "$$" >"$LOCK_DIR/pid"
        return 0
      fi
    fi
  fi

  return 1
}

if ! acquire_lock; then
  echo "Another sol101 update is already running; exiting"
  exit 0
fi
trap 'rm -f "$LOCK_DIR/pid"; rmdir "$LOCK_DIR"' EXIT

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

cd "$SOL101_DIR"
echo "Installing Python dependencies"
uv sync --no-dev
echo "Preparing sol101 originals"
uv run python "$ROOT/scripts/update_sol101.py"

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

generate(ANSWERS)
PY
uv run python - <<'PY'
from pathlib import Path

index = Path("docs/index.md")
text = index.read_text(encoding="utf-8")
text = text.replace(
    '  text: "OpenJudge 和 Codeforces的题解"',
    '  text: "OpenJudge、Codeforces、LeetCode、Sunnywhy、C++ 等题解"',
)
index.write_text(text, encoding="utf-8")
PY

export NODE_OPTIONS=--max-old-space-size=8192
echo "Building VitePress site"
npm run docs:build

echo "[$(date -Is)] sol101 update finished"
