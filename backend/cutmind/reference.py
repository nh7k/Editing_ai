"""Edit like this one: measure a finished edit someone else made and turn it into a style recipe for raw footage.

Measured on CPU from the reference video (no AI service):
* cuts — PySceneDetect shot changes → shot lengths (median, spread), cuts per second
* rhythm — beats of the reference's own soundtrack (librosa); share of cuts that land on a beat
* colour — every frame at 4 fps: saturation (grey frames = black & white share), warm/cool balance, contrast
* flashes — very short jumps to near-white frames
* shape — aspect ratio and length

The recipe becomes intent fields, each with the measured number as its reason (shown in "Why these edits"). The
reference's soundtrack is stored as a project song, so the new edit can cut to the same music.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .ffmpeg_utils import extract_audio_wav, ffmpeg_bin, probe

RECIPE_VERSION = 1


@dataclass
class StyleRecipe:
    name: str = ""
    duration: float = 0.0
    aspect: str = "16:9"
    cuts: list[float] = field(default_factory=list)
    shot_median: float = 0.0
    shot_p25: float = 0.0
    shot_p75: float = 0.0
    on_beat: float = 0.0          # share of cuts close to a beat of its soundtrack (after removing the typical lag)
    beat_z: float = 0.0           # how far above chance that share is (>= 2: really cut to the beat)
    tempo: float = 0.0
    bw_share: float = 0.0         # share of time that is (almost) grey
    saturation: float = 0.0       # mean saturation of the colour frames, 0..1
    warmth: float = 0.0           # (R - B) / 255 of the colour frames
    contrast: float = 0.0         # mean luma std / 255
    flashes: int = 0
    song: str | None = None       # the reference's soundtrack stored as a project song
    version: int = RECIPE_VERSION

    def summary(self) -> list[str]:
        s = [f"{self.duration:.0f}s {self.aspect}", f"{len(self.cuts) + 1} shots, median {self.shot_median:.2f}s"]
        if self.beat_z >= 2:
            s.append(f"{self.on_beat:.0%} of cuts on the beat ({self.tempo:.0f} bpm)")
        if self.bw_share > 0.05:
            s.append(f"{self.bw_share:.0%} black & white")
        s.append("warm" if self.warmth > 0.06 else "cool" if self.warmth < -0.04 else "neutral colour")
        if self.flashes:
            s.append(f"{self.flashes} white flash(es)")
        return s


def _frames_stats(path: Path, fps: float = 4.0) -> dict[str, Any]:
    w, h = 96, 54
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={w}:{h}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=600).stdout
    n = len(raw) // (w * h * 3)
    if n == 0:
        return {"bw": 0.0, "sat": 0.0, "warm": 0.0, "contrast": 0.0, "flashes": 0}
    f = np.frombuffer(raw[: n * w * h * 3], np.uint8).reshape(n, h, w, 3).astype(np.float32)
    mx, mn = f.max(axis=3), f.min(axis=3)
    sat = ((mx - mn) / np.maximum(mx, 1)).mean(axis=(1, 2))           # per frame
    luma = f.mean(axis=3)
    grey = sat < 0.07
    colour = ~grey
    warm = float(((f[..., 0] - f[..., 2]).mean(axis=(1, 2))[colour]).mean() / 255) if colour.any() else 0.0
    ymean = luma.mean(axis=(1, 2))
    # a flash: a frame much brighter than both neighbours' average, near white
    flashes = int(sum(1 for i in range(1, n - 1) if ymean[i] > 215 and ymean[i] - (ymean[i - 1] + ymean[i + 1]) / 2 > 45))
    return {"bw": float(grey.mean()), "sat": float(sat[colour].mean()) if colour.any() else 0.0, "warm": warm,
            "contrast": float(luma.std(axis=(1, 2)).mean() / 255), "flashes": flashes}


def analyze_reference(video: Path, work: Path) -> StyleRecipe:
    from .agents.analyzer import beat_grid, detect_scenes

    info = probe(video)
    r = StyleRecipe(name=video.name, duration=round(info.duration, 2))
    ratio = info.width / max(1, info.height)
    r.aspect = "9:16" if ratio < 0.8 else "1:1" if ratio < 1.25 else "16:9"
    r.cuts = [c for c in detect_scenes(video) if 0.1 < c < info.duration - 0.1]
    edges = [0.0, *r.cuts, info.duration]
    shots = np.diff(edges)
    r.shot_median = round(float(np.median(shots)), 3)
    r.shot_p25, r.shot_p75 = (round(float(x), 3) for x in np.percentile(shots, [25, 75]))
    st = _frames_stats(video)
    r.bw_share, r.saturation, r.warmth = round(st["bw"], 3), round(st["sat"], 3), round(st["warm"], 3)
    r.contrast, r.flashes = round(st["contrast"], 3), st["flashes"]
    if info.has_audio:
        work.mkdir(parents=True, exist_ok=True)
        tempo, beats = beat_grid(extract_audio_wav(video, work / "ref.wav", sr=22050))
        r.tempo = round(tempo or 0.0, 1)
        if len(beats) > 2 and r.cuts:
            period = float(np.median(np.diff(beats)))
            inside = [c for c in r.cuts if beats[0] - period <= c <= beats[-1] + period]
            if len(inside) >= 3:
                # shot detection reports the first new frame and trackers lag: remove the typical lag, then count
                # cuts close to a beat (random cuts score ~0.3 here, cut-to-the-beat edits ~0.8+)
                off = [min((c - b for b in beats), key=abs) for c in inside]
                lag = float(np.median(off))
                tol = max(0.08, 0.16 * period)
                r.on_beat = round(sum(1 for o in off if abs(o - lag) <= tol) / len(inside), 3)
                chance = min(0.95, 2 * tol / period + 0.07)  # random cuts (+ the lag fit) land this often
                r.beat_z = round((r.on_beat - chance) / float(np.sqrt(chance * (1 - chance) / len(inside))), 2)
    return r


def save_recipe(r: StyleRecipe, path: Path) -> None:
    path.write_text(json.dumps(asdict(r)), encoding="utf-8")


def load_recipe(path: Path) -> StyleRecipe | None:
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return StyleRecipe(**d) if d.get("version") == RECIPE_VERSION else None
    except (ValueError, TypeError):
        return None


def apply_reference(it: Any, r: StyleRecipe, explicit: set[str]) -> tuple[Any, list[dict[str, str]]]:
    """Intent with the reference's style (fields the user set themselves are kept). Returns (intent, decisions)."""
    upd: dict[str, Any] = {}
    why: list[dict[str, str]] = []

    def take(fld: str, value: Any, reason: str) -> None:
        if fld in explicit:
            return
        upd[fld] = value
        why.append({"decision": f"{fld} = {value}", "where": "whole edit", "reason": f"like the reference: {reason}",
                    "skill": "reference_style"})

    take("aspect_ratio", r.aspect, f"it is {r.aspect}")
    take("target_duration", round(min(r.duration, 600.0), 1), f"it is {r.duration:.1f}s long")
    if r.shot_median < 1.8:
        take("fast_cuts", True, f"median shot {r.shot_median:.2f}s")
        take("cut_length", max(0.3, round(r.shot_median, 2)), f"median shot {r.shot_median:.2f}s "
             f"(middle half {r.shot_p25:.2f}-{r.shot_p75:.2f}s)")
    if r.beat_z >= 2:
        take("beat_sync", True, f"{r.on_beat:.0%} of its cuts land on the beat (far above chance)")
        take("music", True, "it is cut to music")
    if r.bw_share >= 0.85:
        take("color_preset", "bw", f"{r.bw_share:.0%} of it is black & white")
    elif r.bw_share >= 0.08:
        take("color_pass", True, f"{r.bw_share:.0%} of it is black & white, the rest colour")
    elif r.saturation > 0.42:
        take("color_preset", "vivid", f"strong colours (saturation {r.saturation:.2f})")
    elif r.warmth > 0.07:
        take("color_preset", "warm", f"warm colours (R-B {r.warmth:+.2f})")
    elif r.warmth < -0.05:
        take("color_preset", "cool", f"cool colours (R-B {r.warmth:+.2f})")
    if r.flashes:
        take("flash_accents", min(4, r.flashes), f"{r.flashes} white flash(es)")
    take("transition", None, "hard cuts")
    data = {**it.model_dump(), **upd}
    data["inferred_fields"] = sorted({*it.inferred_fields, *upd})
    return type(it).model_validate(data), why


def style_profile(r: StyleRecipe) -> dict[str, Any]:
    """The reference's numeric style traits in the SAME shape as a recipe (recipes.yaml / recipes.schema.json), so the
    Director can apply them like any recipe. Only numbers are taken — never the reference's content."""
    lo = round(max(0.2, r.shot_p25 or r.shot_median * 0.7), 2)
    hi = round(max(lo, r.shot_p75 or r.shot_median * 1.4), 2)
    look = ("bw" if r.bw_share > 0.6 else "warm" if r.warmth > 0.06 else "cool" if r.warmth < -0.04
            else "vivid" if r.saturation > 0.45 else "cinematic" if r.contrast > 0.22 else "none")
    tempo = round(r.tempo) if r.tempo else 0
    return {
        "id": "reference", "name": f"Like {r.name or 'the reference'}", "genre": "montage",
        "shot_len": [lo, hi], "hook": "the reference's opening pace", "cut_on": "beat" if r.beat_z >= 2 else "mixed",
        "transitions": ["none"], "look": look, "captions": "off",
        "zoom_per_min": 0, "speed_ramps": 0, "bpm": [max(40, tempo - 10), min(200, tempo + 10)] if tempo else [80, 120],
        "duck_db": 12, "aspect": r.aspect if r.aspect in ("9:16", "16:9", "1:1") else "16:9",
        "duration": round(max(3.0, min(600.0, r.duration)), 1), "lufs": -14,
        "avoid": ["copying the reference's footage, text or logo"],
        "measured": {"shots": len(r.cuts) + 1, "shot_median": r.shot_median, "on_beat": r.on_beat, "beat_z": r.beat_z,
                     "bw_share": r.bw_share, "saturation": r.saturation, "warmth": r.warmth, "contrast": r.contrast,
                     "flashes": r.flashes},
    }
