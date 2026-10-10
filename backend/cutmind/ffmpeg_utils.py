"""Thin, typed wrappers around the ffmpeg / ffprobe command line tools."""

from __future__ import annotations

import glob
import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from .config import get_settings


class FFmpegError(RuntimeError):
    """Raised when ffmpeg/ffprobe fails; `stderr_tail` holds the useful part of the log."""

    def __init__(self, message: str, stderr_tail: str = "") -> None:
        super().__init__(message if not stderr_tail else f"{message}: {stderr_tail}")
        self.stderr_tail = stderr_tail


def _search_binary(name: str, override: str | None) -> str | None:
    if override and Path(override).exists():
        return override
    found = shutil.which(name)
    if found:
        return found
    # Windows winget installs often aren't on PATH until a new shell starts.
    local = os.environ.get("LOCALAPPDATA")
    if local:
        pattern = os.path.join(local, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "*", "bin", f"{name}.exe")
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    return None


@lru_cache(maxsize=None)
def ffmpeg_bin() -> str:
    path = _search_binary("ffmpeg", get_settings().ffmpeg_bin)
    if not path:
        raise FFmpegError("ffmpeg not found. Install it (see SETUP.md) or set FFMPEG_BIN.")
    return path


@lru_cache(maxsize=None)
def ffprobe_bin() -> str:
    path = _search_binary("ffprobe", get_settings().ffprobe_bin)
    if not path:
        raise FFmpegError("ffprobe not found. Install it (see SETUP.md) or set FFPROBE_BIN.")
    return path


def ffmpeg_available() -> bool:
    try:
        ffmpeg_bin()
        ffprobe_bin()
        return True
    except FFmpegError:
        return False


STALL_S = 300.0  # ffmpeg prints progress every ~0.5 s; this long without any output means it is stuck


def run_ffmpeg(args: list[str], cwd: Path | None = None, timeout: float | None = None, stall: float = STALL_S) -> str:
    """Run ffmpeg with the given args; returns stderr (ffmpeg logs there). Raises FFmpegError.

    No fixed time limit by default: a 20-minute 1080p export legitimately takes about an hour on a laptop (a flat
    15-minute limit killed it — eval/perf_probe.py 20). Instead ffmpeg is stopped when it prints nothing for
    `stall` seconds (a hung filter graph), or after `timeout` seconds if the caller gives one.
    Raises subprocess.TimeoutExpired in both cases, as before."""
    import threading
    import time

    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", *args]
    proc = subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    chunks: list[bytes] = []
    last = [time.monotonic()]

    def pump() -> None:  # progress lines end in a carriage return, so read raw chunks, not lines
        assert proc.stderr is not None
        for b in iter(lambda: proc.stderr.read1(4096), b""):
            chunks.append(b)
            last[0] = time.monotonic()

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    start = time.monotonic()
    while proc.poll() is None:
        now = time.monotonic()
        if now - last[0] > stall or (timeout is not None and now - start > timeout):
            proc.kill()
            proc.wait()
            raise subprocess.TimeoutExpired(cmd, timeout if timeout is not None else stall)
        time.sleep(0.2)
    reader.join(timeout=10)
    proc = subprocess.CompletedProcess(cmd, proc.returncode, None,
                                       b"".join(chunks).decode("utf-8", errors="replace"))
    if proc.returncode != 0:
        # prefer the lines that actually describe the error over encoder statistics
        lines = proc.stderr.strip().splitlines()
        errors = [ln for ln in lines if re.search(r"error|invalid|no such|not found|failed|cannot", ln, re.I)]
        pick = (errors or lines)
        # the FIRST error names the broken filter; the last ones only say that everything stopped
        summary = list(dict.fromkeys(pick[:4] + pick[-2:]))
        try:  # the whole log + command, for debugging (the work folder is cleaned up after a job)
            import tempfile

            log = Path(tempfile.gettempdir()) / "cutmind_last_ffmpeg_error.log"
            log.write_text(" ".join(cmd) + "\n\n" + proc.stderr, encoding="utf-8")
        except OSError:
            pass
        raise FFmpegError("ffmpeg failed", "\n".join(summary))
    return proc.stderr


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    has_video: bool
    video_codec: str | None
    audio_codec: str | None
    sample_rate: int | None
    size_bytes: int
    audio_duration: float | None = None  # audio can be shorter than the video
    created: str | None = None  # container/stream `creation_time` tag (camera recording time), if any


def _parse_rate(rate: str | None) -> float:
    if not rate or rate in {"0/0", "N/A"}:
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        return float(num) / float(den) if float(den) else 0.0
    return float(rate)


def probe(path: Path) -> MediaInfo:
    """ffprobe a file. Raises FFmpegError for unreadable / corrupt files."""
    cmd = [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if proc.returncode != 0:
        raise FFmpegError("ffprobe could not read the file", proc.stderr.strip()[-300:])
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or (v or {}).get("duration") or 0.0)
    return MediaInfo(
        duration=duration,
        width=int((v or {}).get("width") or 0),
        height=int((v or {}).get("height") or 0),
        fps=round(_parse_rate((v or {}).get("avg_frame_rate") or (v or {}).get("r_frame_rate")), 3),
        has_audio=a is not None,
        has_video=v is not None,
        video_codec=(v or {}).get("codec_name"),
        audio_codec=(a or {}).get("codec_name"),
        sample_rate=int(a["sample_rate"]) if a and a.get("sample_rate") else None,
        size_bytes=int(fmt.get("size") or (path.stat().st_size if path.exists() else 0)),
        audio_duration=float(a["duration"]) if a and a.get("duration") not in (None, "N/A") else None,
        created=(fmt.get("tags", {}).get("creation_time") or (v or {}).get("tags", {}).get("creation_time")),
    )


def decode_check(path: Path, timeout: float | None = None) -> tuple[bool, str]:
    """Fully decode the file to /dev/null. Returns (ok, error_text). Proves the file plays.
    Default limit: 600 s or the video's own length, whichever is longer (a 20-minute export needs more)."""
    if timeout is None:
        try:
            timeout = max(600.0, probe(path).duration)
        except Exception:  # noqa: BLE001 — an unreadable file fails the decode below anyway
            timeout = 600.0
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-i", str(path), "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    err = proc.stderr.strip()
    return proc.returncode == 0 and not err, err[-400:]


def extract_frame(path: Path, t: float, width: int | None = None, height: int | None = None) -> np.ndarray:
    """Return one RGB frame (H, W, 3) uint8 at time t (seconds)."""
    info_w, info_h = width, height
    if info_w is None or info_h is None:
        info = probe(path)
        info_w, info_h = info.width, info.height
    cmd = [
        ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path),
        "-frames:v", "1", "-vf", f"scale={info_w}:{info_h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=60)
    expected = info_w * info_h * 3
    if proc.returncode != 0 or len(proc.stdout) < expected:
        raise FFmpegError(f"could not extract frame at {t:.2f}s", proc.stderr.decode(errors="replace")[-300:])
    return np.frombuffer(proc.stdout[:expected], dtype=np.uint8).reshape(info_h, info_w, 3)


def save_frame_jpg(path: Path, t: float, out: Path, width: int = 320) -> Path:
    run_ffmpeg(["-ss", f"{max(0.0, t):.3f}", "-i", str(path), "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(out)])
    return out


_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SIL_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def detect_silence(path: Path, noise_db: float = -35.0, min_dur: float = 0.5) -> list[tuple[float, float]]:
    """Silent intervals [(start, end)] via ffmpeg silencedetect. Empty if the file has no audio."""
    info = probe(path)
    if not info.has_audio:
        return []
    log = run_ffmpeg(["-i", str(path), "-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"])
    out: list[tuple[float, float]] = []
    start: float | None = None
    for line in log.splitlines():
        m = _SIL_START.search(line)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = _SIL_END.search(line)
        if m and start is not None:
            out.append((start, float(m.group(1))))
            start = None
    if start is not None:  # silence runs to the end of file
        out.append((start, info.duration))
    # the audio stream may end before the video does: that tail is silent too
    audio_end = info.audio_duration
    if audio_end is not None and info.duration - audio_end > 0.3:
        if out and out[-1][1] >= audio_end - 0.1:
            out[-1] = (out[-1][0], info.duration)
        else:
            out.append((audio_end, info.duration))
    return out


def measure_loudness(path: Path) -> dict[str, float]:
    """Integrated loudness (LUFS), true peak and max volume. Empty dict if no audio."""
    info = probe(path)
    if not info.has_audio:
        return {}
    # volumedetect FIRST: it passes audio through unchanged, so peak/mean are measured on the real signal
    # (with loudnorm first they were measured on the normalised copy — a bug found while testing fades)
    log = run_ffmpeg(["-i", str(path), "-vn", "-af", "volumedetect,loudnorm=print_format=json", "-f", "null", "-"])
    result: dict[str, float] = {}
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log, re.S)
    if m:
        data = json.loads(m.group(0))
        for key, name in (("input_i", "lufs"), ("input_tp", "true_peak"), ("input_lra", "lra")):
            try:
                v = float(data[key])
            except (KeyError, ValueError):
                continue
            # a silent track measures -inf, which JSON can't store (it came back as null and broke the cache)
            result[name] = v if math.isfinite(v) else -99.0
    m = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", log)
    if m:
        result["max_volume"] = float("-inf") if m.group(1) == "-inf" else float(m.group(1))
    m = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", log)
    if m:
        result["mean_volume"] = float("-inf") if m.group(1) == "-inf" else float(m.group(1))
    return result


def extract_audio_wav(path: Path, out: Path, sr: int = 16000) -> Path:
    run_ffmpeg(["-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(out)])
    return out
