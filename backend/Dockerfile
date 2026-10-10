# CutMind backend — production image (CPU only, no external AI services).
# Build from the repository root:   docker build -f backend/Dockerfile -t cutmind-backend .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models \
    CUTMIND_DATA_DIR=/data \
    CUTMIND_MODELS_DIR=/models \
    PLANNER_MODE=mock \
    LLM_PROVIDER=llamaserver

# ffmpeg = renderer + analysis; fontconfig/DejaVu so libass can draw captions
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fontconfig fonts-dejavu-core fonts-noto-core curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY backend/ /app/

# The planner LLM (GGUF) is NOT baked in: it lives in the `cutmind-models` volume, filled once by
# `docker compose run --rm models` (scripts/download_models.py, checksum-verified) and served by llama-server.
RUN python -m cutmind.media_gen --music assets/music

RUN useradd --create-home --uid 10001 cutmind && mkdir -p /data /models && chown -R cutmind /data /models /app
USER cutmind

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD curl -fsS http://localhost:8000/health || exit 1
# one worker: jobs run in an in-process queue (see ARCHITECTURE.md); rendering never runs on the LLM server
CMD ["uvicorn", "cutmind.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
