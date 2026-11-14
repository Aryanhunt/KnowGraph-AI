#!/usr/bin/env bash
# =============================================================================
# KnowGraph AI — one-command launcher
#
#   ./start-all.sh          check + start everything
#   ./start-all.sh --check  only run the checks, start nothing
#   ./start-all.sh stop     stop backend + frontend (MongoDB/Ollama stay up)
#   ./start-all.sh stop     stop backend + frontend (MongoDB/Ollama stay up)
#
# Checks and starts, in order:
#   1. MongoDB        (brew services / mongod)  — metadata store
#   2. Ollama         (ollama serve)            — local LLM runtime
#      + models       (ollama pull, only if missing — one-time download)
#   3. Backend        (Flask on :5003)          — creates .venv and .env if needed
#   4. Frontend       (Vite on :5173)           — runs npm install if needed
#
# Idempotent: anything already running is detected and left alone.
# Logs: backend.log / frontend.log / ollama.log in the project root.
# =============================================================================

set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
CHECK_ONLY=0
ACTION="${1:-start}"
[[ "$ACTION" == "--check" || "$ACTION" == "check" ]] && CHECK_ONLY=1

do_stop() {
  echo "Stopping KnowGraph AI processes..."
  if pkill -f 'wsgi.py' 2>/dev/null; then echo "  stopped: backend (Flask)"
  else echo "  backend was not running"; fi
  if pkill -f '[v]ite' 2>/dev/null; then echo "  stopped: frontend (vite)"
  else echo "  frontend was not running"; fi
  echo ""
  echo "MongoDB and Ollama left running on purpose (system services)."
  echo "  brew services stop mongodb-community   # stop MongoDB too"
  echo "  pkill ollama                           # stop Ollama too"
}

if [[ "$ACTION" == "stop" || "$ACTION" == "close" || "$ACTION" == "down" ]]; then
  do_stop
  exit 0
fi

ok()   { printf "  \033[32mOK\033[0m %s\n" "$1"; }
fix()  { printf "  \033[33m->\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31mXX\033[0m %s\n" "$1"; }
head() { printf "\n== %s ==\n" "$1"; }

port_up()       { curl -sf -o /dev/null --max-time 3 "$1"; }
wait_for_port() { # <url> <seconds> <name>
  local url="$1" seconds="$2" name="$3" waited=0
  while ! port_up "$url"; do
    sleep 2; waited=$((waited + 2))
    if (( waited >= seconds )); then bad "$name not ready after ${seconds}s"; return 1; fi
  done
  ok "$name is ready"
}

echo "=============================================="
echo " KnowGraph AI - local-first knowledge system"
echo "=============================================="
cd "$ROOT"

# ---------------------------------------------------------------------------
# 1. MongoDB
# ---------------------------------------------------------------------------
head "1/4  MongoDB (metadata store)"
MONGO_OK=0
if mongosh --quiet --eval 'db.runCommand({ping:1})' >/dev/null 2>&1; then
  ok "MongoDB is running and answering pings"
  MONGO_OK=1
elif command -v mongosh >/dev/null 2>&1 || command -v mongod >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1 \
     && brew services list 2>/dev/null | grep -q '^mongodb-community stopped'; then
    fix "starting mongodb-community via brew services..."
    brew services start mongodb-community >/dev/null 2>&1 || true
  elif command -v mongod >/dev/null 2>&1; then
    fix "starting a standalone mongod (data in ~/.knowgraph-mongo)..."
    mkdir -p "$HOME/.knowgraph-mongo"
    (mongod --dbpath "$HOME/.knowgraph-mongo" --fork \
        --logpath "$HOME/.knowgraph-mongo/mongod.log" >/dev/null 2>&1 || true)
  fi
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if mongosh --quiet --eval 'db.runCommand({ping:1})' >/dev/null 2>&1; then MONGO_OK=1; break; fi
    sleep 2
  done
  if (( MONGO_OK )); then ok "MongoDB is now running"; else bad "MongoDB still unreachable"; fi
else
  bad "MongoDB is not installed"
  fix "brew tap mongodb/brew && brew install mongodb-community && brew services start mongodb-community"
fi
# ---------------------------------------------------------------------------
# 2. Ollama + models
# ---------------------------------------------------------------------------
head "2/4  Ollama (local LLM runtime)"
OLLAMA_OK=0
if command -v ollama >/dev/null 2>&1; then
  if port_up "http://127.0.0.1:11434/api/tags"; then
    ok "Ollama daemon is already running"
    OLLAMA_OK=1
  else
    fix "starting ollama serve..."
    (nohup ollama serve > "$ROOT/ollama.log" 2>&1 &)
    for _ in 1 2 3 4 5 6 7 8; do
      sleep 2
      if port_up "http://127.0.0.1:11434/api/tags"; then OLLAMA_OK=1; break; fi
    done
    if (( OLLAMA_OK )); then ok "Ollama is now running (log: ollama.log)"
    else bad "Ollama did not start - see ollama.log"; fi
  fi

  # Models: read the configured names from backend/.env, pull only if missing.
  if (( OLLAMA_OK )); then
    LLM_MODEL="$(grep -E '^LLM_MODEL=' "$BACKEND/.env" 2>/dev/null | cut -d= -f2 | tr -d '\"')"
    EMBED_MODEL="$(grep -E '^EMBEDDING_MODEL=' "$BACKEND/.env" 2>/dev/null | cut -d= -f2 | tr -d '\"')"
    LLM_MODEL="${LLM_MODEL:-qwen2.5:3b-instruct}"
    EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"
    INSTALLED="$(ollama list 2>/dev/null || true)"

    for model in "$LLM_MODEL" "$EMBED_MODEL"; do
      base="${model%%:*}"
      if grep -qE "(^|[[:space:]])${model}([[:space:]]|$)|(^|[[:space:]])${base}(:|$)" <<<"$INSTALLED"; then
        ok "model present: $model"
      elif (( CHECK_ONLY )); then
        bad "model missing: $model  (run: ollama pull $model)"
      else
        fix "pulling $model (one-time download, please wait)..."
        ollama pull "$model" >/dev/null 2>&1 \
          && ok "model pulled: $model" \
          || bad "could not pull $model - run 'ollama pull $model' manually"
      fi
    done
  fi
else
  bad "Ollama is not installed"
  fix "brew install ollama   (or download from https://ollama.com)"
fi

# ---------------------------------------------------------------------------
# 3. Backend
# ---------------------------------------------------------------------------
head "3/4  Backend (Flask on http://127.0.0.1:5003)"
if port_up "http://127.0.0.1:5003/api/health"; then
  ok "backend is already running on :5003"
elif (( CHECK_ONLY )); then
  bad "backend is not running"
else
  cd "$BACKEND"
  if [ ! -d .venv ]; then
    fix "creating Python virtual environment (first run, a few minutes)..."
    python3 -m venv .venv \
      && .venv/bin/pip install --upgrade pip --quiet \
      && .venv/bin/pip install -r requirements.txt --quiet \
      && ok "virtual environment created" \
      || bad "could not create the virtual environment"
  fi
  if [ ! -f .env ]; then
    fix "creating .env from .env.example - edit SECRET_KEY before sharing!"
    cp .env.example .env
  fi
  fix "starting backend..."
  (nohup .venv/bin/python wsgi.py > "$ROOT/backend.log" 2>&1 &)
  wait_for_port "http://127.0.0.1:5003/api/health" 30 "backend" \
    || bad "see backend.log for the error"
  cd "$ROOT"
fi
# ---------------------------------------------------------------------------
# 4. Frontend
# ---------------------------------------------------------------------------
head "4/4  Frontend (Vite on http://localhost:5173)"
if port_up "http://localhost:5173/"; then
  ok "frontend is already running on :5173"
elif (( CHECK_ONLY )); then
  bad "frontend is not running"
else
  cd "$FRONTEND"
  if [ ! -d node_modules ]; then
    fix "installing npm dependencies (first run)..."
    npm install --no-audit --no-fund --silent \
      && ok "dependencies installed" \
      || bad "npm install failed"
  fi
  fix "starting frontend..."
  (nohup npm run dev > "$ROOT/frontend.log" 2>&1 &)
  wait_for_port "http://localhost:5173/" 30 "frontend" \
    || bad "see frontend.log for the error"
  cd "$ROOT"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
head "Status summary"
print_state() { # <name> <running-label> <url-label>
  printf "  %-11s %s\n" "$1" "$2"
}
[[ ${MONGO_OK:-0} == 1 ]] && print_state "MongoDB"  "running" || print_state "MongoDB"  "NOT RUNNING"
[[ ${OLLAMA_OK:-0} == 1 ]] && print_state "Ollama"   "running" || print_state "Ollama"   "NOT RUNNING"
if port_up "http://127.0.0.1:5003/api/health"; then
  print_state "Backend"  "running  -> http://127.0.0.1:5003"
else
  print_state "Backend"  "NOT RUNNING"
fi
if port_up "http://localhost:5173/"; then
  print_state "Frontend" "running  -> http://localhost:5173"
else
  print_state "Frontend" "NOT RUNNING"
fi

echo
if port_up "http://localhost:5173/"; then
  echo "Open the app:            http://localhost:5173"
  echo "Service status in UI:    Settings page (or GET /api/system/health)"
  echo "Logs:                    backend.log, frontend.log, ollama.log"
  echo "Stop backend+frontend:   ./start-all.sh stop"
elif (( CHECK_ONLY )); then
  echo "Check-only mode: nothing was started. Run ./start-all.sh to launch."
fi
echo