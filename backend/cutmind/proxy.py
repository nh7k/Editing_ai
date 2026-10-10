"""Edit proxies: a light H.264 copy of each heavy source clip, made once (at upload) and used for every edit.

Professional editors work the same way. A 1080p60 MJPEG `.avi` costs far more to decode than a 720p30 H.264
file; since most outputs are ≤720p, analysing and rendering from the proxy makes every edit several times
faster. The timeline is identical (same duration, constant frame rate), so cut points don't change.
"""

from __future__ import annotations

import threading
from pathlib import Path

from .ffmpeg_utils import MediaInfo, probe, run_ffmpeg

PROXY_SHORT_SIDE = 720
PROXY_FPS = 30
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def proxy_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}_proxy.mp4")


def needs_proxy(info: MediaInfo) -> bool:
    """Heavy to decode: not H.264, high frame rate, or bigger than the proxy size."""
    short = min(info.width, info.height)
    return info.video_codec != "h264" or info.fps > PROXY_FPS + 1 or short > PROXY_SHORT_SIDE


def ensure_proxy(source: Path) -> Path | None:
    """Create the proxy if useful (thread-safe, idempotent). Returns its path, or None when not needed."""
    target = proxy_path(source)
    with _lock_for(str(source)):
        if target.exists():
            return target
        info = probe(source)
        if not needs_proxy(info):
            return None
        tmp = target.with_name(target.stem + ".part.mp4")
        # short side → 720 (never upscale), constant 30 fps so timestamps stay exact
        scale = (f"scale=-2:'min({PROXY_SHORT_SIDE},ih)'" if info.width >= info.height
                 else f"scale='min({PROXY_SHORT_SIDE},iw)':-2")
        args = ["-i", str(source), "-map", "0:v:0", "-map", "0:a:0?", "-vf", f"fps={PROXY_FPS},{scale}",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "21", "-maxrate", "6M", "-bufsize", "12M",
                "-pix_fmt", "yuv420p", "-g", "30",  # cap: 4K phone footage made 20 Mbit/s "light" copies
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(tmp)]
        run_ffmpeg(args)
        tmp.replace(target)
        return target


def existing_proxy(source: Path) -> Path | None:
    target = proxy_path(source)
    return target if target.exists() else None
