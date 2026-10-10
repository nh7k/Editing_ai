"""Independent verification helpers for end-to-end tests (real ffprobe / frame extraction)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from cutmind.ffmpeg_utils import decode_check, detect_silence, measure_loudness, probe, run_ffmpeg
from cutmind.plan import EditPlan
from cutmind.renderer import render

ROOT = Path(__file__).resolve().parents[2]
FRAMES_DIR = ROOT / "docs" / "test_frames"
RESULTS_DIR = ROOT / "tests" / "results"


def wait_job(client: Any, job_id: str, timeout: float = 900) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        r = client.get(f"/jobs/{job_id}")
        assert r.status_code == 200
        job = r.json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(1.0)
    raise TimeoutError(job_id)


def download_output(client: Any, pid: str, dest: Path) -> Path:
    r = client.get(f"/projects/{pid}/output")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "video/mp4"
    dest.write_bytes(r.content)
    return dest


def media_facts(path: Path) -> dict[str, Any]:
    info = probe(path)
    ok, err = decode_check(path)
    loud = measure_loudness(path) if info.has_audio else {}
    return {"duration": round(info.duration, 3), "width": info.width, "height": info.height, "fps": info.fps,
            "aspect": f"{info.width}:{info.height}", "has_audio": info.has_audio, "video_codec": info.video_codec,
            "audio_codec": info.audio_codec, "size_bytes": info.size_bytes, "plays": ok, "decode_errors": err[:200],
            "lufs": loud.get("lufs"), "max_volume": loud.get("max_volume"), "mean_volume": loud.get("mean_volume")}


def rerender_variant(plan: EditPlan, sources: dict[str, Path], work: Path, music_dir: Path, **changes: Any) -> Path:
    """Render the same plan with some sections changed (e.g. no text, neutral colour) for A/B pixel checks."""
    data = plan.to_json()
    data.update(changes)
    variant = EditPlan.model_validate(data)
    out = work / "variant.mp4"
    return render(variant, sources, work / "w", out, music_dir)


def band_change(a: np.ndarray, b: np.ndarray, top: float, bottom: float) -> float:
    """Share of pixels that changed in the centred caption area (captions are centred horizontally)."""
    h, w = a.shape[:2]
    band = (slice(int(h * top), int(h * bottom)), slice(int(w * 0.3), int(w * 0.7)))
    return float((np.abs(a[band].astype(int) - b[band].astype(int)).max(axis=2) > 40).mean())


def center_stats(frame: np.ndarray) -> dict[str, float]:
    h, w = frame.shape[:2]
    c = frame[int(h * 0.3): int(h * 0.6), int(w * 0.2): int(w * 0.8)].astype(np.float32)
    return {"r": float(c[..., 0].mean()), "g": float(c[..., 1].mean()), "b": float(c[..., 2].mean()),
            "chroma": float((c.max(axis=2) - c.min(axis=2)).mean()),
            "luma": float((0.299 * c[..., 0] + 0.587 * c[..., 1] + 0.114 * c[..., 2]).mean())}


def long_silences(path: Path, min_dur: float = 1.0) -> list[tuple[float, float]]:
    info = probe(path)
    return [(s, e) for s, e in detect_silence(path, -35.0, min_dur) if s > 0.6 and e < info.duration - 0.6]


def contact_sheet(path: Path, name: str, n: int = 6) -> Path:
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    info = probe(path)
    out = FRAMES_DIR / f"{name}.jpg"
    step = max(info.duration / n, 0.1)
    run_ffmpeg(["-i", str(path), "-vf", f"fps=1/{step:.3f},scale=-2:200,tile={n}x1", "-frames:v", "1", "-q:v", "4", str(out)])
    return out


def save_results(name: str, rows: list[dict[str, Any]]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{name}.json"
    out.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    return out
