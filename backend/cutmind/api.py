"""FastAPI application: projects, clip upload, edit jobs, plans, outputs, feedback, scoreboard."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import shutil
import tempfile
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from . import templates as tpl
from .agent_registry import REGISTRY, registry_summary, route
from .agents.analyzer import import_faster_whisper, voice_to_prompt
from .agents.audio import list_music
from .capabilities import detect as detect_capabilities
from .coach import understand
from .config import Settings, get_settings
from .db import AGENT_ROLES, Database, new_id
from .editorial import KNOWLEDGE_DIR, knowledge
from .ffmpeg_utils import FFmpegError, extract_audio_wav, ffmpeg_available, probe, save_frame_jpg
from .fx_catalog import TEXT_ANIMATIONS
from .fx_catalog import catalog as fx_catalog
from .intent import PromptError, parse_intent, validate_prompt
from .jobs import JobManager
from .learning import KNOBS, Learner
from .local_llm import LocalLLMClient, local_llm_status
from .lyrics import song_words
from .manual import ManualEdit, ManualError
from .media_views import filmstrip, frame_at, waveform
from .music_library import (
    SongError,
    import_song,
    music_dirs,
    project_music_dir,
    project_songs,
    resolve,
    selected_song,
    set_selected,
)
from .phrasebook import COMMANDS, PhraseBook
from .plan import EditPlan
from .proxy import existing_proxy, proxy_path
from .reference import analyze_reference, load_recipe, save_recipe
from .renderer import extra_path
from .song import analyze_song
from .styles import public_styles
from .text_styles import catalog as text_catalog
from .workflow import graph_mermaid

CHUNK = 1024 * 1024
VOICE_MAX_BYTES = 5 * CHUNK
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/docs/oauth2-redirect", "/redoc"}


def _warm_up_translator() -> None:
    """Models the chat needs, loaded at start (inside the first message they took 20-55 s)."""
    try:
        from .phrasebook import warm_up

        warm_up()  # "samajh nahi aaya, shayad ye?" suggestions
    except Exception:  # noqa: BLE001
        pass
    try:
        from .translator import Translator, trained_available

        if trained_available():
            t = Translator("trained")
            t.load()
            t.translate("thoda slow karo")  # the first generation is slow too (onnxruntime warms up)
    except Exception:  # noqa: BLE001 — the rules work without it
        pass


def _warm_up_planner() -> None:
    try:
        from .llm_provider import get_provider

        p = get_provider()
        if hasattr(p, "warm_up"):
            p.warm_up()
    except Exception:  # noqa: BLE001 — the rules answer until the model is there
        pass


def _warm_up_resolver() -> None:
    try:
        from .tools.resolve import warm

        warm()
    except Exception:  # noqa: BLE001 — built on the first request instead
        pass


class RateLimiter:
    """Edit requests per client per minute (in memory; one API process). 0 = off."""

    def __init__(self, per_min: int) -> None:
        self.per_min = per_min
        self.hits: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.per_min <= 0:
            return True
        import time as _t

        now = _t.monotonic()
        with self.lock:
            q = [t for t in self.hits.get(key, []) if now - t < 60.0]
            ok = len(q) < self.per_min
            if ok:
                q.append(now)
            self.hits[key] = q
            return ok


def _warm_up_llm(settings: Settings) -> None:
    try:
        LocalLLMClient(settings=settings).load()
    except Exception:  # noqa: BLE001 — jobs will report the problem (and fall back to rules)
        pass


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, extra: dict[str, Any] | None = None) -> None:
        self.status, self.code, self.message, self.extra = status, code, message, extra or {}


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class UnderstandIn(BaseModel):
    prompt: str = Field(max_length=2000)
    project_id: str | None = None  # with it, the footage helps classify the video



class CopyRunIn(BaseModel):
    prompt: str | None = Field(None, max_length=500)
    keep_sound: bool = True


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class ApplyIn(BaseModel):
    prompt: str | None = Field(None, max_length=500)

class EditIn(BaseModel):
    prompt: str = Field(max_length=2000)
    aspect_ratio: Literal["9:16", "1:1", "16:9"] | None = None
    resolution: Literal[360, 480, 720, 1080] | None = None
    variations: Literal[1, 2, 3] | None = None
    style: Literal["midnight_drift", "violet_authority", "cyan_kinetic"] | None = None
    music_track: str | None = Field(None, max_length=120, description="song for this edit (project or library file name)")
    at: float | None = Field(None, ge=0, le=36000, description="timeline comment: the second of the CURRENT edit "
                                                               "the message is about (only that moment changes)")


class TeachIn(BaseModel):
    phrase: str = Field(min_length=2, max_length=200)
    command: str = Field(min_length=2, max_length=120)


class SongSelectIn(BaseModel):
    name: str | None = Field(None, max_length=120)


class ChooseIn(BaseModel):
    variant: int = Field(ge=0, le=2)


class FeedbackIn(BaseModel):
    rating: Literal["up", "down"]
    comment: str | None = Field(None, max_length=500)
    agent: str | None = None


def _clip_out(c: dict[str, Any]) -> dict[str, Any]:
    return {k: c[k] for k in ("id", "filename", "duration", "width", "height", "fps", "size_bytes")} | {
        "has_audio": bool(c["has_audio"])}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.projects_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.db_path)
    jobs = JobManager(db, settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
        # jobs a crash / restart interrupted: resume from their LangGraph checkpoint (or start queued ones again)
        unfinished = db.all("SELECT id, project_id, prompt, options, status FROM jobs WHERE status IN ('queued','running') "
                            "ORDER BY created_at")
        keep = {r["id"] for r in unfinished}
        # other temp files from a crashed previous run are useless: clean them
        for work in settings.projects_dir.glob("*/work/*"):
            if work.name not in keep and not work.name.startswith("prep_"):
                shutil.rmtree(work, ignore_errors=True)
        for row in unfinished:
            try:
                jobs.restart(row["id"], row["project_id"], row["prompt"], json.loads(row["options"] or "{}"))
            except Exception as exc:  # noqa: BLE001 — never block startup
                db.update_job(row["id"], status="failed", error=f"Server restarted and the job could not resume: {exc}")
        if settings.planner_mode == "local" and settings.llm_preload:
            # load (and if needed download) the model in the background so the first job isn't slow
            threading.Thread(target=_warm_up_llm, args=(settings,), name="llm-warmup", daemon=True).start()
        # the Hinglish translator takes ~13 s to load: load it now, not inside the user's first request (that request
        # timed out in the app)
        threading.Thread(target=_warm_up_translator, name="translator-warmup", daemon=True).start()
        # the planner LLM (llama.cpp in-process): load it and cache its system prompt now — the first chat message
        # must not pay 10-30 s of model loading + prompt reading
        threading.Thread(target=_warm_up_planner, name="planner-warmup", daemon=True).start()
        # the skill resolver's index (~2 s): built now so the first unclear message is answered at once
        threading.Thread(target=_warm_up_resolver, name="resolver-warmup", daemon=True).start()
        yield
        jobs.shutdown()

    app = FastAPI(title="CutMind API", version=__version__, lifespan=lifespan,
                  description="Prompt-driven multi-agent video editor (local, free, open source).")
    app.state.db, app.state.jobs, app.state.settings = db, jobs, settings
    limiter = RateLimiter(int(os.environ.get("RATE_LIMIT_PER_MIN", "30")))
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def _require_api_key(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Optional shared-secret auth. `?api_key=` is accepted too because <video>/<img> can't send headers."""
        if settings.api_key and request.method != "OPTIONS" and request.url.path not in PUBLIC_PATHS:
            given = request.headers.get("x-api-key") or request.query_params.get("api_key")
            if not given or not hmac.compare_digest(given, settings.api_key):
                return JSONResponse({"error": {"code": "unauthorized", "message": "Missing or wrong API key."}},
                                    status_code=401)
        return await call_next(request)

    # ---- uniform error shape ------------------------------------------------------------------------
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"error": {"code": exc.code, "message": exc.message, **exc.extra}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        return JSONResponse({"error": {"code": "validation_error",
                                       "message": f"{loc}: {first.get('msg', 'invalid input')}".strip(": ")}},
                            status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse({"error": {"code": code, "message": str(exc.detail)}}, status_code=exc.status_code)

    # ---- helpers ---------------------------------------------------------------------------------------
    def project_or_404(pid: str) -> dict[str, Any]:
        p = db.get_project(pid)
        if not p:
            raise ApiError(404, "project_not_found", f"Project {pid} does not exist.")
        return p

    def project_out(p: dict[str, Any]) -> dict[str, Any]:
        last = db.last_job(p["id"])
        done = db.last_job(p["id"], "done")
        return {"id": p["id"], "name": p["name"], "created_at": p["created_at"],
                "clips": [_clip_out(c) for c in db.list_clips(p["id"])],
                "last_job_id": last["id"] if last else None,
                "output_job_id": done["id"] if done else None,  # the version the player shows (last FINISHED job)
                "has_output": bool(done and done["output_path"] and Path(done["output_path"]).exists())}

    # ---- routes --------------------------------------------------------------------------------------------
    @app.get("/health", tags=["system"])
    def health() -> dict[str, Any]:
        whisper = True
        try:
            import_faster_whisper()
        except Exception:  # noqa: BLE001
            whisper = False
        llm = local_llm_status(settings) if settings.planner_mode == "local" else {"model": None, "available": None}
        return {"status": "ok", "version": __version__, "planner_mode": settings.planner_mode,
                "ffmpeg": ffmpeg_available(), "llm": llm, "whisper": whisper and settings.enable_transcription,
                "auth_required": bool(settings.api_key)}

    @app.post("/projects/{pid}/manual", tags=["edit"], status_code=202)
    def manual_edit(pid: str, body: ManualEdit) -> dict[str, Any]:
        """Apply hand-made changes (text, fonts, animations, effects, looks, transitions, timeline) directly —
        no AI step. Unchanged cuts are reused from the cache, so text-only changes render in seconds."""
        project_or_404(pid)
        try:
            job_id = jobs.submit_manual(pid, body.ops)
        except ManualError as exc:
            raise ApiError(422, "bad_manual_edit", str(exc)) from exc
        return {"job_id": job_id, "status": "queued"}

    @app.get("/prompts", tags=["edit"])
    def prompt_library() -> dict[str, Any]:
        """Ready-made professional briefs, plus the content types and platforms the editor knows."""
        kn = knowledge()
        lib = yaml.safe_load((KNOWLEDGE_DIR / "prompt_library.yaml").read_text(encoding="utf-8"))["prompts"]
        return {"prompts": lib,
                "genres": [{"id": g["id"], "name": g["name"], "structure": g["structure"]} for g in kn["genres"].values()],
                "platforms": [{"id": p["id"], "name": p["name"], "aspect": p["aspect"]} for p in kn["platforms"].values()],
                "skills": len(kn["skills"])}

    @app.get("/text-styles", tags=["edit"])
    def text_styles() -> dict[str, Any]:
        """Fonts, text presets, colour words and text animations for the manual text editor."""
        return {**text_catalog(), "animations": [{"id": k, "description": v[0]} for k, v in TEXT_ANIMATIONS.items()]}

    @app.post("/understand", tags=["edit"])
    def understand_prompt(body: UnderstandIn) -> dict[str, Any]:
        """Prompt coach: rough Hinglish → a clean English prompt + the list of what was understood. Instant."""
        try:
            analysis = jobs.cached_analysis(body.project_id) if body.project_id else None
            # words the user taught become commands; parts nobody understood are asked about, not guessed
            pb = PhraseBook(db)
            expanded, unclear_parts = pb.expand(validate_prompt(body.prompt))
            has_edit = bool(body.project_id and jobs.memory.history(body.project_id, 1))
            return {**understand(expanded, analysis, has_edit), "unclear": unclear_parts,
                    "translated": [{"text": k, "english": v} for k, v in pb.translated.items()]}
        except PromptError as exc:
            raise ApiError(422, "bad_prompt", str(exc)) from exc

    @app.post("/transcribe", tags=["edit"])
    def transcribe_voice(audio: UploadFile = File(...)) -> dict[str, Any]:
        """Voice prompt: record what you want ("isko mast sa edit kar do") → English text for /edit.
        Runs the same local faster-whisper model as captions; nothing leaves the server."""
        if not settings.enable_transcription:
            raise ApiError(503, "transcription_disabled", "Speech recognition is turned off on this server.")
        data = audio.file.read(VOICE_MAX_BYTES + 1)
        if not data:
            raise ApiError(400, "empty_file", "The recording is empty.")
        if len(data) > VOICE_MAX_BYTES:
            raise ApiError(413, "file_too_large", f"Voice prompts can be at most {VOICE_MAX_BYTES // CHUNK} MB (~1 minute).")
        tmp = settings.data_dir / "tmp" / new_id("voice")
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            src = tmp / "in.bin"
            src.write_bytes(data)
            try:
                wav = extract_audio_wav(src, tmp / "voice.wav", sr=16000)
            except FFmpegError as exc:
                raise ApiError(400, "bad_audio", "Could not read the recording as audio.") from exc
            try:
                text, lang = voice_to_prompt(wav, settings.whisper_model)
            except ImportError as exc:
                raise ApiError(503, "whisper_unavailable", "Speech recognition (faster-whisper) is not installed.") from exc
            return {"text": text, "language": lang}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @app.post("/projects", tags=["projects"], status_code=201)
    def create_project(body: ProjectIn) -> dict[str, Any]:
        name = body.name.strip()
        if not name:
            raise ApiError(422, "validation_error", "name: project name cannot be blank")
        return project_out(db.create_project(name))

    @app.get("/projects", tags=["projects"])
    def list_projects() -> list[dict[str, Any]]:
        return [project_out(p) for p in db.list_projects()]

    @app.get("/projects/{pid}", tags=["projects"])
    def get_project(pid: str) -> dict[str, Any]:
        return project_out(project_or_404(pid))

    @app.delete("/projects/{pid}", tags=["projects"])
    def delete_project(pid: str) -> dict[str, Any]:
        project_or_404(pid)
        db.delete_project(pid)
        shutil.rmtree(jobs.project_dir(pid), ignore_errors=True)
        return {"ok": True}

    @app.post("/projects/{pid}/clips", tags=["clips"], status_code=201)
    async def upload_clips(pid: str, request: Request, files: list[UploadFile] = File(...)) -> dict[str, Any]:
        project_or_404(pid)
        max_bytes = settings.max_upload_mb * 1024 * 1024
        declared = int(request.headers.get("content-length") or 0)
        if declared and declared > max_bytes * max(1, len(files)) + CHUNK:
            raise ApiError(413, "file_too_large", f"Upload is larger than the {settings.max_upload_mb} MB limit.")
        existing = len(db.list_clips(pid))
        if existing + len(files) > settings.max_clips:
            raise ApiError(400, "too_many_clips", f"A project can have at most {settings.max_clips} clips.")
        clip_dir = jobs.project_dir(pid) / "clips"
        clip_dir.mkdir(parents=True, exist_ok=True)
        saved: list[dict[str, Any]] = []
        for f in files:
            name = Path(f.filename or "clip").name
            ext = Path(name).suffix.lower()
            if ext not in settings.allowed_extensions:
                raise ApiError(415, "unsupported_file_type",
                               f"'{name}' is not a supported video type. Allowed: {', '.join(settings.allowed_extensions)}")
            dest = clip_dir / f"{new_id('src')}{ext}"
            size = 0
            with dest.open("wb") as out:
                while chunk := await f.read(CHUNK):
                    size += len(chunk)
                    if size > max_bytes:
                        out.close()
                        dest.unlink(missing_ok=True)
                        raise ApiError(413, "file_too_large",
                                       f"'{name}' is larger than the {settings.max_upload_mb} MB limit.")
                    out.write(chunk)
            if size == 0:
                dest.unlink(missing_ok=True)
                raise ApiError(400, "empty_file", f"'{name}' is empty.")
            try:
                info = probe(dest)
                if not info.has_video or info.duration <= 0.2 or info.width == 0:
                    raise FFmpegError("no playable video stream")
            except FFmpegError as exc:
                dest.unlink(missing_ok=True)
                raise ApiError(400, "corrupt_file", f"'{name}' could not be read as a video ({str(exc)[:120]}).") from exc
            meta = {"duration": round(info.duration, 3), "width": info.width, "height": info.height,
                    "fps": info.fps, "has_audio": info.has_audio, "size_bytes": size}
            clip = db.add_clip(pid, name, str(dest), meta)
            try:
                save_frame_jpg(dest, min(1.0, info.duration / 2), clip_dir / f"{clip['id']}.jpg")
            except FFmpegError:
                pass  # thumbnail is cosmetic
            saved.append(_clip_out(clip))
            jobs.prepare(pid, clip["id"])  # proxy + analysis in the background
        return {"clips": saved}

    @app.delete("/projects/{pid}/clips/{clip_id}", tags=["clips"])
    def delete_clip(pid: str, clip_id: str) -> dict[str, Any]:
        project_or_404(pid)
        clip = db.get_clip(clip_id)
        if not clip or clip["project_id"] != pid:
            raise ApiError(404, "clip_not_found", f"Clip {clip_id} not found in this project.")
        db.delete_clip(clip_id)
        Path(clip["path"]).unlink(missing_ok=True)
        proxy_path(Path(clip["path"])).unlink(missing_ok=True)
        (jobs.project_dir(pid) / "clips" / f"{clip_id}.jpg").unlink(missing_ok=True)
        return {"ok": True}

    @app.get("/projects/{pid}/clips/{clip_id}/thumbnail", tags=["clips"], response_class=FileResponse)
    def clip_thumbnail(pid: str, clip_id: str) -> FileResponse:
        project_or_404(pid)
        thumb = jobs.project_dir(pid) / "clips" / f"{clip_id}.jpg"
        if not thumb.exists():
            raise ApiError(404, "thumbnail_not_found", "No thumbnail for this clip.")
        return FileResponse(thumb, media_type="image/jpeg")

    # ---- songs: upload your own music, pick the song for the next edit ------------------------------------
    def _song_out(pathname: Path, source: str, selected: str | None) -> dict[str, Any]:
        out: dict[str, Any] = {"name": pathname.name, "source": source, "selected": pathname.name == selected}
        try:
            out["duration"] = round(probe(pathname).duration, 2)
            prof = analyze_song(pathname, settings.data_dir / "cache" / "songwork", settings.data_dir / "cache",
                                only_cached=True)
            if prof is None:  # not measured yet: done in the background, the next listing shows it
                out["analyzing"] = True
                threading.Thread(target=_analyze_quietly, args=(pathname,), daemon=True).start()
            else:
                out.update(tempo=prof.tempo, feel=prof.feel, drop=prof.drop)
        except Exception:  # noqa: BLE001 — a listing never fails because of one odd file
            pass
        return out

    def _analyze_quietly(song: Path) -> None:
        try:
            analyze_song(song, settings.data_dir / "cache" / "songwork", settings.data_dir / "cache")
        except Exception:  # noqa: BLE001
            pass

    def _prepare_lyrics(song: Path) -> None:
        try:
            song_words(song, settings.data_dir / "cache" / "songwork", settings.data_dir / "cache")
        except Exception:  # noqa: BLE001 — lyrics are a bonus; the edit works without them
            pass

    @app.get("/projects/{pid}/music", tags=["music"])
    def list_songs(pid: str) -> dict[str, Any]:
        project_or_404(pid)
        sel = selected_song(settings, pid)
        return {"selected": sel,
                "project": [_song_out(x, "project", sel) for x in project_songs(settings, pid)],
                "library": [_song_out(x, "library", sel) for x in list_music(settings.music_dir)]}

    @app.post("/projects/{pid}/music", tags=["music"], status_code=201)
    async def upload_song(pid: str, file: UploadFile = File(...)) -> dict[str, Any]:
        project_or_404(pid)
        name = Path(file.filename or "song").name
        max_bytes = settings.max_upload_mb * 1024 * 1024
        tmp = jobs.project_dir(pid) / "music" / f"upload_{new_id('up')}{Path(name).suffix.lower()}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        try:
            with tmp.open("wb") as out:
                while chunk := await file.read(CHUNK):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ApiError(413, "file_too_large", f"'{name}' is larger than the {settings.max_upload_mb} MB limit.")
                    out.write(chunk)
            if size == 0:
                raise ApiError(400, "empty_file", f"'{name}' is empty.")
            try:
                song = import_song(settings, pid, tmp, name)
            except SongError as exc:
                raise ApiError(400, "bad_song", str(exc)) from exc
        finally:
            tmp.unlink(missing_ok=True)
        set_selected(settings, pid, song.name)  # a song you just uploaded is the one you want
        _analyze_quietly(song)
        threading.Thread(target=_prepare_lyrics, args=(song,), daemon=True).start()  # ready before the edit
        return _song_out(song, "project", song.name)

    @app.put("/projects/{pid}/music/selected", tags=["music"])
    def select_song(pid: str, body: SongSelectIn) -> dict[str, Any]:
        project_or_404(pid)
        try:
            set_selected(settings, pid, body.name)
        except SongError as exc:
            raise ApiError(404, "song_not_found", str(exc)) from exc
        return {"selected": body.name}

    @app.get("/projects/{pid}/music/{name}/file", tags=["music"], response_class=FileResponse)
    def song_file(pid: str, name: str) -> FileResponse:
        project_or_404(pid)
        p = resolve(Path(name).name, music_dirs(settings, pid))
        if p is None:
            raise ApiError(404, "song_not_found", f"No song called '{name}'.")
        return FileResponse(p, media_type="audio/mp4" if p.suffix == ".m4a" else "audio/mpeg")

    @app.delete("/projects/{pid}/music/{name}", tags=["music"])
    def delete_song(pid: str, name: str) -> dict[str, Any]:
        project_or_404(pid)
        d = project_music_dir(settings, pid)
        p = resolve(Path(name).name, [d]) if d else None
        if p is None:
            raise ApiError(404, "song_not_found", f"No uploaded song called '{name}' (library songs can't be deleted).")
        p.unlink()
        if selected_song(settings, pid) is None:
            set_selected(settings, pid, None)
        return {"ok": True}

    # ---- reference edit: "edit my footage like this video" --------------------------------------------------
    @app.post("/projects/{pid}/reference", tags=["reference"], status_code=201)
    async def upload_reference(pid: str, file: UploadFile = File(...)) -> dict[str, Any]:
        project_or_404(pid)
        name = Path(file.filename or "reference.mp4").name
        ext = Path(name).suffix.lower()
        if ext not in settings.allowed_extensions:
            raise ApiError(415, "unsupported_file_type", f"'{name}' is not a supported video type.")
        d = jobs.project_dir(pid) / "reference"
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("ref.*"):
            old.unlink(missing_ok=True)
        dest = d / f"ref{ext}"
        size, max_bytes = 0, settings.max_upload_mb * 1024 * 1024
        with dest.open("wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise ApiError(413, "file_too_large", f"'{name}' is larger than the {settings.max_upload_mb} MB limit.")
                out.write(chunk)
        try:
            info = probe(dest)
            if not info.has_video or info.duration < 1.0:
                raise FFmpegError("no playable video stream")
        except FFmpegError as exc:
            dest.unlink(missing_ok=True)
            raise ApiError(400, "corrupt_file", f"'{name}' could not be read as a video.") from exc
        recipe = analyze_reference(dest, d / "work")
        recipe.name = name
        if info.has_audio:
            try:  # its soundtrack becomes a project song, so the new edit can use the same music
                song = import_song(settings, pid, dest, f"{Path(name).stem}_sound.m4a")
                recipe.song = song.name
                _analyze_quietly(song)
            except SongError:
                pass
        save_recipe(recipe, d / "recipe.json")
        return {"name": name, "summary": recipe.summary(), "recipe": asdict(recipe)}

    @app.get("/projects/{pid}/reference", tags=["reference"])
    def get_reference(pid: str) -> dict[str, Any]:
        project_or_404(pid)
        r = load_recipe(jobs.project_dir(pid) / "reference" / "recipe.json")
        if r is None:
            raise ApiError(404, "no_reference", "No reference video uploaded for this project.")
        return {"name": r.name, "summary": r.summary(), "recipe": asdict(r)}

    @app.delete("/projects/{pid}/reference", tags=["reference"])
    def delete_reference(pid: str) -> dict[str, Any]:
        project_or_404(pid)
        shutil.rmtree(jobs.project_dir(pid) / "reference", ignore_errors=True)
        return {"ok": True}

    @app.post("/reference-style", tags=["reference"])
    async def reference_style(file: UploadFile = File(...)) -> dict[str, Any]:
        """A reference video → its STYLE PROFILE (numbers only, recipe-shaped). Not stored, not tied to a project."""
        from .recipes import schema as recipe_schema
        from .reference import style_profile

        name = Path(file.filename or "reference.mp4").name
        if Path(name).suffix.lower() not in settings.allowed_extensions:
            raise ApiError(415, "unsupported_file_type", f"'{name}' is not a supported video type.")
        work = Path(tempfile.mkdtemp(prefix="refstyle_", dir=settings.data_dir))
        try:
            dest, size = work / f"ref{Path(name).suffix.lower()}", 0
            with dest.open("wb") as out:
                while chunk := await file.read(CHUNK):
                    size += len(chunk)
                    if size > settings.max_upload_mb * 1024 * 1024:
                        raise ApiError(413, "file_too_large", f"'{name}' is larger than the {settings.max_upload_mb} MB limit.")
                    out.write(chunk)
            try:
                if not probe(dest).has_video:
                    raise FFmpegError("no video")
            except FFmpegError as exc:
                raise ApiError(400, "corrupt_file", f"'{name}' could not be read as a video.") from exc
            r = analyze_reference(dest, work / "work")
            r.name = name
            prof = style_profile(r)
            import jsonschema

            jsonschema.validate({k: v for k, v in prof.items() if k != "measured"}, recipe_schema())
            return {"name": name, "summary": r.summary(), "profile": prof}
        finally:
            shutil.rmtree(work, ignore_errors=True)

    @app.get("/taste", tags=["learning"])
    def get_taste() -> dict[str, Any]:
        """What CutMind learned about this user's taste (local only): preference counts + the learned knobs."""
        return {"preferences": jobs.memory.preferences(), "knobs": Learner(db).summary()}

    @app.delete("/taste", tags=["learning"])
    def reset_taste() -> dict[str, Any]:
        """"Reset my taste": forget the learned knobs and the preference counts (edits and versions stay)."""
        db.execute("DELETE FROM learn_arms") if db.all("SELECT name FROM sqlite_master WHERE name='learn_arms'") else None
        jobs.memory.reset_taste()
        return {"ok": True, "preferences": jobs.memory.preferences()}

    @app.get("/projects/{pid}/explain", tags=["edit"])
    def explain_current(pid: str) -> dict[str, Any]:
        """What the CURRENT version changed compared with the one before it (understood / changed / kept / length /
        warnings / next suggestions)."""
        from .versions import explain as explain_plans

        project_or_404(pid)
        rows = db.all("SELECT id, prompt, plan FROM jobs WHERE project_id=? AND status='done' AND plan IS NOT NULL "
                      "ORDER BY created_at DESC, rowid DESC LIMIT 2", (pid,))
        if not rows:
            raise ApiError(404, "no_plan", "No finished edit yet for this project.")
        after = EditPlan.model_validate(json.loads(rows[0]["plan"]))
        before = EditPlan.model_validate(json.loads(rows[1]["plan"])) if len(rows) > 1 else None
        it = parse_intent(rows[0]["prompt"] or "")
        out = explain_plans(before, after, it.model_dump(exclude_defaults=True), rows[0]["prompt"] or "")
        return {"job_id": rows[0]["id"], "prompt": rows[0]["prompt"], "understood": it.recognized, **out}

    # ---- Tier 1 tools (skills/tier1): deterministic skill calls, versioned like every edit ------------------------
    @app.get("/tools", tags=["tools"])
    def list_tools() -> dict[str, Any]:
        """The Tier 1 skills: id, name, category, parameters, time modes, Media3 status and the render-test result."""
        from .tools import spec

        res_path = spec.ROOT / "skills" / "tier1_results.json"
        results = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else {}
        return {"tools": [{"id": s["id"], "name": s["name"], "name_hi": s.get("name_hi"), "category": s["category"],
                           "params": s["params"], "time_modes": s["time_modes"], "media3": s["media3"]["status"],
                           "tested": bool(results.get(s["id"], {}).get("ok")), "example": s["examples"][0]["prompt"]}
                          for s in spec.load().values()]}

    @app.post("/tools/parse", tags=["tools"])
    def parse_tools(body: dict[str, Any]) -> dict[str, Any]:
        """A prompt → the tool calls it means (no edit made): skills, parameters, time, assumptions, negations,
        unclear parts with the 3 nearest skills, and asks that are not available yet."""
        from .skill_registry import named_later
        from .tools.parse import parse

        prompt = str(body.get("prompt") or "")[:2000]
        if not prompt.strip():
            raise ApiError(422, "empty_prompt", "Say what to change.")
        r = parse(prompt)
        r["not_available_yet"] = named_later(prompt)
        return r

    @app.post("/tools/resolve", tags=["tools"])
    def resolve_tools(body: dict[str, Any]) -> dict[str, Any]:
        """A prompt + where the user is → ranked readings (no edit made). Body: {prompt, project_id?, context?:
        {marker_time, playhead, effects_present_at_time, ...}}. With a project and a marker, what is on screen
        there is read from the latest version."""
        from .tools.resolve import context_from_plan, resolve
        from .unmet import UnmetLog

        prompt = str(body.get("prompt") or "")[:2000]
        if not prompt.strip():
            raise ApiError(422, "empty_prompt", "Say what to change.")
        ctx = dict(body.get("context") or {})
        pid = body.get("project_id")
        t = ctx.get("marker_time", ctx.get("playhead"))
        if pid and t is not None and "effects_present_at_time" not in ctx:
            job = db.last_job(str(pid), "done")
            if job and job["plan"]:
                ctx = {**context_from_plan(EditPlan.model_validate(json.loads(job["plan"])), float(t)), **ctx}
        ctx["learned"] = UnmetLog(db).learned(prompt)
        return resolve(prompt, ctx).to_dict()

    @app.post("/tools/resolve/pick", tags=["tools"])
    def resolve_pick(body: dict[str, Any]) -> dict[str, Any]:
        """The choice the user tapped for a request that was not clear (local memory; never the shared synonyms)."""
        from .unmet import UnmetLog

        ok = UnmetLog(db).pick(str(body.get("request_id") or ""), str(body.get("choice_id") or ""))
        if not ok:
            raise ApiError(404, "not_found", "unknown request id")
        return {"ok": True}

    @app.post("/projects/{pid}/tools", tags=["tools"], status_code=202)
    def apply_tools(pid: str, body: dict[str, Any]) -> dict[str, Any]:
        """Run Tier 1 skills on the latest version: {"calls": [{"id", "params", "time"}]} or {"prompt": "..."}.
        A new version is made; the old one is untouched (undo / restore as for every edit)."""
        from .skill_registry import named_later
        from .tools.parse import parse

        if db.get_project(pid) is None:
            raise ApiError(404, "not_found", f"project {pid} not found")
        calls = body.get("calls")
        prompt = str(body.get("prompt") or "")
        if not calls:
            if not prompt.strip():
                raise ApiError(422, "bad_tools", "Send {\"calls\": [...]} or {\"prompt\": \"...\"}.")
            r = parse(prompt)
            calls = r["calls"]
            if not calls:
                later = named_later(prompt)
                near = [n for u in r["unknown"] for n in u["nearest"]][:3]
                msg = (f"'{later[0]}' is not available yet. " if later else "I could not match that to a skill. ")
                raise ApiError(422, "not_understood", msg + "Closest: " + ", ".join(f"{n['name']} (e.g. '{n['try']}')" for n in near))
        if not isinstance(calls, list) or not 1 <= len(calls) <= 20:
            raise ApiError(422, "bad_tools", "Send 1-20 tool calls.")
        try:
            job_id = jobs.submit_tools(pid, calls, prompt)
        except ManualError as exc:
            raise ApiError(422, "bad_tools", str(exc)) from exc
        return {"job_id": job_id, "status": "queued", "calls": calls}

    @app.post("/enhance", tags=["skills"])
    def enhance_prompt(body: dict[str, Any]) -> dict[str, Any]:
        """Desi → Pro: the casual prompt as a professional brief (with the assumed defaults listed), the skills it
        names, and 3 suggestions when nothing was understood. No model needed; nothing is rendered."""
        from .prompt_enhancer import enhance

        text = str(body.get("prompt") or "").strip()
        if not text:
            raise ApiError(422, "bad_prompt", "Kuch likho — jaise 'ek filmy reel bana de'.")
        return enhance(text[:2000])

    @app.get("/skills", tags=["skills"])
    def list_skills(q: str | None = Query(None, max_length=300)) -> dict[str, Any]:
        """The skill registry (220+ entries with tier and status). With `q`: which skills a message would use."""
        from . import skill_registry as R

        out: dict[str, Any] = {"skills": [{k: s[k] for k in ("id", "tier", "category", "name", "description", "status",
                                                               "time_modes", "params", "cost")} for s in R.load().values()]}
        if q:
            out["understood"] = R.understand(q)
        return out

    @app.post("/projects/{pid}/skills", tags=["skills"], status_code=202)
    def apply_skills(pid: str, body: dict[str, Any]) -> dict[str, Any]:
        """Apply structured skill calls to the CURRENT edit: [{"id", "params", "time": {"mode", …}}]. Refused calls
        (unknown / planned / wrong time mode / out-of-range parameter) answer 422 with the reason."""
        from .skill_apply import SkillError
        from .skill_apply import apply as check

        project_or_404(pid)
        calls = body.get("calls") or []
        if not isinstance(calls, list) or not calls or len(calls) > 20:
            raise ApiError(422, "bad_skills", "Send 1-20 skill calls as {\"calls\": [...]}.")
        job = db.last_job(pid, "done")
        total = EditPlan.model_validate(json.loads(job["plan"])).total_duration() if job and job["plan"] else 600.0
        try:
            _it, notes = check(calls, total)
        except SkillError as exc:
            raise ApiError(422, "bad_skill", str(exc)) from exc
        job_id = jobs.submit(pid, "skills: " + ", ".join(notes)[:300], {"skill_calls": calls, "skill_total": total})
        return {"job_id": job_id, "status": "queued", "skills": notes}

    @app.get("/llm/health", tags=["system"])
    def llm_health() -> dict[str, Any]:
        """The planner LLM: provider, model, loaded?, queue, p50/p95 latency, failures; and the router's last trace."""
        from . import llm_router
        from .llm_provider import get_provider

        return {"provider": get_provider().health(), "last_trace": llm_router.last_trace,
                "timeout_s": llm_router.TIMEOUT, "max_tokens": llm_router.MAX_TOKENS}

    # ---- Copy an Edit: watch a liked video shot by shot, rebuild the same edit from the raw footage ---------------
    def _copy_dir(pid: str) -> Path:
        return jobs.project_dir(pid) / "copy_edit"

    def _copy_status(pid: str) -> dict[str, Any] | None:
        f = _copy_dir(pid) / "status.json"
        try:
            return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
        except ValueError:
            return None

    def _set_copy_status(pid: str, **st: Any) -> None:
        d = _copy_dir(pid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "status.json").write_text(json.dumps(st), encoding="utf-8")

    def _blueprint_out(pid: str, bp: Any) -> dict[str, Any]:
        return {**bp.to_dict(), "summary": bp.summary(),
                "thumbs": [f"/projects/{pid}/copy-edit/thumb/{i}" for i in range(len(bp.shots))]}

    def _watch_liked(pid: str, video: Path, name: str) -> None:
        """Background: the agent watches the liked video (shots, effects, text, soundtrack)."""
        from .blueprint import analyze_blueprint, save_blueprint, save_thumbs

        d = _copy_dir(pid)
        try:
            _set_copy_status(pid, status="analyzing", progress=0.05, step="Finding every cut…")

            def prog(p: float) -> None:
                _set_copy_status(pid, status="analyzing", progress=round(0.25 + 0.65 * p, 3),
                                 step="Reading the text on screen…")
            bp = analyze_blueprint(video, d / "work", prog)
            bp.name = name
            _set_copy_status(pid, status="analyzing", progress=0.92, step="Saving its soundtrack and shot pictures…")
            if probe(video).has_audio:
                try:
                    song = import_song(settings, pid, video, f"{Path(name).stem}_copy.m4a")
                    bp.song = song.name
                    _analyze_quietly(song)
                except SongError:
                    pass
            save_thumbs(video, bp, d / "thumbs")
            save_blueprint(bp, d / "blueprint.json")
            _set_copy_status(pid, status="ready", progress=1.0, step="Done")
        except Exception as exc:  # noqa: BLE001
            _set_copy_status(pid, status="failed", progress=0.0, error=str(exc)[:300])
        finally:
            shutil.rmtree(d / "work", ignore_errors=True)

    @app.post("/projects/{pid}/copy-edit", tags=["copy-edit"], status_code=202)
    async def upload_liked(pid: str, file: UploadFile = File(...)) -> dict[str, Any]:
        project_or_404(pid)
        if (_copy_status(pid) or {}).get("status") == "analyzing":
            raise ApiError(409, "busy", "The agent is still watching the previous video.")
        name = Path(file.filename or "liked.mp4").name
        ext = Path(name).suffix.lower()
        if ext not in settings.allowed_extensions:
            raise ApiError(415, "unsupported_file_type", f"'{name}' is not a supported video type.")
        d = _copy_dir(pid)
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"liked{ext}"
        size, max_bytes = 0, settings.max_upload_mb * 1024 * 1024
        with dest.open("wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    out.close()
                    shutil.rmtree(d, ignore_errors=True)
                    raise ApiError(413, "file_too_large", f"'{name}' is larger than the {settings.max_upload_mb} MB limit.")
                out.write(chunk)
        try:
            info = probe(dest)
            if not info.has_video or info.duration < 1.0:
                raise FFmpegError("no playable video stream")
        except FFmpegError as exc:
            shutil.rmtree(d, ignore_errors=True)
            raise ApiError(400, "corrupt_file", f"'{name}' could not be read as a video.") from exc
        if info.duration > 180:
            shutil.rmtree(d, ignore_errors=True)
            raise ApiError(400, "too_long", "Copy an Edit works with videos up to 3 minutes (reels, shorts, edits).")
        _set_copy_status(pid, status="analyzing", progress=0.0, step="Starting…", name=name)
        threading.Thread(target=_watch_liked, args=(pid, dest, name), daemon=True).start()
        return {"status": "analyzing", "progress": 0.0}

    @app.get("/projects/{pid}/copy-edit", tags=["copy-edit"])
    def get_liked(pid: str) -> dict[str, Any]:
        from .blueprint import load_blueprint

        project_or_404(pid)
        st = _copy_status(pid)
        if st and st.get("status") in ("analyzing", "failed"):
            return st
        bp = load_blueprint(_copy_dir(pid) / "blueprint.json")
        if bp is None:
            raise ApiError(404, "no_blueprint", "No liked video analysed for this project yet.")
        return {"status": "ready", "blueprint": _blueprint_out(pid, bp)}

    @app.get("/projects/{pid}/copy-edit/thumb/{i}", tags=["copy-edit"], response_class=FileResponse)
    def liked_thumb(pid: str, i: int) -> FileResponse:
        project_or_404(pid)
        f = _copy_dir(pid) / "thumbs" / f"{i}.jpg"
        if not f.exists():
            raise ApiError(404, "thumbnail_not_found", "No picture for this shot.")
        return FileResponse(f, media_type="image/jpeg")

    @app.delete("/projects/{pid}/copy-edit", tags=["copy-edit"])
    def delete_liked(pid: str) -> dict[str, Any]:
        project_or_404(pid)
        shutil.rmtree(_copy_dir(pid), ignore_errors=True)
        return {"deleted": True}

    @app.post("/projects/{pid}/copy-edit/run", tags=["copy-edit"], status_code=202)
    def run_copy(pid: str, body: CopyRunIn) -> dict[str, Any]:
        from .blueprint import load_blueprint

        project_or_404(pid)
        if load_blueprint(_copy_dir(pid) / "blueprint.json") is None:
            raise ApiError(400, "no_blueprint", "Pehle wo video upload karo jaisa edit chahiye.")
        if not db.list_clips(pid):
            raise ApiError(400, "no_clips", "This project has no clips. Upload at least one video clip first.")
        extra = (body.prompt or "").strip()
        try:
            prompt = (PhraseBook(db).expand(validate_prompt(extra), ask=False)[0] if extra
                      else "Copy the liked video")
        except PromptError as exc:
            raise ApiError(422, "bad_prompt", str(exc)) from exc
        job_id = jobs.submit(pid, prompt, {"copy_edit": True, "keep_sound": body.keep_sound})
        return {"job_id": job_id, "status": "queued"}

    @app.post("/projects/{pid}/copy-edit/template", tags=["templates"], status_code=201)
    def save_liked_template(pid: str, body: TemplateIn) -> dict[str, Any]:
        project_or_404(pid)
        try:
            return tpl.save_mine(settings.data_dir, body.name, _copy_dir(pid), jobs.project_dir(pid) / "music")
        except tpl.TemplateError as exc:
            raise ApiError(400, "no_blueprint", str(exc)) from exc

    # ---- Templates -------------------------------------------------------------------------------------------
    @app.get("/templates", tags=["templates"])
    def list_templates() -> dict[str, Any]:
        return tpl.all_templates(settings.data_dir)

    @app.get("/templates/{tid}/preview", tags=["templates"], response_class=FileResponse)
    def template_preview(tid: str) -> FileResponse:
        f = tpl.preview(settings.data_dir, tid, settings.data_dir / "cache" / "template_cards")
        if f is None:
            raise ApiError(404, "template_not_found", f"Template {tid} does not exist.")
        return FileResponse(f, media_type="image/jpeg")

    @app.delete("/templates/{tid}", tags=["templates"])
    def delete_template(tid: str) -> dict[str, Any]:
        if not tpl.delete_mine(settings.data_dir, tid):
            raise ApiError(404, "template_not_found", "Only your own templates can be deleted.")
        return {"deleted": True}

    @app.post("/projects/{pid}/templates/{tid}/apply", tags=["templates"], status_code=202)
    def apply_template(pid: str, tid: str, body: ApplyIn) -> dict[str, Any]:
        project_or_404(pid)
        t = tpl.get(settings.data_dir, tid)
        if t is None:
            raise ApiError(404, "template_not_found", f"Template {tid} does not exist.")
        if not db.list_clips(pid):
            raise ApiError(400, "no_clips", "This project has no clips. Upload at least one video clip first.")
        extra = (body.prompt or "").strip()
        try:
            extra = PhraseBook(db).expand(validate_prompt(extra), ask=False)[0] if extra else ""
        except PromptError as exc:
            raise ApiError(422, "bad_prompt", str(exc)) from exc
        if t["kind"] == "mine":
            try:
                tpl.install_mine(settings.data_dir, tid, _copy_dir(pid), jobs.project_dir(pid) / "music")
            except tpl.TemplateError as exc:
                raise ApiError(400, "broken_template", str(exc)) from exc
            job_id = jobs.submit(pid, extra or "Copy the liked video",
                                 {"copy_edit": True, "template": tid})
        else:
            prompt = t["prompt"] + (". " + extra if extra else "")  # what the user adds in words wins
            job_id = jobs.submit(pid, prompt, {"template": tid})
        return {"job_id": job_id, "status": "queued", "template": t["name"]}

    # ---- versions: history, restore, undo / redo, compare (no re-render: outputs are kept per version) ---------
    @app.get("/projects/{pid}/versions", tags=["versions"])
    def list_versions(pid: str) -> dict[str, Any]:
        from .versions import versions

        project_or_404(pid)
        return {"versions": versions(db, pid)}

    def _version_op(pid: str, fn: Any, *args: Any) -> dict[str, Any]:
        project_or_404(pid)
        if any(j["status"] in ("queued", "running") for j in db.all("SELECT status FROM jobs WHERE project_id=?", (pid,))):
            raise ApiError(409, "busy", "Pehle chal raha edit khatam hone do.")
        try:
            return fn(db, jobs.project_dir(pid), pid, *args, jobs.memory)
        except ValueError as exc:
            raise ApiError(400, "no_version", str(exc)) from exc

    @app.post("/projects/{pid}/versions/{job_id}/restore", tags=["versions"])
    def restore_version(pid: str, job_id: str) -> dict[str, Any]:
        from .versions import restore

        return _version_op(pid, restore, job_id)

    @app.post("/projects/{pid}/undo", tags=["versions"])
    def undo_edit(pid: str) -> dict[str, Any]:
        from .versions import undo

        return _version_op(pid, undo)

    @app.post("/projects/{pid}/redo", tags=["versions"])
    def redo_edit(pid: str) -> dict[str, Any]:
        from .versions import redo

        return _version_op(pid, redo)

    @app.get("/projects/{pid}/versions/compare", tags=["versions"])
    def compare_versions(pid: str, a: str = Query(...), b: str = Query(...)) -> dict[str, Any]:
        from .versions import diff

        project_or_404(pid)
        plans = []
        for jid in (a, b):
            row = db.one("SELECT plan FROM jobs WHERE id=? AND project_id=?", (jid, pid))
            if not row or not row.get("plan"):
                raise ApiError(404, "no_version", f"Version {jid} not found.")
            plans.append(EditPlan.model_validate(json.loads(row["plan"])))
        return diff(plans[0], plans[1])

    @app.post("/projects/{pid}/edit", tags=["edit"], status_code=202)
    def start_edit(pid: str, body: EditIn, request: Request) -> dict[str, Any]:
        project_or_404(pid)
        who = request.headers.get("x-api-key") or request.headers.get("x-user") or (request.client.host if request.client else "?")
        if not limiter.allow(who):
            raise ApiError(429, "rate_limited", f"Bahut saare edits ek saath — ek minute mein {limiter.per_min} se zyada "
                                                "nahi. Thoda ruk kar dobara bhejo.")
        try:
            prompt = PhraseBook(db).expand(validate_prompt(body.prompt), ask=False)[0]  # + the user's taught phrases
        except PromptError as exc:
            raise ApiError(422, "bad_prompt", str(exc)) from exc
        if not db.list_clips(pid):
            raise ApiError(400, "no_clips", "This project has no clips. Upload at least one video clip first.")
        options = {k: v for k, v in {"aspect_ratio": body.aspect_ratio, "resolution": body.resolution,
                                     "variations": body.variations, "style": body.style,
                                     "music_track": body.music_track}.items() if v}
        if body.at is not None:  # a comment on the timeline: changes only that moment (cutmind/moment.py)
            from .moment import moment_options, read_comment

            job = db.last_job(pid, "done")
            if not job or not job["plan"]:
                raise ApiError(400, "no_plan", "Pehle ek edit banao — comment us edit ke kisi moment pe lagta hai.")
            plan = EditPlan.model_validate(json.loads(job["plan"]))
            if not read_comment(prompt)["understood"]:
                # the comment reader knows a few kinds of edit; everything else goes to the skill resolver (never a
                # dead end: apply when sure, else tap-able choices — docs/INTENT_FAILURE_REVIEW.md)
                return _resolve_or_ask(pid, prompt, plan, body.at)
            try:
                options["moment"] = moment_options(prompt, body.at, plan)
            except ValueError as exc:
                raise ApiError(422, "not_understood", str(exc)) from exc
        else:
            if _only_auto_guess(prompt, options):
                # "yaha screen white kar do" used to read as "auto edit" (from "kar do") and re-edit everything
                from .tools.resolve import CHOOSE_MIN, resolve

                if (res := resolve(prompt, {"comment": False})).choices and res.choices[0]["score"] >= CHOOSE_MIN:
                    last = db.last_job(pid, "done")
                    plan = EditPlan.model_validate(json.loads(last["plan"])) if last and last["plan"] else None
                    return _resolve_or_ask(pid, prompt, plan, None)
            _must_understand(prompt, options)
        job_id = jobs.submit(pid, prompt, options)
        return {"job_id": job_id, "status": "queued"}

    auto_ask = re.compile(r"(edit|auto|reel|reels|short|shorts|montage|vlog|video|bana|banao|banado|bana do)", re.I)

    def _only_auto_guess(prompt: str, options: dict[str, Any]) -> bool:
        """The old reader saw no edit in the words and fell back to "auto edit" although nobody asked for one."""
        from .memory import wants_my_style, wants_repeat

        if options or settings.planner_mode == "local" or wants_repeat(prompt) or wants_my_style(prompt):
            return False
        rec = parse_intent(prompt).recognized
        return bool(rec) and all(r.startswith("auto edit") for r in rec) and not auto_ask.search(prompt)

    def _resolve_or_ask(pid: str, prompt: str, plan: EditPlan | None, at: float | None) -> dict[str, Any]:
        """Apply the resolver's reading when it is clearly ahead; otherwise 422 "choose" with up to 3 choices (each
        is ready-to-run tool calls for POST /projects/{pid}/tools) and a request id for POST /tools/resolve/pick."""
        from .tools.resolve import context_from_plan, resolve
        from .unmet import UnmetLog

        ctx = context_from_plan(plan, at) if plan is not None else {}
        if at is None:
            ctx["comment"] = False
        log = UnmetLog(db)
        ctx["learned"] = log.learned(prompt)
        res = resolve(prompt, ctx)
        if res.decision == "apply":
            best = res.choices[0]
            try:
                job_id = jobs.submit_tools(pid, best["calls"], prompt)
            except ManualError as exc:
                raise ApiError(422, "bad_tools", str(exc)) from exc
            return {"job_id": job_id, "status": "queued", "did": best["label"]}
        rid = log.log(pid, prompt, ctx, res.decision, res.choices)
        where = f" ({at:.1f}s)" if at is not None else ""
        msg = (f'"{prompt[:60]}"{where} ke ek se zyada matlab ho sakte hain — jo chahiye us pe tap karo:'
               if res.decision == "choose" else
               f'"{prompt[:60]}"{where} pakka samajh nahi aaya. Shayad aap inme se kuch chahte ho:')
        chips = [{"id": c["id"], "label": c["label"], "calls": c["calls"]} for c in res.choices]
        raise ApiError(422, "choose", msg, {"choices": chips, "request_id": rid, "decision": res.decision})

    def _must_understand(prompt: str, options: dict[str, Any]) -> None:
        """Never turn a message the agent did not understand into a "default edit" the user did not ask for: say
        so, with the closest things it can do (the user taps one, or writes it differently)."""
        from .memory import wants_my_style, wants_repeat

        if settings.planner_mode == "local" or options or wants_repeat(prompt) or wants_my_style(prompt):
            return  # the local LLM reads free text itself; buttons / style picks / "same as before" are understood
        if not parse_intent(prompt).is_empty():
            return
        try:
            sugg = [s["label"] for s in PhraseBook(db).suggest(prompt)]
        except Exception:  # noqa: BLE001
            sugg = []
        hint = (" Shayad aapka matlab: " + " / ".join(f'"{s}"' for s in sugg) + "?") if sugg else ""
        if re.search(r"\b(video|vidoe|vdo|player|preview)\b.{0,25}\b(chal|chalu|play|ruk|band|atak|start)\w*.{0,20}"
                     r"\b(nahi|nhi|nai|gayi|gaya|raha|rahi|ho)\b|\b(play|chal)\w* (nahi|nhi) (ho|kar)", prompt.lower()):
            # "video to chalu hi nahi ho rahi": about the player, not an edit request
            raise ApiError(422, "player_help",
                           "Ye edit ki baat nahi, video player ki hai — isliye edit nahi kiya. Timeline ke neeche ▶ dabao. "
                           "Agar video 2 sec pe ruk jaata tha, wo bug theek ho gaya hai: page refresh karke dobara play "
                           "karo. Phir bhi na chale to mujhe batao.")
        if re.search(r"\b(wala|wali|wale|part|hissa|scene|clip|video|shot)\b", prompt.lower()):
            # "boat wala part zyada dikhao": things IN the picture are not recognised yet — say what works instead
            raise ApiError(422, "not_understood",
                           f'"{prompt[:80]}" — video ke andar ki cheezein (jaise boat, church) main abhi pehchan nahi '
                           'sakta, isliye edit nahi kiya. Clip number se bolo: "pehla clip hata do", "dusra clip mat '
                           'dikhao", ya "last wala video nikal do".')
        raise ApiError(422, "not_understood",
                       f'Ye samajh nahi aaya: "{prompt[:80]}". Edit nahi kiya.{hint} Aise likho: "captions lagao", '
                       '"gaana badlo", "black and white karo", "thoda slow karo".')

    @app.get("/jobs/{job_id}", tags=["edit"])
    def get_job(job_id: str) -> dict[str, Any]:
        snap = jobs.get(job_id)
        if not snap:
            raise ApiError(404, "job_not_found", f"Job {job_id} does not exist.")
        return snap

    @app.get("/jobs/{job_id}/events", tags=["edit"])
    async def job_events(job_id: str, after: int = Query(0, ge=0)) -> StreamingResponse:
        """Server-Sent Events: every real step of the job (agent started/finished, graph node timings, logs,
        review scores, final_ready). Ends when the job is finished. `after` resumes from an event number."""
        if not jobs.get(job_id):
            raise ApiError(404, "job_not_found", f"Job {job_id} does not exist.")

        async def stream():  # noqa: ANN202
            seq = after
            idle = 0
            while True:
                state = jobs.states.get(job_id)
                if state is not None:
                    new, status = state.events_after(seq), state.data["status"]
                else:  # finished in an earlier server run: replay what was saved
                    snap = jobs.get(job_id) or {}
                    new, status = [e for e in snap.get("events", []) if e["seq"] > seq], snap.get("status", "done")
                for e in new:
                    seq = e["seq"]
                    yield f"id: {seq}\nevent: {e['type']}\ndata: {json.dumps(e, default=str)}\n\n"
                if status in ("done", "failed") and not new:
                    yield f"event: end\ndata: {json.dumps({'status': status})}\n\n"
                    return
                idle = 0 if new else idle + 1
                if idle and idle % 50 == 0:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.25)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/capabilities", tags=["system"])
    def capabilities() -> dict[str, Any]:
        """CapabilityManager: CPU / RAM / GPU / disk / FFmpeg / Whisper / LLM, and what that enables."""
        return detect_capabilities(settings).to_dict()

    @app.get("/agents", tags=["system"])
    def agents_registry(prompt: str | None = None) -> dict[str, Any]:
        """The specialist registry; with `prompt`, which specialists the router would run for it."""
        out: dict[str, Any] = {**registry_summary(),
                               "specialists": [{"id": s.id, "name": s.name, "category": s.category, "impl": s.impl,
                                                "available": s.available} for s in REGISTRY]}
        if prompt:
            try:
                out["selected"] = [s.id for s in route(parse_intent(validate_prompt(prompt)))]
            except PromptError as exc:
                raise ApiError(422, "bad_prompt", str(exc)) from exc
        return out

    @app.get("/workflow", tags=["system"])
    def workflow_graph() -> dict[str, Any]:
        """The LangGraph workflow (Mermaid) for developer mode."""
        return {"mermaid": graph_mermaid()}

    @app.get("/projects/{pid}/plan", tags=["edit"])
    def get_plan(pid: str) -> dict[str, Any]:
        project_or_404(pid)
        job = db.last_job(pid, "done")
        if not job or not job["plan"]:
            raise ApiError(404, "no_plan", "No finished edit yet for this project.")
        return json.loads(job["plan"])

    @app.get("/projects/{pid}/output", tags=["edit"], response_class=FileResponse)
    def get_output(pid: str, format: Literal["mp4", "gif", "mp3"] = "mp4",  # noqa: A002
                   variant: int | None = Query(None, ge=0, le=2),
                   v: str | None = Query(None, max_length=64, description="job id of the version to play")) -> FileResponse:
        project_or_404(pid)
        if v:
            # exactly the version asked for. Serving "the latest" under a running job's id let the browser cache the
            # OLD file under that URL and later mix it with byte ranges of the new one: the video stopped halfway
            job = db.get_job(v)
            if not job or job["project_id"] != pid or job["status"] != "done":
                raise ApiError(404, "no_output", "This version is not rendered yet.")
        else:
            job = db.last_job(pid, "done")
        if not job or not job["output_path"] or not Path(job["output_path"]).exists():
            raise ApiError(404, "no_output", "No rendered video yet for this project.")
        main = Path(job["output_path"])
        if variant is not None:
            main = main.with_name(f"{main.stem}_v{variant}.mp4")
            if not main.exists():
                raise ApiError(404, "no_variant", f"The last edit has no version {variant}.")
        path = main if format == "mp4" else extra_path(main, format)
        if not path.exists():
            raise ApiError(404, "no_output", f"The last edit has no {format.upper()} — ask for it in the prompt "
                                             f"(e.g. 'also export a {format.upper()}').")
        media = {"mp4": "video/mp4", "gif": "image/gif", "mp3": "audio/mpeg"}[format]
        # a versioned URL never changes its bytes; the bare URL ("the latest") must be re-checked every time
        cache = "private, max-age=31536000, immutable" if v else "no-cache"
        return FileResponse(path, media_type=media, filename=f"cutmind_{pid}.{format}",
                            headers={"Cache-Control": cache})

    @app.post("/jobs/{job_id}/feedback", tags=["learning"])
    def feedback(job_id: str, body: FeedbackIn) -> dict[str, Any]:
        job = db.get_job(job_id)
        if not job:
            raise ApiError(404, "job_not_found", f"Job {job_id} does not exist.")
        if job["status"] != "done":
            raise ApiError(409, "job_not_finished", "Feedback can only be given on a finished job.")
        if body.agent and body.agent not in AGENT_ROLES:
            raise ApiError(422, "unknown_agent", f"Unknown agent '{body.agent}'. Use one of: {', '.join(AGENT_ROLES)}")
        per_agent = 5 if body.rating == "up" else -5
        targets = [body.agent] if body.agent else [a for a in AGENT_ROLES if a != "reviewer"]
        for a in targets:
            db.add_score(job_id, a, 0, f"user_{body.rating}", per_agent, body.comment or f"user thumbs {body.rating}")
        if body.rating == "down" and body.comment:
            for a in targets if body.agent else ["director"]:
                db.add_lesson(a, "user_feedback", f"user_feedback: user disliked the result: {body.comment[:150]}", job_id)
        db.add_feedback(job_id, body.rating, body.comment, body.agent, per_agent * len(targets))
        Learner(db).reward(job_id, 1.0 if body.rating == "up" else 0.0)  # the taste knobs this edit used
        jobs.memory.remember_rating(job_id, body.rating)
        return {"ok": True, "points_delta": per_agent, "agents": targets}

    @app.get("/phrasebook", tags=["learning"])
    def phrasebook() -> dict[str, Any]:
        """Phrases you taught the agent, phrases it did not understand yet, and the commands it can map them to."""
        pb = PhraseBook(db)
        return {"taught": pb.taught(), "misses": pb.misses(), "commands": COMMANDS}

    @app.post("/phrasebook", tags=["learning"], status_code=201)
    def teach_phrase(body: TeachIn) -> dict[str, Any]:
        """"rang thode feeke kar do" means "Faded film look." — remembered for every later prompt."""
        try:
            PhraseBook(db).teach(body.phrase, body.command)
        except ValueError as exc:
            raise ApiError(422, "unknown_command", str(exc)) from exc
        return {"ok": True, "phrase": body.phrase.strip().lower(), "command": body.command}

    @app.get("/learning", tags=["learning"])
    def learning_state() -> dict[str, Any]:
        """What the agents learned from your reactions (per video type + song feel): score of each option."""
        return {"knobs": KNOBS, "arms": Learner(db).summary()}

    @app.get("/projects/{pid}/memory", tags=["learning"])
    def project_memory(pid: str) -> dict[str, Any]:
        """What the agents remember: this project's past edits + the user's preferences across projects."""
        project_or_404(pid)
        return {"history": jobs.memory.history(pid, 20), "preferences": jobs.memory.preferences(),
                "summary": jobs.memory.summary(pid)}

    @app.get("/fx", tags=["edit"])
    def fx() -> dict[str, Any]:
        """Every effect, motion, transition, colour look and text animation the agents can use."""
        cat = fx_catalog()
        return {"catalog": cat, "counts": {k: len(v) for k, v in cat.items()}}

    @app.get("/styles", tags=["edit"])
    def styles() -> dict[str, Any]:
        return {"styles": public_styles()}

    @app.post("/jobs/{job_id}/choose", tags=["edit"])
    def choose_variant(job_id: str, body: ChooseIn) -> dict[str, Any]:
        try:
            chosen = jobs.choose(job_id, body.variant)
        except KeyError as exc:
            raise ApiError(404, "no_variant", str(exc).strip("'\"")) from exc
        except ValueError as exc:
            raise ApiError(409, "job_not_finished", str(exc)) from exc
        return {"ok": True, "chosen": chosen}

    def _clip_media(pid: str, clip_id: str) -> tuple[Path, Path]:
        project_or_404(pid)
        clip = db.get_clip(clip_id)
        if not clip or clip["project_id"] != pid:
            raise ApiError(404, "clip_not_found", f"Clip {clip_id} not found in this project.")
        source = Path(clip["path"])
        return existing_proxy(source) or source, jobs.project_dir(pid) / "clips"

    @app.get("/projects/{pid}/clips/{clip_id}/filmstrip", tags=["clips"], response_class=FileResponse)
    def clip_filmstrip(pid: str, clip_id: str, frames: int = Query(10, ge=2, le=30)) -> FileResponse:
        media, cache = _clip_media(pid, clip_id)
        return FileResponse(filmstrip(media, cache, clip_id, frames), media_type="image/jpeg")

    @app.get("/projects/{pid}/clips/{clip_id}/frame", tags=["clips"], response_class=FileResponse)
    def clip_frame(pid: str, clip_id: str, t: float = Query(0.0, ge=0), w: int = Query(160, ge=48, le=480)) -> FileResponse:
        """A small picture of the clip at t seconds (the live timeline's shot thumbnails)."""
        media, cache = _clip_media(pid, clip_id)
        try:
            return FileResponse(frame_at(media, cache, clip_id, t, w), media_type="image/jpeg")
        except FFmpegError as exc:
            raise ApiError(404, "frame_not_found", f"No frame at {t:.2f}s.") from exc

    @app.get("/projects/{pid}/clips/{clip_id}/waveform", tags=["clips"])
    def clip_waveform(pid: str, clip_id: str, points: int = Query(200, ge=20, le=2000)) -> dict[str, Any]:
        media, cache = _clip_media(pid, clip_id)
        return waveform(media, cache, clip_id, points)

    @app.get("/agents/scoreboard", tags=["learning"])
    def scoreboard() -> dict[str, Any]:
        return {"agents": db.scoreboard()}

    @app.get("/agents/{name}/lessons", tags=["learning"])
    def lessons(name: str) -> dict[str, Any]:
        if name not in AGENT_ROLES:
            raise ApiError(404, "agent_not_found", f"Unknown agent '{name}'.")
        return {"agent": name, "lessons": db.recent_lessons(name, 20)}

    return app

