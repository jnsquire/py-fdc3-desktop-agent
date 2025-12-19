#!/usr/bin/env bash
set -euo pipefail

echo "Bootstrapping dev environment (POSIX)..."

if [ ! -x "./.venv/bin/python" ]; then
  echo "Virtualenv not found at ./.venv - create one first or use your preferred setup." >&2
fi

echo "Installing dev dependencies into .venv..."
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e '.[dev]'

echo "Installing pre-commit hooks..."
./.venv/bin/pre-commit install --install-hooks

echo "Running pre-commit on all files (this may autofix some issues)..."
./.venv/bin/pre-commit run --all-files || true

echo "Bootstrap complete."
