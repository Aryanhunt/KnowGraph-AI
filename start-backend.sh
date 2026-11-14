#!/usr/bin/env bash
# Start the KnowGraph AI backend.
# Usage: ./start-backend.sh   (from the project root)

set -euo pipefail
cd "$(dirname "$0")/backend"

if [ ! -d .venv ]; then
  echo "Creating the Python virtual environment (first run)…"
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi

if [ ! -f .env ]; then
  echo "Creating backend/.env from .env.example — edit SECRET_KEY before sharing!"
  cp .env.example .env
fi

echo "Starting KnowGraph AI backend on http://127.0.0.1:5003"
exec .venv/bin/python wsgi.py