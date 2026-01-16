#!/usr/bin/env bash
set -euo pipefail

# ---------- settings ----------
KERNEL_NAME="myproject-venv"
DISPLAY_NAME="Python (myproject .venv)"

# ---------- paths (workspace-only) ----------
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JUPYTER_DIR="$ROOT/.jupyter"

export JUPYTER_PATH="$JUPYTER_DIR/share/jupyter"
export JUPYTER_CONFIG_DIR="$JUPYTER_DIR/config"
export JUPYTER_RUNTIME_DIR="$JUPYTER_DIR/runtime"
export JUPYTER_DATA_DIR="$JUPYTER_DIR/data"

KERNEL_DIR="$JUPYTER_DIR/share/jupyter/kernels/$KERNEL_NAME"
KERNEL_JSON="$KERNEL_DIR/kernel.json"

# ---------- ensure dirs ----------
mkdir -p "$JUPYTER_PATH/kernels" "$JUPYTER_CONFIG_DIR" "$JUPYTER_RUNTIME_DIR" "$JUPYTER_DATA_DIR"

# ---------- ensure deps (safe if already installed) ----------
# If you manage deps via pyproject, consider doing this once manually:
#   uv add jupyterlab ipykernel
# This line is harmless to re-run; uv will keep things consistent.
uv pip install -q jupyterlab ipykernel

# ---------- register local kernelspec if missing ----------
if [[ ! -f "$KERNEL_JSON" ]]; then
  uv run python -m ipykernel install \
    --prefix "$JUPYTER_DIR" \
    --name "$KERNEL_NAME" \
    --display-name "$DISPLAY_NAME"
  echo "✅ Installed kernelspec: $KERNEL_NAME"
else
  echo "✅ Kernelspec already present: $KERNEL_NAME"
fi

# ---------- start jupyter lab ----------
# Clean stale runtime only if you want (safe before start):
# rm -rf "$JUPYTER_RUNTIME_DIR"/*

cd "$ROOT"
exec uv run jupyter lab --notebook-dir="$ROOT"