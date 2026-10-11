"""The production verifier for skill jobs: every skill a message ran is MEASURED on the new video against the
version before it (same moment), never taken from the skill's own notes or the plan's claims.

Each check is one of:
  passed     the measured change is there (with the numbers)
  failed     the skill ran but the video does not show it (with the numbers) — said to the user, never hidden
  not needed the plan did not change for this skill (nothing to do on this footage) — with the skill's reason
  unmeasured no honest measurement exists here (exports, invisible metadata) — said as such, never as "passed"

Before this, a skill job only had a gate (decodes, duration, sound present). Measurements are deliberately coarse
and direction-only (a warm grade must make the picture warmer than before, a mute must make it quiet), so they hold
on any footage, not only on test clips.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .ffmpeg_utils import extract_frame, ffmpeg_bin, probe
from .plan import EditPlan

COLOR_UP = {"warm": "warmth", "brightness": "luma", "contrast": "contrast", "saturation": "sat",
            "brighten_to_white": "luma"}
COLOR_DOWN = {"cool": "warmth", "grayscale": "sat"}
VISUAL_ANY = {"blur", "blur_box_censor", "pixelate_censor", "sepia", "cinematic_look", "teal_orange", "vintage_faded",
              "vhs_retro", "glitch", "rgb_split", "film_grain", "light_leak", "flash", "fade_black", "fade_white",
              "zoom_in", "zoom_out", "ken_burns", "pan", "shake", "punch_in", "tilt", "rotate_flip", "mirror_effect",
              "crop", "letterbox", "color_pop", "restore_normal", "text_overlay", "title_card", "lower_third",
              "text_pop_in", "text_slide", "text_typewriter", "text_glow_neon", "caption_style", "karaoke_captions",
              "watermark_logo", "sticker_lottie", "progress_bar", "countdown_timer", "shape_highlight",
              "picture_in_picture", "split_screen", "blur_background_fill", "auto_reframe", "stabilize",
              "auto_enhance", "white_screen_card", "intro_outro", "insert_broll", "vignette", "sharpen", "denoise"}
SHORTER = {"trim", "delete_segment", "remove_silence", "remove_fillers", "jump_cut_tighten", "speed_up",
           "extract_highlights", "montage_builder"}
LONGER = {"slow_motion", "freeze_frame", "loop_boomerang"}
AUDIO_QUIETER = {"mute"}
AUDIO_ANY = {"volume", "add_music", "replace_audio", "duck_music", "normalize_loudness", "audio_fade", "voice_clarity",
             "echo_reverb", "sfx_whoosh", "denoise"}
ASPECT = {"aspect_9_16": 9 / 16, "aspect_16_9": 16 / 9, "aspect_1_1": 1.0, "aspect_4_5": 4 / 5}
UNMEASURED = {"srt_export", "thumbnail", "extract_audio", "export_preset", "split", "scene_detect", "merge_clips",
              "reorder_clips", "hook_first", "fit_to_duration", "beat_sync", "j_cut", "l_cut", "auto_captions",
              "crossfade", "slide", "wipe", "iris_circle", "whip_pan", "zoom_transition", "glitch_transition",
              "reverse", "speed_ramp"}


@dataclass
class Check:
    skill: str
    status: str  # passed | failed | not_needed | unmeasured
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _frame(p: Path, t: float) -> np.ndarray:
    # one fixed small size for both versions, so a changed canvas still compares like with like
    return extract_frame(p, t, 192, 192).astype(float)


def _stats(f: np.ndarray) -> dict[str, float]:
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return {"warmth": float((r - b).mean()), "luma": float(lum.mean()), "contrast": float(lum.std()),
            "sat": float((f.max(axis=2) - f.min(axis=2)).mean())}


def _rms_db(p: Path, t: float, length: float = 1.0) -> float:
    raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-t", f"{length:.3f}", "-i", str(p),
                          "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True, timeout=60).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(float) / 32768.0
    return float(20 * np.log10(max(1e-9, np.sqrt(np.mean(x ** 2))))) if len(x) else -120.0


def _when(span: list[float] | tuple[float, float] | None, dur_a: float, dur_b: float) -> float:
    """The moment to compare: the middle of what the skill changed (or of the video), inside both versions."""
    end = min(dur_a, dur_b)
    t = (float(span[0]) + float(span[1])) / 2 if span else end / 2
    return min(max(0.2, t), max(0.2, end - 0.25))


def verify(before_plan: EditPlan, before_video: Path | None, after_plan: EditPlan, after_video: Path,
           applied: list[dict[str, Any]]) -> list[Check]:
    """Measure every applied skill; independent of the skills' notes."""
    out: list[Check] = []
    if before_video is None or not Path(before_video).exists():
        return [Check(a["skill"], "unmeasured", "no earlier video to compare with") for a in applied]
    da, db_ = probe(before_video).duration, probe(after_video).duration
    same_plan = before_plan.to_json() == after_plan.to_json()
    for a in applied:
        sid, span = a["skill"], a.get("span")
        try:
            out.append(_one(sid, span, before_video, after_video, da, db_, same_plan, a.get("notes") or []))
        except Exception as exc:  # noqa: BLE001 — a measuring problem is reported, never a crash of the edit
            out.append(Check(sid, "unmeasured", f"could not measure ({str(exc)[:80]})"))
    return out


def _one(sid: str, span: Any, va: Path, vb: Path, da: float, db_: float, same_plan: bool, notes: list[str]) -> Check:
    if same_plan:
        return Check(sid, "not_needed", "; ".join(notes)[:160] or "the edit already had this — nothing changed")
    if sid in ASPECT:
        info = probe(vb)
        ratio = info.width / max(1, info.height)
        ok = abs(ratio - ASPECT[sid]) < 0.02
        return Check(sid, "passed" if ok else "failed", f"video is {info.width}x{info.height} (ratio {ratio:.3f})")
    if sid in SHORTER or sid in LONGER:
        ok = db_ < da - 0.1 if sid in SHORTER else db_ > da + 0.1
        return Check(sid, "passed" if ok else "failed", f"length {da:.2f}s → {db_:.2f}s")
    t = _when(span, da, db_)
    if sid in AUDIO_QUIETER or sid in AUDIO_ANY:
        ra, rb = _rms_db(va, t), _rms_db(vb, t)
        if sid in AUDIO_QUIETER:
            ok = rb < min(-45.0, ra - 10)
        else:
            ok = abs(rb - ra) > 0.8 or (ra < -60 and rb > -50)
        if sid not in VISUAL_ANY or ok:
            return Check(sid, "passed" if ok else "failed", f"sound at {t:.1f}s: {ra:.1f} → {rb:.1f} dB")
    fa, fb = _frame(va, t), _frame(vb, t)
    sa, sb = _stats(fa), _stats(fb)
    if sid in COLOR_UP or sid in COLOR_DOWN:
        key = COLOR_UP.get(sid) or COLOR_DOWN[sid]
        delta = sb[key] - sa[key]
        ok = delta > 2.0 if sid in COLOR_UP else delta < -2.0
        return Check(sid, "passed" if ok else "failed", f"{key} at {t:.1f}s: {sa[key]:.1f} → {sb[key]:.1f}")
    if sid in VISUAL_ANY:
        d = float(np.abs(fa - fb).mean())
        return Check(sid, "passed" if d > 1.5 else "failed", f"picture at {t:.1f}s changed by {d:.1f} (needs > 1.5)")
    if sid in UNMEASURED:
        return Check(sid, "unmeasured", "no picture/sound measurement for this kind of change")
    d = float(np.abs(fa - fb).mean())
    return Check(sid, "passed" if d > 1.5 else "unmeasured", f"picture at {t:.1f}s changed by {d:.1f}")


def summary(checks: list[Check]) -> tuple[list[str], list[str]]:
    """(lines for the answer card, warnings) — failures are always warnings."""
    lines, warns = [], []
    for c in checks:
        mark = {"passed": "✓", "failed": "✗", "not_needed": "–", "unmeasured": "?"}[c.status]
        lines.append(f"{mark} {c.skill}: {c.detail}")
        if c.status == "failed":
            warns.append(f"{c.skill} ran but the video does not show it ({c.detail})")
    return lines, warns
