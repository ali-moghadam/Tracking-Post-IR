#!/usr/bin/env bash
# Run project locally: venv setup, deps install, start server.
set -euo pipefail

cd "$(dirname "$0")"

VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating venv at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "Installing deps..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    echo "No .env found, copying .env.example..."
    cp .env.example .env
fi

echo "Starting app (python main.py)..."
python main.py