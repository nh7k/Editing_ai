"""The judge's own measurements — independent of the app: it calls ffprobe / ffmpeg itself and never imports the
app's verifier, reviewer or messages. Everything is direction-and-tolerance based, on small frames.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
W = H = 160  # one fixed analysis size for every frame (like with like, any aspect)


def _run(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout)


@lru_cache(maxsize=512)
def info(path: str) -> dict:
    """ffprobe facts: duration, video size, fps, audio present, audio duration, rotation."""
    r = _run([FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", path])
    if r.returncode != 0:
        return {"ok": False, "error": r.stderr.decode(errors="replace")[-200:]}
    d = json.loads(r.stdout or b"{}")
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    rot = 0
    for sd in (v or {}).get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    num, _, den = ((v or {}).get("avg_frame_rate") or "0/1").partition("/")
    return {"ok": True, "duration": float(d.get("format", {}).get("duration") or 0.0),
            "width": int((v or {}).get("width") or 0), "height": int((v or {}).get("height") or 0),
            "fps": float(num) / float(den or 1) if float(den or 1) else 0.0, "has_video": v is not None,
            "has_audio": a is not None, "audio_duration": float((a or {}).get("duration") or 0.0),
            "video_duration": float((v or {}).get("duration") or 0.0), "rotation": rot,
            "size": int(d.get("format", {}).get("size") or 0)}


def decodes(path: str) -> tuple[bool, str]:
    r = _run([FFMPEG, "-v", "error", "-i", path, "-f", "null", "-"], timeout=600)
    err = r.stderr.decode(errors="replace").strip()
    return r.returncode == 0 and not err, err[-200:]


def frame(path: str, t: float) -> np.ndarray:
    r = _run([FFMPEG, "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", path, "-frames:v", "1",
              "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    raw = r.stdout
    if len(raw) < W * H * 3:
        raise RuntimeError(f"no frame at {t:.2f}s in {Path(path).name}")
    return np.frombuffer(raw[:W * H * 3], dtype=np.uint8).reshape(H, W, 3).astype(float)


def stats(f: np.ndarray) -> dict[str, float]:
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    lap = np.abs(4 * lum[1:-1, 1:-1] - lum[:-2, 1:-1] - lum[2:, 1:-1] - lum[1:-1, :-2] - lum[1:-1, 2:])
    k = H // 5
    corners = np.concatenate([lum[:k, :k].ravel(), lum[:k, -k:].ravel(), lum[-k:, :k].ravel(), lum[-k:, -k:].ravel()])
    centre = lum[2 * k:3 * k, 2 * k:3 * k]
    return {"warmth": float((r - b).mean()), "luma": float(lum.mean()), "contrast": float(lum.std()),
            "sat": float((f.max(axis=2) - f.min(axis=2)).mean()), "edges": float(lap.mean()),
            "corner_vs_centre": float(corners.mean() - centre.mean()),
            "sepia": float(((r - b) > 15).mean()) if float((f.max(axis=2) - f.min(axis=2)).mean()) < 60 else 0.0}


def frame_diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a - b).mean())


def region_diff(a: np.ndarray, b: np.ndarray, rows: tuple[float, float]) -> float:
    lo, hi = int(rows[0] * H), int(rows[1] * H)
    return float(np.abs(a[lo:hi] - b[lo:hi]).mean())


def zoom_factor(src: np.ndarray, out: np.ndarray) -> float:
    """The centre-crop scale s (1.0-1.6) that makes the source look most like the output (1.0 = not zoomed)."""
    best, best_s = 1e9, 1.0
    for s in np.arange(1.0, 1.61, 0.05):
        cw, ch = int(W / s), int(H / s)
        x0, y0 = (W - cw) // 2, (H - ch) // 2
        crop = src[y0:y0 + ch, x0:x0 + cw]
        yi = (np.arange(H) * ch / H).astype(int)
        xi = (np.arange(W) * cw / W).astype(int)
        up = crop[yi][:, xi]
        e = float(np.abs(up - out).mean())
        if e < best - 1e-6:
            best, best_s = e, float(s)
    return best_s


def pcm(path: str, t: float, length: float, rate: int = 16000) -> np.ndarray:
    r = _run([FFMPEG, "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-t", f"{length:.3f}", "-i", path, "-vn",
              "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"])
    return np.frombuffer(r.stdout, dtype=np.int16).astype(float) / 32768.0


def rms_db(path: str, t: float, length: float = 1.0) -> float:
    x = pcm(path, t, length)
    return float(20 * np.log10(max(1e-9, np.sqrt(np.mean(x ** 2))))) if len(x) else -120.0


def band_db(path: str, t: float, length: float, lo: float, hi: float) -> float:
    """Energy in a frequency band (dB) — the synthetic music's kick is at 55-65 Hz, the TTS voice is 100-4000 Hz."""
    x = pcm(path, t, length)
    if len(x) < 512:
        return -120.0
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    fr = np.fft.rfftfreq(len(x), 1 / 16000)
    e = spec[(fr >= lo) & (fr < hi)].sum() / max(1, len(x))
    return float(10 * np.log10(max(1e-12, e)))


def silences(path: str, noise_db: float = -35, min_dur: float = 0.6) -> list[tuple[float, float]]:
    r = _run([FFMPEG, "-v", "info", "-i", path, "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
              "-f", "null", "-"], timeout=300)
    txt = r.stderr.decode(errors="replace")
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", txt)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?[\d.]+)", txt)]
    d = info(path).get("duration", 0.0)
    return [(max(0.0, a), ends[i] if i < len(ends) else d) for i, a in enumerate(starts)]


def silence_ratio(path: str) -> float:
    d = info(path).get("duration") or 1.0
    return sum(b - a for a, b in silences(path)) / d


def lufs(path: str) -> float:
    r = _run([FFMPEG, "-v", "info", "-i", path, "-af", "ebur128", "-f", "null", "-"], timeout=300)
    m = re.findall(r"I:\s*(-?[\d.]+)\s*LUFS", r.stderr.decode(errors="replace"))
    return float(m[-1]) if m else -99.0


def cuts(path: str, threshold: float = 0.35) -> list[float]:
    """Hard cuts (scene score) — compared with a fixture's known cut times."""
    r = _run([FFMPEG, "-v", "info", "-i", path, "-vf", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
             timeout=300)
    return [round(float(x), 2) for x in re.findall(r"pts_time:([\d.]+)", r.stderr.decode(errors="replace"))]
