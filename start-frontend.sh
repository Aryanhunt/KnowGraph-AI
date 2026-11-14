#!/usr/bin/env bash
# Start the KnowGraph AI frontend.
# Usage: ./start-frontend.sh   (from the project root)

set -euo pipefail
cd "$(dirname "$0")/frontend"

if [ ! -d node_modules ]; then
  echo "Installing npm dependencies (first run)…"
  npm install --no-audit --no-fund
fi

echo "Starting the Vite dev server on http://localhost:5173"
exec npm run dev