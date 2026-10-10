@echo off
REM Start the CutMind backend (port 8000) and the Expo web app (port 8081) in two windows.
REM PLANNER_MODE=local (default here) runs the small Hugging Face model in-process; set PLANNER_MODE=mock for rules only.
cd /d "%~dp0"
if "%PLANNER_MODE%"=="" set PLANNER_MODE=local
start "CutMind backend" cmd /k "cd /d backend && .venv\Scripts\python.exe -m uvicorn cutmind.api:create_app --factory --host 0.0.0.0 --port 8000"
start "CutMind app" cmd /k "cd /d mobile && npx expo start --web --port 8081"
echo Backend:  http://localhost:8000/docs
echo App:      http://localhost:8081   (Android dev build: cd mobile ^&^& npx expo run:android)
