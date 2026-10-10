"""Runtime configuration, read from environment variables (no secrets, no hard-coded paths)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    planner_mode: str = field(default_factory=lambda: os.environ.get("PLANNER_MODE", "mock").lower())
    # In-process LLM (PLANNER_MODE=local): any Qwen2-style ONNX decoder from Hugging Face.
    llm_repo: str = field(default_factory=lambda: os.environ.get("LLM_REPO", "auto"))
    llm_file: str = field(default_factory=lambda: os.environ.get("LLM_FILE", "onnx/model_q4.onnx"))
    llm_model_dir: str | None = field(default_factory=lambda: os.environ.get("LLM_MODEL_DIR") or None)
    llm_max_new_tokens: int = field(default_factory=lambda: int(os.environ.get("LLM_MAX_NEW_TOKENS", "120")))
    llm_threads: int = field(default_factory=lambda: int(os.environ.get("LLM_THREADS", "0")))
    # Which agents ask the LLM: "director" (1 call per job — default, fast on CPU) or "all".
    llm_preload: bool = field(default_factory=lambda: _env_bool("LLM_PRELOAD", True))
    # Production: set CUTMIND_API_KEY to require an `X-API-Key` header; CORS_ORIGINS is a comma list ("*" = any).
    api_key: str | None = field(default_factory=lambda: os.environ.get("CUTMIND_API_KEY") or None)
    cors_origins: str = field(default_factory=lambda: os.environ.get("CORS_ORIGINS", "*"))
    llm_agents: str = field(default_factory=lambda: os.environ.get("LLM_AGENTS", "director").lower())

    def llm_enabled_for(self, agent: str) -> bool:
        if self.planner_mode != "local":
            return False
        return self.llm_agents == "all" or agent in {a.strip() for a in self.llm_agents.split(",")}
    whisper_model: str = field(default_factory=lambda: os.environ.get("WHISPER_MODEL", "tiny"))
    enable_transcription: bool = field(default_factory=lambda: _env_bool("ENABLE_TRANSCRIPTION", True))
    # editorial brain (skills / genres / platforms → inferred professional choices); EDITORIAL=0 = baseline
    editorial: bool = field(default_factory=lambda: _env_bool("EDITORIAL", True))
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("CUTMIND_DATA_DIR", str(PROJECT_ROOT / "data"))).resolve()
    )
    music_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("MUSIC_DIR", str(BACKEND_DIR / "assets" / "music"))).resolve()
    )
    max_upload_mb: int = field(default_factory=lambda: int(os.environ.get("MAX_UPLOAD_MB", "500")))
    max_clips: int = field(default_factory=lambda: int(os.environ.get("MAX_CLIPS", "20")))
    score_threshold: int = field(default_factory=lambda: int(os.environ.get("SCORE_THRESHOLD", "70")))
    max_agent_retries: int = field(default_factory=lambda: int(os.environ.get("MAX_AGENT_RETRIES", "2")))
    ffmpeg_bin: str | None = field(default_factory=lambda: os.environ.get("FFMPEG_BIN"))
    ffprobe_bin: str | None = field(default_factory=lambda: os.environ.get("FFPROBE_BIN"))
    keep_work_dirs: bool = field(default_factory=lambda: _env_bool("KEEP_WORK_DIRS", False))

    allowed_extensions: tuple[str, ...] = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi")

    def __post_init__(self) -> None:
        if self.planner_mode not in {"mock", "local"}:
            raise ValueError(f"PLANNER_MODE must be 'mock' or 'local', got {self.planner_mode!r}")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cutmind.sqlite3"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> Settings:
    """Re-read env vars (used by tests)."""
    global _settings
    _settings = Settings()
    return _settings
