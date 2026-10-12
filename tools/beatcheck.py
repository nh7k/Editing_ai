"""How well a rendered video moves WITH its music — measured on the file only (independent of the app's plan).

  python tools/beatcheck.py out.mp4 [plain.mp4]

- beats: librosa beat tracking on the video's own audio track (ISC licence, already a dependency)
- visual accents: peaks of the frame-to-frame change (cuts, zoom punches, flashes, shakes all spike it), at the
  video's frame rate on small grey frames
- hit rate: share of beats with an accent within ±70 ms; on-beat share: share of accents that sit on a beat
- with a plain render (same cut/song, no effects) the extra accents the edit added are measured too
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

W, H = 96, 96


def frames(path: str) -> tuple[np.ndarray, float]:
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                      "stream=avg_frame_rate", "-of", "json", path], capture_output=True).stdout)
    n, _, d = info["streams"][0]["avg_frame_rate"].partition("/")
    fps = float(n) / float(d or 1)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={W}:{H},format=gray", "-f", "rawvideo",
                          "-"], capture_output=True).stdout
    arr = np.frombuffer(raw, dtype=np.uint8)
    return arr[: len(arr) // (W * H) * W * H].reshape(-1, H, W).astype(float), fps


def accents(path: str) -> tuple[np.ndarray, np.ndarray, float]:
    f, fps = frames(path)
    d = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))
    t = (np.arange(len(d)) + 1) / fps
    # a peak: a local maximum clearly above the running median (the footage's own motion)
    med = np.array([np.median(d[max(0, i - 15):i + 16]) for i in range(len(d))])
    peaks = [i for i in range(1, len(d) - 1) if d[i] >= d[i - 1] and d[i] >= d[i + 1] and d[i] > med[i] * 1.8 + 1.5]
    return t[peaks], d, fps


def beats(path: str) -> tuple[float, np.ndarray]:
    import librosa

    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "22050", "-f", "s16le", "-"],
                         capture_output=True).stdout  # mp4 audio: decoded by FFmpeg (libsndfile can't read mp4)
    y, sr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0, 22050
    tempo, b = librosa.beat.beat_track(y=y, sr=sr, units="time")
    return float(np.atleast_1d(tempo)[0]), np.asarray(b)


def kicks(path: str) -> np.ndarray:
    """Kick-drum onsets straight from the audio (no beat tracker): rises of the 40-120 Hz energy, 10 ms hops,
    adaptive threshold, ≥ 0.2 s apart. Independent of the app's beat grid AND of librosa's beat phase (a tracker
    can sit on the off-beat; measured on 3 of 8 songs)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    y = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    hop, n = 80, 512
    fr = np.fft.rfftfreq(n, 1 / 8000)
    band = (fr >= 40) & (fr < 120)
    e = np.array([np.sum(np.abs(np.fft.rfft(y[i:i + n] * np.hanning(n)))[band] ** 2) for i in range(0, len(y) - n, hop)])
    if e.size == 0:
        return np.array([])
    le = np.log10(e + e.max() * 1e-6)
    flux = np.maximum(0, np.diff(le, prepend=le[0]))
    thr = np.median(flux) + 3 * np.median(np.abs(flux - np.median(flux))) + 0.05
    out, last = [], -9.0
    for i in range(1, len(flux) - 1):
        t = i * hop / 8000
        if flux[i] > thr and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1] and t - last >= 0.2:
            out.append(t)
            last = t
    return np.array(out)


def report(path: str, plain: str | None = None) -> dict:
    tempo, bt = beats(path)
    acc, _d, fps = accents(path)
    tol = 0.07
    hit = [b for b in bt if np.any(np.abs(acc - b) <= tol)]
    on = [a for a in acc if np.any(np.abs(bt - a) <= tol)]
    dur = float(json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
                                           path], capture_output=True).stdout)["format"]["duration"])
    # chance level: accents placed at random hit a ±70 ms window this often
    chance = min(1.0, len(acc) * 2 * tol / max(dur, 1e-6))
    out = {"file": Path(path).name, "duration": round(dur, 2), "tempo": round(tempo, 1), "beats": len(bt),
           "accents": len(acc), "beats_hit": f"{len(hit)}/{len(bt)}",
           "hit_rate": round(len(hit) / max(1, len(bt)), 2), "on_beat_share": round(len(on) / max(1, len(acc)), 2),
           "chance_on_beat": round(chance, 2)}
    kk = kicks(path)
    khit = [k for k in kk if np.any(np.abs(acc - k) <= tol)]
    out.update(kicks=len(kk), kicks_hit=f"{len(khit)}/{len(kk)}", kick_hit_rate=round(len(khit) / max(1, len(kk)), 2))
    if plain:
        pacc, _, _ = accents(plain)
        extra = [a for a in acc if not np.any(np.abs(pacc - a) <= 0.05)]
        extra_on = [a for a in extra if np.any(np.abs(bt - a) <= tol)]
        out.update(plain_accents=len(pacc), added_accents=len(extra),
                   added_on_beat=f"{len(extra_on)}/{len(extra)}")
    return out


if __name__ == "__main__":
    print(json.dumps(report(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None), indent=1))
