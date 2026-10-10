# Local setup (CPU only)

Full details: SETUP.md. Short version on Windows:

```bash
winget install Gyan.FFmpeg.Essentials
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt
PLANNER_MODE=mock .venv/Scripts/python -m uvicorn cutmind.api:create_app --factory --port 8000
```

```bash
cd mobile
npm install
npx expo start --web --port 8081
```

Open http://localhost:8081 (studio editor on a wide window) and http://localhost:8000/docs.

* Local LLM planner: `PLANNER_MODE=local` (first run downloads ~1 GB; `python -m cutmind.prefetch` to pre-download).
* MCP server for desktop AI clients: see MCP.md.
* Check the machine: http://localhost:8000/capabilities.
* Keep the project folder **outside OneDrive** (or "Always keep on this device") — see TROUBLESHOOTING.md.
