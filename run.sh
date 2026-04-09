#!/bin/bash
# AirControl — Enterprise Startup Script

# Safe bash mode
set -euo pipefail

function cleanup() {
    echo ""
    echo "[AirControl] Shutting down..."
    # Kill background jobs
    jobs -p | xargs -r kill
}
trap cleanup EXIT

echo "============================================="
echo "   AirControl — Neural Command Center        "
echo "============================================="

echo "[1/2] Starting Vision Engine & API (Port 8000)..."
cd backend
source venv/bin/activate
# Optional: install deps if missing
# pip install -r requirements.txt --quiet >/dev/null 2>&1

# Kill any existing process on port 8000 to prevent EADDRINUSE
lsof -ti:8000 | xargs -r kill -9 || true
sleep 1

uvicorn main:app --host 0.0.0.0 --port 8000 --log-level warning &
cd ..

echo "Waiting for API to initialize..."
sleep 2

echo "[2/2] Starting Tauri Desktop App..."
npm run tauri dev

# Wait for background jobs (API)
wait
