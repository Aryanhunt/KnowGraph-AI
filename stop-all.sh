#!/usr/bin/env bash
# =============================================================================
# KnowGraph AI — stop everything started by start-all.sh
#
#   ./stop-all.sh
#
# Stops the Flask backend and the Vite dev server. MongoDB and Ollama are left
# running on purpose (they are system services shared with other projects) —
# use `brew services stop mongodb-community` if you want them off too.
# =============================================================================

set -uo pipefail

stopped=0

if pkill -f 'wsgi.py' 2>/dev/null; then
  echo "Stopped: backend (wsgi.py)"
  stopped=1
else
  echo "Backend was not running"
fi

if pkill -f 'vite' 2>/dev/null; then
  echo "Stopped: frontend (vite)"
  stopped=1
else
  echo "Frontend was not running"
fi

if (( stopped )); then
  echo "Done. MongoDB and Ollama are still running — stop them with:"
  echo "  brew services stop mongodb-community"
  echo "  (Ollama stops with Cmd+Q on its menu-bar icon, or pkill ollama)"
fi