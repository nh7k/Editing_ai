#!/usr/bin/env bash
# Start the CutMind backend (port 8000) and the Expo web app (port 8081). Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"
export PLANNER_MODE="${PLANNER_MODE:-local}"
VPY=backend/.venv/bin/python; [ -x "$VPY" ] || VPY=backend/.venv/Scripts/python.exe
(cd backend && "../$VPY" -m uvicorn cutmind.api:create_app --factory --host 0.0.0.0 --port 8000) &
BACK=$!
trap 'kill $BACK 2>/dev/null' EXIT
echo "Backend: http://localhost:8000/docs   App: http://localhost:8081"
cd mobile && npx expo start --web --port 8081
