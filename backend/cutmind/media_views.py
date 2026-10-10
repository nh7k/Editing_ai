"""Small, cached views of a clip for the timeline UI: a filmstrip image and waveform peaks."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

from .ffmpeg_utils import ffmpeg_bin, probe, run_ffmpeg

FRAME_W, FRAME_H = 160, 90


def filmstrip(media: Path, cache_dir: Path, clip_id: str, frames: int = 10) -> Path:
    """`frames` evenly spaced thumbnails side by side (each 160×90, cover-cropped) as one JPEG."""
    out = cache_dir / f"{clip_id}_strip{frames}.jpg"
    if out.exists():
        return out
    dur = max(0.1, probe(media).duration)
    run_ffmpeg(["-i", str(media), "-vf",
                f"fps={frames / dur:.6f},scale={FRAME_W}:{FRAME_H}:force_original_aspect_ratio=increase,"
                f"crop={FRAME_W}:{FRAME_H},tile={frames}x1", "-frames:v", "1", "-q:v", "5", str(out)])
    return out


def waveform(media: Path, cache_dir: Path, clip_id: str, points: int = 200) -> dict:
    """Peak amplitude (0..1) per bucket. Silent / no-audio clips give zeros."""
    out = cache_dir / f"{clip_id}_wave{points}.json"
    if out.exists():
        return json.loads(out.read_text(encoding="utf-8"))
    info = probe(media)
    peaks = [0.0] * points
    if info.has_audio:
        raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", "8000",
                              "-f", "s16le", "-"], capture_output=True, timeout=300).stdout
        samples = np.abs(np.frombuffer(raw, dtype=np.int16).astype(np.float32)) / 32768.0
        if samples.size:
            buckets = np.array_split(samples, points)
            peaks = [round(float(b.max()) if b.size else 0.0, 4) for b in buckets]
            top = max(peaks) or 1.0
            peaks = [round(p / top, 4) for p in peaks]  # normalise so quiet clips are still visible
    data = {"peaks": peaks, "duration": round(info.duration, 3)}
    out.write_text(json.dumps(data), encoding="utf-8")
    return data


def frame_at(media: Path, cache_dir: Path, clip_id: str, t: float, width: int = 160) -> Path:
    """One small JPEG of the clip at `t` s (the live timeline's shot thumbnails). Cached per 0.25 s."""
    t = round(max(0.0, t) * 4) / 4
    out = cache_dir / "frames" / f"{clip_id}_{t:.2f}_{width}.jpg"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-ss", f"{t:.2f}", "-i", str(media), "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "6", str(out)])
    return out
