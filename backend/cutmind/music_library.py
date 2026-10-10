"""Songs: the built-in royalty-free library plus the songs a user uploads to a project.

Project songs live in data/projects/<id>/music/ (any audio file, or the sound of a video file, stored as .m4a).
`selected.json` remembers which one the user picked in the Sounds panel. A plan stores just the file name; the
renderer looks in the project folder first, then the library.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import Settings
from .ffmpeg_utils import probe, run_ffmpeg

AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac", ".opus", ".wma"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".3gp"}
MAX_SONG_SECONDS = 15 * 60


class SongError(ValueError):
    pass


def project_music_dir(settings: Settings, project_id: str | None) -> Path | None:
    return settings.projects_dir / project_id / "music" if project_id else None


def music_dirs(settings: Settings, project_id: str | None) -> list[Path]:
    d = project_music_dir(settings, project_id)
    return [d, settings.music_dir] if d is not None else [settings.music_dir]


def resolve(name: str, dirs: list[Path]) -> Path | None:
    for d in dirs:
        p = d / name
        if p.is_file() and p.resolve().parent == d.resolve():  # no path tricks in the name
            return p
    return None


def project_songs(settings: Settings, project_id: str) -> list[Path]:
    d = project_music_dir(settings, project_id)
    if d is None or not d.exists():
        return []
    return sorted((p for p in d.iterdir() if p.suffix.lower() in AUDIO_EXTS and p.is_file()),
                  key=lambda p: p.stat().st_mtime, reverse=True)  # newest first


def selected_song(settings: Settings, project_id: str) -> str | None:
    d = project_music_dir(settings, project_id)
    f = d / "selected.json" if d else None
    if f is None or not f.exists():
        return None
    try:
        name = json.loads(f.read_text(encoding="utf-8")).get("name")
    except ValueError:
        return None
    return name if name and resolve(name, music_dirs(settings, project_id)) else None


def set_selected(settings: Settings, project_id: str, name: str | None) -> None:
    d = project_music_dir(settings, project_id)
    assert d is not None
    if name is not None and resolve(name, music_dirs(settings, project_id)) is None:
        raise SongError(f"no song called '{name}'")
    d.mkdir(parents=True, exist_ok=True)
    (d / "selected.json").write_text(json.dumps({"name": name}), encoding="utf-8")


def safe_name(filename: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9 _.-]+", "", Path(filename).stem).strip(" .")[:60] or "song"
    return stem.replace(" ", "_")


def import_song(settings: Settings, project_id: str, src: Path, filename: str) -> Path:
    """Store an uploaded song (or the sound of an uploaded video) as <name>.m4a in the project. Checks it is real
    audio first; the upload itself is deleted by the caller."""
    ext = Path(filename).suffix.lower()
    if ext not in AUDIO_EXTS | VIDEO_EXTS:
        raise SongError(f"'{ext or filename}' is not a song file — use mp3, m4a, wav, aac, ogg, flac or a video")
    try:
        info = probe(src)
    except Exception as e:  # noqa: BLE001
        raise SongError("this file could not be read as audio (corrupt or unsupported)") from e
    if not info.has_audio:
        raise SongError("this file has no sound in it")
    if info.duration > MAX_SONG_SECONDS:
        raise SongError(f"songs can be at most {MAX_SONG_SECONDS // 60} minutes long")
    d = project_music_dir(settings, project_id)
    assert d is not None
    d.mkdir(parents=True, exist_ok=True)
    base, n = safe_name(filename), 1
    out = d / f"{base}.m4a"
    while out.exists():
        n += 1
        out = d / f"{base}_{n}.m4a"
    run_ffmpeg(["-i", str(src), "-vn", "-ac", "2", "-ar", "44100", "-c:a", "aac", "-b:a", "192k", str(out)])
    return out
