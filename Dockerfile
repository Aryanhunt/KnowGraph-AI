# =============================================================================
# KnowGraph AI — Render-ready multi-stage Dockerfile
#
# Single container that builds the React/Vite frontend and serves the Flask
# backend + frontend bundle on one port (5003).
#
# Usage (Render):
#   Build: docker build -t knowgraph-ai .
#   Run:   docker run -p 5003:5003 --env-file .env knowgraph-ai
# =============================================================================

# ---- Stage 1: Build frontend (React + Vite) ----
FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /app/frontend

# Copy package manifests
COPY frontend/package.json frontend/package-lock.json ./

# Install dependencies
RUN npm ci --omit=dev

# Copy source and build
COPY frontend/ .
RUN npm run build

# ---- Stage 2: Backend + served frontend ----
FROM python:3.14-slim-bookworm

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy built frontend
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Copy backend
COPY backend /app/backend

# Install Python deps
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Expose the Flask port (5003, per backend/wsgi.py)
EXPOSE 5003

# ---- Environment variables (see backend/.env.example) ----
# PORT             - Flask port (default 5003)
# SECRET_KEY       - JWT signing key (required)
# MONGODB_URI      - MongoDB connection string
# OLLAMA_BASE_URL  - Ollama API URL (default http://localhost:11434)
# OCR_ENABLED      - Set to false if OCR fails on Render
# LOG_LEVEL        - INFO (default)

COPY backend/.env.example /app/backend/.env

# Run the WSGI app (prod server)
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5003", "wsgi:app"]
