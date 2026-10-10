# CutMind — setup

Everything is free and open source: no API keys to buy, no paid cloud AI. The AI model runs **inside
the backend** (ONNX Runtime on CPU), so the same setup works on a laptop and on a server.

## Requirements

| Tool | Version used while building | Needed for | Install |
|---|---|---|---|
| Python | 3.13.15 (3.11+ works; Docker image uses 3.12) | backend | `winget install Python.Python.3.13` / python.org |
| Node.js + npm | 24.19 / 11.17 | mobile app | `winget install OpenJS.NodeJS.LTS` |
| FFmpeg + ffprobe | 9.0.1 (gyan.dev essentials) | rendering, analysis | `winget install Gyan.FFmpeg.Essentials` · `brew install ffmpeg` · `sudo apt install ffmpeg` |
| Docker (optional) | – | server deployment | Docker Desktop / Docker Engine |
| Android SDK / emulator (optional) | not installed here | native dev build | Android Studio |

Models (downloaded once from Hugging Face, cached in `~/.cache/huggingface` or `HF_HOME`):

| Model | Size | License | Used for |
|---|---|---|---|
| `onnx-community/Qwen2.5-1.5B-Instruct` → `onnx/model_q4.onnx` (standard) | ~1.8 GB | Apache-2.0 | prompt → edit intent (`PLANNER_MODE=local`) |
| `onnx-community/Qwen2.5-0.5B-Instruct` → `onnx/model_q4.onnx` (lite) | ~0.8 GB | Apache-2.0 | same, ~5× faster on low-RAM machines, less accurate |

`LLM_REPO=auto` (default) picks standard when ≥3.5 GB RAM is free at startup, else lite.
| `Systran/faster-whisper-tiny` | ~75 MB | MIT | speech-to-text for captions |

## Local (one command)

```bat
setup.bat
```
or on macOS / Linux / Git Bash:
```bash
./setup.sh
```
The script checks Python/Node/FFmpeg (installs FFmpeg with winget on Windows), creates
`backend/.venv`, installs `backend/requirements-dev.txt`, generates two royalty-free music beds into
`backend/assets/music`, runs `npm install` in `mobile/`, and pre-downloads the models
(`python -m cutmind.prefetch`).

Run everything:
```bat
run-all.bat
```
Backend http://localhost:8000/docs · Web app http://localhost:8081. `run-all` uses `PLANNER_MODE=local`;
set `PLANNER_MODE=mock` for the rules-only planner (no model, instant).

## Server / production (Docker)

```bash
cp .env.example .env          # set a long random CUTMIND_API_KEY
docker compose up -d --build  # image bakes in FFmpeg + LLM + whisper, runs as a non-root user
curl http://<server>:8000/health
```
* Data (SQLite, uploads, renders) lives in the `cutmind-data` volume (`/data`).
* Put it behind HTTPS (Caddy / nginx / a cloud load balancer); the API key is a shared secret.
* Memory: measured peak ~1.9 GB for the backend process with the 1.5B model + whisper loaded (plus
  short-lived FFmpeg processes); the compose file caps the container at 6 GB. Plan for 4 GB RAM minimum.
* One container processes one edit at a time (in-process queue). Scale by running more containers with
  separate data volumes, or move the queue out (see TEST_REPORT next steps).

In the mobile app's Settings enter the server URL and the API key.

Android development build (needs Android SDK; not tested on this PC):
```bash
cd mobile
npx expo run:android
```
Backend URL in Settings: `http://10.0.2.2:8000` (emulator), your PC's LAN IP (phone on the same Wi-Fi) or
your server's HTTPS URL.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `PLANNER_MODE` | `mock` (`local` in run-all and Docker) | `mock` = keyword rules only, `local` = in-process LLM + keyword guard (falls back to rules on any model failure) |
| `LLM_REPO` / `LLM_FILE` | `auto` / `onnx/model_q4.onnx` | `auto` = Qwen2.5-1.5B if ≥3.5 GB RAM is free at startup, else Qwen2.5-0.5B; or any Qwen2-style ONNX repo on Hugging Face |
| `LLM_MODEL_DIR` | – | use a local folder (model + `tokenizer.json` + `config.json`) instead of downloading |
| `LLM_AGENTS` | `director` | which agents ask the model: `director` (1 call/job) or `all` |
| `LLM_THREADS` / `LLM_MAX_NEW_TOKENS` / `LLM_PRELOAD` | physical cores / `120` / `true` | CPU threads, answer length cap, load the model at startup |
| `CUTMIND_API_KEY` | – | when set, every route except `/health` and docs needs `X-API-Key` |
| `CORS_ORIGINS` | `*` | comma-separated browser origins |
| `WHISPER_MODEL` / `ENABLE_TRANSCRIPTION` | `tiny` / `true` | speech-to-text |
| `CUTMIND_DATA_DIR` | `./data` | projects, uploads, renders, SQLite |
| `MUSIC_DIR` | `backend/assets/music` | royalty-free tracks (`upbeat`/`calm` in the name helps selection) |
| `MAX_UPLOAD_MB` / `MAX_CLIPS` | `500` / `20` | upload limits |
| `SCORE_THRESHOLD` / `MAX_AGENT_RETRIES` | `70` / `2` | reviewer retry policy |
| `FFMPEG_BIN` / `FFPROBE_BIN` | auto (PATH, then winget folder) | explicit binaries |
| `KEEP_WORK_DIRS` | `false` | keep temp render folders for debugging |

## Tests

```bash
cd backend
.venv/Scripts/python -m pytest ../tests -q                                          # mock planner (Windows path; .venv/bin elsewhere)
E2E_PLANNER_MODE=local .venv/Scripts/python -m pytest ../tests/integration/test_e2e_api.py   # with the real model
cd ../mobile && npm run typecheck && npm run lint && npm test && npm run build:web
```

## Windows notes found while building

* **Smart App Control** (Windows 11) blocks unsigned DLLs: it blocked `numba 0.68` (pinned `<0.63`),
  `llama-cpp-python` (that's why the LLM runs on Microsoft-signed ONNX Runtime instead) and, after a few
  days, PyAV (`av`). faster-whisper only needs PyAV at import time, so CutMind registers a placeholder
  when PyAV can't load — transcription still works because audio is decoded by FFmpeg. None of this
  applies on Linux servers / Docker.
* winget adds FFmpeg to PATH only for **new** terminals; the backend also searches the winget folder.
* Hugging Face prints a symlink warning on Windows; harmless (`HF_HUB_DISABLE_SYMLINKS_WARNING=1`).
