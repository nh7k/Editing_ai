"""Measurements for the Tier 1 render tests (test_tier1.py). Each check gets the run (plan, output, media) and the
plain render of the same input, and returns (ok, detail). Measurements only — nothing here trusts the plan."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from cutmind.ffmpeg_utils import detect_silence, extract_frame, ffmpeg_bin, probe
from cutmind.plan import EditPlan


@dataclass
class Run:
    plan: EditPlan
    out: Path
    applied: list[Any]
    plain: Path
    plain_plan: EditPlan
    media: dict[str, Path]
    params: dict[str, Any] = field(default_factory=dict)
    words: Any = None  # callable: path -> [(word, start, end)]


def frame(p: Path, t: float) -> np.ndarray:
    return extract_frame(p, t).astype(float)


def diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a - b).mean())


def dur(p: Path) -> float:
    return probe(p).duration


def pcm(p: Path, start: float, length: float, rate: int = 16000) -> np.ndarray:
    raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-t", f"{length:.3f}",
                          "-i", str(p), "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
                         capture_output=True, timeout=60).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(float) / 32768.0


def peak_hz(p: Path, start: float, length: float) -> float:
    """The loudest frequency in the window (the test clips are pure tones: 440 / 880 / 660 Hz)."""
    x = pcm(p, start, length)
    if len(x) < 256:
        return 0.0
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1 / 16000)[int(np.argmax(spec[5:])) + 5])


def rms_db(p: Path, start: float, length: float) -> float:
    x = pcm(p, start, length)
    return float(20 * np.log10(max(1e-9, np.sqrt(np.mean(x ** 2))))) if len(x) else -120.0


def edges(f: np.ndarray) -> float:
    g = f.mean(axis=2)
    return float(np.abs(np.diff(g, axis=0)).mean() + np.abs(np.diff(g, axis=1)).mean())


def near(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


# ---- A. cutting ----------------------------------------------------------------------------------------------
def trim_range(r: Run) -> tuple[bool, str]:
    a, b = r.params["start"], r.params["end"]
    d = dur(r.out)
    first = diff(frame(r.out, 0.2), frame(r.plain, a + 0.2))
    return near(d, b - a, 0.12) and first < 6, f"{d:.2f}s (want {b - a:.2f}); first frame vs plain@{a + 0.2:.1f}s diff {first:.1f}"


def split_invisible(r: Run) -> tuple[bool, str]:
    at = r.params["at"]
    d, d0 = dur(r.out), dur(r.plain)
    n, n0 = len(r.plan.clips), len(r.plain_plan.clips)
    fr = max(diff(frame(r.out, t), frame(r.plain, t)) for t in (at - 0.3, at + 0.1, at + 0.4))
    dip = rms_db(r.plain, at - 0.05, 0.1) - rms_db(r.out, at - 0.05, 0.1)
    ok = near(d, d0, 0.06) and n == n0 + 1 and fr < 4 and abs(dip) < 1.5
    return ok, f"{n0}→{n} shots, {d0:.2f}→{d:.2f}s, frames diff {fr:.1f}, sound at the split {dip:+.1f} dB vs plain"


def delete_range(r: Run) -> tuple[bool, str]:
    a, b = r.params["start"], r.params["end"]
    d, d0 = dur(r.out), dur(r.plain)
    after = diff(frame(r.out, a + 0.4), frame(r.plain, b + 0.4))
    return near(d, d0 - (b - a), 0.12) and after < 6, f"{d0:.2f}→{d:.2f}s (want −{b - a:.2f}); after-cut frame diff {after:.1f}"


def merged_all(r: Run) -> tuple[bool, str]:
    want = sum(dur(p) for p in r.media["_clips"])
    d = dur(r.out)
    return near(d, want, 0.25), f"{d:.2f}s for clips totalling {want:.2f}s"


def order_swapped(r: Run) -> tuple[bool, str]:
    second_start = r.plain_plan.timeline()[1].start
    a = diff(frame(r.out, 0.3), frame(r.plain, second_start + 0.3))
    b = diff(frame(r.out, 0.3), frame(r.plain, 0.3))
    return a < 6 and b > 10, f"first frame vs old shot 2: {a:.1f}, vs old shot 1: {b:.1f}"


def shorter_no_long_silence(r: Run) -> tuple[bool, str]:
    d, d0 = dur(r.out), dur(r.plain)
    p = r.applied[0].params
    longest = max((e - s for s, e in detect_silence(r.out, noise_db=p["threshold_db"], min_dur=0.2)), default=0.0)
    limit = p["min_gap"] + 0.25
    return d < d0 - 0.5 and longest <= limit, f"{d0:.2f}→{d:.2f}s, longest pause left {longest:.2f}s (≤ {limit:.2f})"


def filler_gone(r: Run) -> tuple[bool, str]:
    before = [w for w, _s, _e in r.words(r.plain)]
    after = [w for w, _s, _e in r.words(r.out)]
    fill = re.compile(r"^(um+|uh+|erm|hmm+|aa+)$")
    b = [w for w in before if fill.match(w.lower().strip(".,!?"))]
    a = [w for w in after if fill.match(w.lower().strip(".,!?"))]
    return bool(b) and not a and dur(r.out) < dur(r.plain), f"fillers before {b}, after {a}; {dur(r.plain):.2f}→{dur(r.out):.2f}s"


def max_gap_respected(r: Run) -> tuple[bool, str]:
    ws = r.words(r.out)
    gaps = [b[1] - a[2] for a, b in zip(ws, ws[1:], strict=False)]
    mg = max(gaps, default=0.0)
    lim = r.params.get("max_gap", 0.3) + 0.35
    return bool(ws) and mg <= lim and dur(r.out) < dur(r.plain), f"longest gap between words {mg:.2f}s (≤ {lim:.2f}); " \
                                                                  f"{dur(r.plain):.2f}→{dur(r.out):.2f}s"


def duration_target(r: Run) -> tuple[bool, str]:
    d = dur(r.out)
    return near(d, r.params["target_sec"], 0.15), f"{d:.2f}s for {r.params['target_sec']}s"


def highlights_scored(r: Run) -> tuple[bool, str]:
    d = dur(r.out)
    want = r.params["count"] * r.params["length"]
    return near(d, want, 0.4) and len(r.plan.clips) == r.params["count"], \
        f"{len(r.plan.clips)} moments, {d:.2f}s (want {want:.2f}); {r.applied[0].notes[:1]}"


def hook_starts(r: Run) -> tuple[bool, str]:
    first = r.plan.ordered_clips()[0]
    src = r.media[first.source]
    a = diff(frame(r.out, 0.2), frame(src, first.in_ + 0.2)[: frame(r.out, 0.2).shape[0]]) \
        if frame(src, first.in_ + 0.2).shape == frame(r.out, 0.2).shape else None
    d, d0 = dur(r.out), dur(r.plain)
    hook = r.params["hook_len"]
    # the opening shot is the scored window (from the plan) and the rest plays after it (picture = plain shifted)
    rest = diff(frame(r.out, hook + 0.5), frame(r.plain, 0.5))
    return near(d, d0 + hook, 0.15) and rest < 6, f"{d0:.2f}→{d:.2f}s (+{hook}), opens with {first.source} " \
                                                    f"{first.in_:.1f}-{first.out:.1f}s; rest vs plain diff {rest:.1f}" + \
        (f"; first frame vs source {a:.1f}" if a is not None else "")


def many_short_shots(r: Run) -> tuple[bool, str]:
    sl, tot = r.params["shot_len"], r.params["total"]
    lens = [c.source_duration for c in r.plan.clips]
    d = dur(r.out)
    srcs = {c.source for c in r.plan.clips}
    ok = near(d, tot, 0.6) and all(near(x, sl, 0.26) for x in lens) and len(srcs) >= 2
    return ok, f"{len(lens)} shots of {sorted(set(round(x, 2) for x in lens))}s from {len(srcs)} clips, {d:.2f}s"


def audio_leads(r: Run) -> tuple[bool, str]:
    cut = r.plain_plan.timeline()[1].start
    lead = r.params["lead_sec"]
    f_before = peak_hz(r.out, cut - lead + 0.1, lead - 0.2)
    f_plain = peak_hz(r.plain, cut - lead + 0.1, lead - 0.2)
    pic = diff(frame(r.out, cut - 0.15), frame(r.plain, cut - 0.15))
    return near(f_before, 880, 15) and near(f_plain, 440, 15) and pic < 4, \
        f"sound before the cut {f_before:.0f} Hz (plain {f_plain:.0f} Hz: the next shot is 880 Hz); picture unchanged ({pic:.1f})"


def audio_trails(r: Run) -> tuple[bool, str]:
    cut = r.plain_plan.timeline()[1].start
    tail = r.params["tail_sec"]
    f_after = peak_hz(r.out, cut + 0.1, tail - 0.2)
    f_plain = peak_hz(r.plain, cut + 0.1, tail - 0.2)
    pic = diff(frame(r.out, cut + 0.15), frame(r.plain, cut + 0.15))
    return near(f_after, 440, 15) and near(f_plain, 880, 15) and pic < 4, \
        f"sound after the cut {f_after:.0f} Hz (plain {f_plain:.0f} Hz: this shot is 440 Hz); picture unchanged ({pic:.1f})"


def broll_picture_main_audio(r: Run) -> tuple[bool, str]:
    s, ln = r.params["start"], r.params["len"]
    mid = s + ln / 2
    changed = diff(frame(r.out, mid), frame(r.plain, mid))
    outside = diff(frame(r.out, s + ln + 0.4), frame(r.plain, s + ln + 0.4))
    f_main = peak_hz(r.out, s + 0.1, ln - 0.2)
    f_plain = peak_hz(r.plain, s + 0.1, ln - 0.2)
    return changed > 15 and outside < 4 and near(f_main, f_plain, 15), \
        f"picture changed {changed:.1f} inside, {outside:.1f} after; sound {f_main:.0f} Hz (plain {f_plain:.0f} Hz)"


def card_then_video(r: Run) -> tuple[bool, str]:
    d, d0 = dur(r.out), dur(r.plain)
    cd = r.params["duration"]
    f = frame(r.out, cd / 2)
    save_frame(r, cd / 2, f"card_{r.applied[0].skill}")
    h, w = f.shape[:2]
    centre = f[int(h * 0.35):int(h * 0.65), int(w * 0.1):int(w * 0.9)].mean(axis=2)
    text_px = float((centre > 200).mean())
    after = diff(frame(r.out, cd + 0.5), frame(r.plain, 0.5))
    return near(d, d0 + cd, 0.12) and text_px > 0.004 and after < 6, \
        f"{d0:.2f}→{d:.2f}s (+{cd}); text pixels in the card {text_px:.1%}; video after the card diff {after:.1f}"


# ---- G. layout ----------------------------------------------------------------------------------------------
RATIOS = {"aspect_9_16": (9, 16), "aspect_1_1": (1, 1), "aspect_16_9": (16, 9), "aspect_4_5": (4, 5)}


def aspect_exact(r: Run) -> tuple[bool, str]:
    info = probe(r.out)
    a, b = RATIOS[r.applied[0].skill]
    f = frame(r.out, 1.0)
    content = float(f.std())
    return abs(info.width / info.height - a / b) < 0.01 and info.width % 2 == 0 and info.height % 2 == 0 and content > 10, \
        f"{info.width}x{info.height} for {a}:{b}; picture std {content:.1f}"


def blurred_sides(r: Run) -> tuple[bool, str]:
    """Wide test clips on a 16:9 canvas don't need filling: test on a 9:16 canvas (set by the test)."""
    f = frame(r.out, 1.0)
    h, w = f.shape[:2]
    top = f[: int(h * 0.15)]
    mid = f[int(h * 0.4): int(h * 0.6)]
    # blurred = picture there (not black) but with far less edge detail than the sharp middle
    return float(top.mean()) > 8 and edges(top) < 0.5 * edges(mid), \
        f"top band mean {top.mean():.1f} (not black), edges top {edges(top):.2f} vs middle {edges(mid):.2f}"


def bars_top_bottom(r: Run) -> tuple[bool, str]:
    f = frame(r.out, 1.0)
    h, w = f.shape[:2]
    want = int(max(0, (h - w / r.params["ratio"]) / 2))
    top, mid = f[: max(1, want - 2)], f[want + 4: h - want - 4]
    return want > 4 and float(top.max()) < 25 and float(mid.std()) > 10, \
        f"bar {want}px: top max {top.max():.0f} (black), middle std {mid.std():.1f}"


def pip_corner(r: Run) -> tuple[bool, str]:
    f, f0 = frame(r.out, 1.5), frame(r.plain, 1.5)
    h, w = f.shape[:2]
    corner = diff(f[int(h * 0.08): int(h * 0.3), int(w * 0.72): int(w * 0.95)],
                  f0[int(h * 0.08): int(h * 0.3), int(w * 0.72): int(w * 0.95)])
    rest = diff(f[int(h * 0.5):, : int(w * 0.5)], f0[int(h * 0.5):, : int(w * 0.5)])
    f_main = peak_hz(r.out, 0.5, 1.5)
    return corner > 15 and rest < 4 and near(f_main, 440, 15), \
        f"top-right corner changed {corner:.1f}, rest {rest:.1f}; sound {f_main:.0f} Hz (the main clip's)"


def two_halves(r: Run) -> tuple[bool, str]:
    f = frame(r.out, 1.0)
    h, w = f.shape[:2]
    a = r.media["T1"]
    b = r.media["T2"]
    fa, fb = frame(a, 1.0), frame(b, 1.0)
    # each half shows its clip: compare colour statistics of each half with the matching source
    la, rb = f[:, : w // 2], f[:, w // 2:]
    da = abs(float(la.mean()) - float(fa.mean())) + abs(float(la.std()) - float(fa.std()))
    db_ = abs(float(rb.mean()) - float(fb.mean())) + abs(float(rb.std()) - float(fb.std()))
    cross = abs(float(la.mean()) - float(fb.mean())) + abs(float(la.std()) - float(fb.std()))
    return da < cross and db_ < 25 and da < 25, f"left vs clip 1 {da:.1f} (vs clip 2 {cross:.1f}); right vs clip 2 {db_:.1f}"


def rotated(r: Run) -> tuple[bool, str]:
    f, f0 = frame(r.out, 1.0), frame(r.plain, 1.0)
    d = diff(f, f0[::-1, ::-1])
    return d < 8 and diff(f, f0) > 15, f"180°: vs plain turned around {d:.1f} (same), vs plain {diff(f, f0):.1f}"


def cropped_region(r: Run) -> tuple[bool, str]:
    f, f0 = frame(r.out, 1.0), frame(r.plain, 1.0)
    h, w = f0.shape[:2]
    p = r.params
    box = f0[int(p["y"] * h): int((p["y"] + p["h"]) * h), int(p["x"] * w): int((p["x"] + p["w"]) * w)]
    from PIL import Image

    up = np.asarray(Image.fromarray(box.astype(np.uint8)).resize((w, h), Image.BILINEAR)).astype(float)
    d = diff(f, up)
    return d < 12 and diff(f, f0) > 15, f"vs the plain frame's box enlarged {d:.1f}; vs plain {diff(f, f0):.1f}"


def follows_subject(r: Run) -> tuple[bool, str]:
    xs = []
    for t in (0.3, 1.5, 2.7):
        f = frame(r.out, t)
        ys_, xs_ = np.where(f.mean(axis=2) > 200)
        xs.append(float(xs_.mean()) / f.shape[1] if len(xs_) else -1)
    plain = []
    for t in (0.3, 2.7):
        f = frame(r.plain, t)
        _, xs_ = np.where(f.mean(axis=2) > 200)
        plain.append(len(xs_))
    return all(0.38 < x < 0.62 for x in xs) and min(plain) == 0, \
        f"box x (share of width) at 0.3/1.5/2.7s: {[round(x, 2) for x in xs]}; centred crop loses it: {plain}"


# ---- D. colour --------------------------------------------------------------------------------------------------
def sat(f: np.ndarray) -> float:
    return float((f.max(axis=2) - f.min(axis=2)).mean())


def luma(f: np.ndarray) -> float:
    return float((0.2126 * f[..., 0] + 0.7152 * f[..., 1] + 0.0722 * f[..., 2]).mean())


def _in_out(r: Run, fn) -> tuple[float, float, float, float]:
    """(value inside the 1-3 s window, plain inside, value outside at 4.5 s, plain outside)."""
    return fn(frame(r.out, 2.0)), fn(frame(r.plain, 2.0)), fn(frame(r.out, 4.5)), fn(frame(r.plain, 4.5))


def grey_in_window(r: Run) -> tuple[bool, str]:
    i, i0, o, o0 = _in_out(r, sat)
    return i < 4 and i0 > 20 and abs(o - o0) < 3, f"saturation inside {i0:.1f}→{i:.1f}, outside {o0:.1f}→{o:.1f}"


def sepia_tone(r: Run) -> tuple[bool, str]:
    f = frame(r.out, 2.0)
    rr, gg, bb = (float(f[..., k].mean()) for k in range(3))
    # hue: red > green > blue everywhere, with the spread of a toned grey (not the test pattern's colours)
    hue_ok = rr > gg > bb
    toned = float(np.abs((f[..., 0] - f[..., 2]) - (rr - bb)).mean())
    return hue_ok and toned < 20, f"R {rr:.0f} > G {gg:.0f} > B {bb:.0f}; R-B spread {toned:.1f} (a tone, not colours)"


def tilted_no_corners(r: Run) -> tuple[bool, str]:
    """Inside 1-3 s the picture is rotated (differs from plain) but no corner is black (it was zoomed to cover);
    outside it is untouched."""
    f, g = frame(r.out, 2.0), frame(r.plain, 2.0)
    i = diff(f, g)
    o = diff(frame(r.out, 4.5), frame(r.plain, 4.5))
    h, w = f.shape[:2]
    corners = [f[:6, :6], f[:6, w - 6:], f[h - 6:, :6], f[h - 6:, w - 6:]]
    darkest = min(float(c.mean()) for c in corners)
    plain_dark = min(float(c.mean()) for c in [g[:6, :6], g[:6, w - 6:], g[h - 6:, :6], g[h - 6:, w - 6:]])
    ok = i > 8 and o < 2 and (darkest > 12 or darkest >= plain_dark - 5)
    return ok, f"picture changed {i:.1f} inside, {o:.1f} outside; darkest corner {darkest:.0f} (plain {plain_dark:.0f})"


def restored_look(r: Run) -> tuple[bool, str]:
    """The setup made 1-3 s black and white; restore takes it off: colour is back inside, outside untouched, and
    inside matches the never-edited source picture (the plain render's own outside frames show the same clip)."""
    i, i0, o, o0 = _in_out(r, sat)
    src = frame(r.media["_clips"][0], 2.0)
    out = frame(r.out, 2.0)
    if src.shape != out.shape:  # the source is bigger than the 360p render: compare at the render's size
        from PIL import Image

        src = np.asarray(Image.fromarray(src.astype(np.uint8)).resize((out.shape[1], out.shape[0]))).astype(float)
    d = diff(out, src)
    return i > i0 + 15 and abs(o - o0) < 3 and d < 12, \
        f"saturation inside {i0:.1f}→{i:.1f} (grey→colour), outside {o0:.1f}→{o:.1f}; vs source {d:.1f}"


def washed_white(r: Run) -> tuple[bool, str]:
    li, li0, lo, lo0 = _in_out(r, luma)
    si, si0, _, _ = _in_out(r, sat)
    return li - li0 > 25 and si < si0 - 10 and abs(lo - lo0) < 2, \
        f"luma inside {li0:.1f}→{li:.1f}, saturation {si0:.1f}→{si:.1f}; outside luma {lo0:.1f}→{lo:.1f}"


def white_card(r: Run) -> tuple[bool, str]:
    at, d = 2.0, float(r.params.get("duration", 1.0))
    grew = dur(r.out) - dur(r.plain)
    mid = frame(r.out, at + d / 2)
    after = diff(frame(r.out, at + d + 0.4), frame(r.plain, at + 0.4))
    before = diff(frame(r.out, at - 0.5), frame(r.plain, at - 0.5))
    return abs(grew - d) < 0.1 and luma(mid) > 235 and sat(mid) < 6 and after < 4 and before < 4, \
        f"+{grew:.2f}s (want {d:g}); card luma {luma(mid):.0f} sat {sat(mid):.1f}; video after it vs plain {after:.1f}, before {before:.1f}"


def luma_up(r: Run) -> tuple[bool, str]:
    i, i0, o, o0 = _in_out(r, luma)
    return i - i0 > 10 and abs(o - o0) < 2, f"luma inside {i0:.1f}→{i:.1f}, outside {o0:.1f}→{o:.1f}"


def contrast_up(r: Run) -> tuple[bool, str]:
    a, b = frame(r.out, 2.0), frame(r.plain, 2.0)
    s1, s0 = float(a.mean(axis=2).std()), float(b.mean(axis=2).std())
    return s1 > s0 * 1.15, f"luma spread {s0:.1f}→{s1:.1f}"


def sat_up(r: Run) -> tuple[bool, str]:
    a, b = sat(frame(r.out, 2.0)), sat(frame(r.plain, 2.0))
    return a > b * 1.2, f"saturation {b:.1f}→{a:.1f}"


def _rb(f: np.ndarray) -> float:
    return float(f[..., 0].mean() - f[..., 2].mean())


def warmer(r: Run) -> tuple[bool, str]:
    a, b = _rb(frame(r.out, 2.0)), _rb(frame(r.plain, 2.0))
    return a - b > 8, f"red minus blue {b:.1f}→{a:.1f}"


def cooler(r: Run) -> tuple[bool, str]:
    a, b = _rb(frame(r.out, 2.0)), _rb(frame(r.plain, 2.0))
    return b - a > 8, f"red minus blue {b:.1f}→{a:.1f}"


LOOK_OF = {"cinematic_look": "cinematic", "teal_orange": "teal_orange", "vintage_faded": "vintage"}


def look_matches(r: Run) -> tuple[bool, str]:
    """The rendered frame equals the look's own maths applied to the plain frame (the LUT is what we claim)."""
    from cutmind.luts import apply_look

    plain = frame(r.plain, 2.0)
    want = apply_look(plain / 255.0, LOOK_OF[r.applied[0].skill]) * 255
    got = frame(r.out, 2.0)
    d_want, d_plain = diff(got, want), diff(got, plain)
    return d_want < 4 and d_plain > 2 * d_want, f"vs the look's maths {d_want:.1f}, vs plain {d_plain:.1f}"


def corners_darker(r: Run) -> tuple[bool, str]:
    def ratio(f: np.ndarray) -> float:
        h, w = f.shape[:2]
        c = f[int(h * .4):int(h * .6), int(w * .4):int(w * .6)].mean()
        k = np.concatenate([f[: h // 8, : w // 8].ravel(), f[-h // 8:, -w // 8:].ravel()]).mean()
        return float(k / max(1, c))
    a, b = ratio(frame(r.out, 2.0)), ratio(frame(r.plain, 2.0))
    return a < b * 0.8, f"corner/centre brightness {b:.2f}→{a:.2f}"


def _hf(f: np.ndarray) -> float:
    g = f.mean(axis=2)
    from scipy.ndimage import uniform_filter

    return float(np.abs(g - uniform_filter(g, 5)).mean())


def noise_up(r: Run) -> tuple[bool, str]:
    a, b = _hf(frame(r.out, 2.0)), _hf(frame(r.plain, 2.0))
    t1 = diff(frame(r.out, 2.0), frame(r.out, 2.0 + 1 / 30))
    t0 = diff(frame(r.plain, 2.0), frame(r.plain, 2.0 + 1 / 30))
    return a > b * 1.2 and t1 > t0 + 1, f"fine detail {b:.2f}→{a:.2f}; frame-to-frame change {t0:.2f}→{t1:.2f} (moving grain)"


def edges_up(r: Run) -> tuple[bool, str]:
    a, b = edges(frame(r.out, 2.0)), edges(frame(r.plain, 2.0))
    return a > b * 1.08, f"edge energy {b:.2f}→{a:.2f}"


def edges_down(r: Run) -> tuple[bool, str]:
    i, i0, o, o0 = _in_out(r, edges)
    return i < i0 * 0.7 and abs(o - o0) < 0.05 * o0 + 0.1, f"edge energy inside {i0:.2f}→{i:.2f}, outside {o0:.2f}→{o:.2f}"


def exposure_towards_mid(r: Run) -> tuple[bool, str]:
    a, b = luma(frame(r.out, 2.0)) / 255, luma(frame(r.plain, 2.0)) / 255
    return b < 0.35 and a > b + 0.05 and abs(a - 0.48) < abs(b - 0.48), f"mean brightness {b:.2f}→{a:.2f} (target 0.48)"


def only_color_kept(r: Run) -> tuple[bool, str]:
    f, f0 = frame(r.out, 2.0), frame(r.plain, 2.0)
    red0 = (f0[..., 0] > 150) & (f0[..., 1] < 90) & (f0[..., 2] < 90)
    other0 = (sat_px := (f0.max(axis=2) - f0.min(axis=2))) > 60
    other0 &= ~red0
    if red0.sum() < 50:
        return False, "the test frame has no red area"
    s = f.max(axis=2) - f.min(axis=2)
    return float(s[red0].mean()) > 60 and float(s[other0].mean()) < 20, \
        f"red area saturation {float(sat_px[red0].mean()):.0f}→{float(s[red0].mean()):.0f}; other colours " \
        f"{float(sat_px[other0].mean()):.0f}→{float(s[other0].mean()):.0f}"


# ---- C. motion and time ----------------------------------------------------------------------------------------
def _zoomed(f: np.ndarray, sc: float) -> np.ndarray:
    from PIL import Image

    h, w = f.shape[:2]
    cw, ch = w / sc, h / sc
    box = (int((w - cw) / 2), int((h - ch) / 2), int((w + cw) / 2), int((h + ch) / 2))
    return np.asarray(Image.fromarray(f.astype(np.uint8)).crop(box).resize((w, h), Image.BILINEAR)).astype(float)


def scale_at(r: Run, t: float, ref: Path | None = None, ref_t: float | None = None) -> float:
    """The zoom of the output frame at t against the plain frame (best centre zoom 1.00-1.70)."""
    f = frame(r.out, t)
    g = frame(ref or r.plain, t if ref_t is None else ref_t)
    best = min(np.arange(1.0, 1.71, 0.02), key=lambda sc: diff(f, _zoomed(g, sc)))
    return float(best)


def scale_increases(r: Run) -> tuple[bool, str]:
    a, b, out = scale_at(r, 1.05), scale_at(r, 2.9), scale_at(r, 4.5)
    want = 1 + r.params["amount"]
    return a < 1.07 and abs(b - want) <= 0.06 and out < 1.03, f"zoom at 1.05s {a:.2f}, 2.9s {b:.2f} (want ~{want:.2f}), after {out:.2f}"


def scale_decreases(r: Run) -> tuple[bool, str]:
    a, b = scale_at(r, 1.1), scale_at(r, 2.95)
    want = 1 + r.params["amount"]
    return abs(a - want) <= 0.07 and b < 1.07, f"zoom at 1.1s {a:.2f} (want ~{want:.2f}), at 2.95s {b:.2f}"


def punch_at_times(r: Run) -> tuple[bool, str]:
    peak, before, after = scale_at(r, 2.12), scale_at(r, 1.5), scale_at(r, 3.5)
    return peak > 1.12 and before < 1.03 and after < 1.03, f"zoom before {before:.2f}, at the punch {peak:.2f}, after {after:.2f}"


def _pan_x(r: Run, t: float) -> int:
    f, g = frame(r.out, t), frame(r.plain, t)
    from PIL import Image

    h, w = f.shape[:2]
    m = 0.12 * r.params["speed"]
    sw, sh = int(w * (1 + m)) // 2 * 2, int(h * (1 + m)) // 2 * 2
    big = np.asarray(Image.fromarray(g.astype(np.uint8)).resize((sw, sh), Image.BILINEAR)).astype(float)
    y0 = (sh - h) // 2
    return min(range(0, sw - w + 1, 2), key=lambda x: diff(f, big[y0:y0 + h, x:x + w]))


def pans(r: Run) -> tuple[bool, str]:
    xs = [_pan_x(r, t) for t in (0.3, 2.0, 5.5)]
    return xs[0] < xs[1] < xs[2], f"crop x at 0.3/2.0/5.5 s: {xs} (moving right)"


def jitters(r: Run) -> tuple[bool, str]:
    def motion(p: Path, t: float) -> float:
        return diff(frame(p, t), frame(p, t + 1 / 30))
    inside = np.mean([motion(r.out, t) - motion(r.plain, t) for t in (1.3, 1.9, 2.5)])
    outside = abs(motion(r.out, 4.5) - motion(r.plain, 4.5))
    return inside > 3 and outside < 1.5, f"extra frame-to-frame motion inside {inside:.1f}, outside {outside:.1f}"


def faster(r: Run) -> tuple[bool, str]:
    d, d0 = dur(r.out), dur(r.plain)
    f = r.params["factor"]
    want = d0 - 2.0 * (1 - 1 / f)
    m = diff(frame(r.out, 1.5), frame(r.plain, 1.0 + 0.5 * f))
    return near(d, want, 0.15) and m < 6, f"{d0:.2f}→{d:.2f}s (want {want:.2f}); frame 0.5s into the window = plain " \
                                           f"{0.5 * f:.1f}s in (diff {m:.1f})"


def slower(r: Run) -> tuple[bool, str]:
    d, d0 = dur(r.out), dur(r.plain)
    f = r.params["factor"]
    want = d0 + 2.0 * (1 / f - 1)
    m = diff(frame(r.out, 2.0), frame(r.plain, 1.0 + 1.0 * f))
    return near(d, want, 0.15) and m < 6, f"{d0:.2f}→{d:.2f}s (want {want:.2f}); frame 1s into the window = plain " \
                                           f"{1.0 * f:.1f}s in (diff {m:.1f})"


def ramped(r: Run) -> tuple[bool, str]:
    d, d0 = dur(r.out), dur(r.plain)
    st = 2.0 if r.params["curve"] == "speed_up_later" else 0.5
    want = d0 - 3.0 + 3.0 / st
    m = diff(frame(r.out, 6.0 + 3.0 + 0.5), frame(r.plain, 6.0 + 3.0 + 0.5 * st))
    first = diff(frame(r.out, 7.0), frame(r.plain, 7.0))
    return near(d, want, 0.2) and m < 6 and first < 4, \
        f"{d0:.2f}→{d:.2f}s (want {want:.2f}); first half normal ({first:.1f}); second half x{st:g} ({m:.1f})"


def plays_backwards(r: Run) -> tuple[bool, str]:
    """Shot 1 reversed: the output frame at t is the plain frame at (6 - t). Re-encoding a reversed shot leaves
    ~2-3 % noise, so the test is WHERE the best match is (within 2 frames) and how much better it is than its
    neighbours, not an exact equality."""
    def best(t_out: float, t_want: float) -> tuple[float, float, float]:
        f = frame(r.out, t_out)
        cands = [t_want + k / 30 for k in range(-6, 7)]
        ds = [(diff(f, frame(r.plain, t)), t) for t in cands if 0 <= t < 6.0]
        d, t = min(ds)
        others = sorted(x for x, tt in ds if abs(tt - t) > 3 / 30)
        return t, d, others[0] if others else 99.0
    t1, d1, o1 = best(0.3, 5.7)
    t2, d2, o2 = best(5.7, 0.3)
    rest = diff(frame(r.out, 8.0), frame(r.plain, 8.0))
    ok = abs(t1 - 5.7) <= 2 / 30 and abs(t2 - 0.3) <= 2 / 30 and d1 < 0.7 * o1 and d2 < 0.7 * o2 and rest < 4
    return ok and near(dur(r.out), dur(r.plain), 0.1),         f"out 0.3s = plain {t1:.2f}s ({d1:.1f} vs {o1:.1f} for other frames); out 5.7s = plain {t2:.2f}s "         f"({d2:.1f} vs {o2:.1f}); next shot unchanged ({rest:.1f})"


def frozen(r: Run) -> tuple[bool, str]:
    at, d = r.params["at"], r.params["duration"]
    fs = [frame(r.out, t) for t in (at + 0.1, at + d / 2, at + d - 0.1)]
    still = max(diff(fs[0], fs[1]), diff(fs[1], fs[2]))
    same = diff(fs[1], frame(r.plain, at))
    after = diff(frame(r.out, at + d + 0.5), frame(r.plain, at + 0.5))
    quiet = rms_db(r.out, at + 0.15, d - 0.3)
    return still < 1.5 and same < 6 and after < 6 and quiet < -40 and near(dur(r.out), dur(r.plain) + d, 0.12), \
        f"held frames differ {still:.2f}; = plain at {at}s ({same:.1f}); continues after ({after:.1f}); " \
        f"sound in the hold {quiet:.0f} dB; {dur(r.plain):.2f}→{dur(r.out):.2f}s"


# ---- B. transitions ---------------------------------------------------------------------------------------------
def _mid(r: Run) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """(output frame in the middle of the first transition, shot A's frame there, shot B's frame there, overlap)."""
    t = next(x for x in r.plan.transitions if x.after == 0)
    start = r.plan.timeline()[1].start
    mid = start + t.duration / 2
    a = frame(r.plain, mid)                      # shot A at the same output time (A is untouched before the cut)
    b = frame(r.plain, 6.0 + t.duration / 2)     # shot B, t.duration/2 into it
    return frame(r.out, mid), a, b, t.duration


def _len_ok(r: Run) -> tuple[bool, str]:
    d, d0 = dur(r.out), dur(r.plain)
    ov = sum(t.duration for t in r.plan.transitions if t.after >= 0)
    return near(d, d0 - ov, 0.12), f"{d0:.2f}→{d:.2f}s (−{ov:.2f} overlap)"


def blend_mid(r: Run) -> tuple[bool, str]:
    m, a, b, _ = _mid(r)
    mix = diff(m, (a + b) / 2)
    ok, ln = _len_ok(r)
    return ok and mix < 10 and diff(m, a) > 15 and diff(m, b) > 15, f"{ln}; middle frame vs 50/50 mix {mix:.1f}, " \
        f"vs A {diff(m, a):.1f}, vs B {diff(m, b):.1f}"


def dark_mid(r: Run) -> tuple[bool, str]:
    m, a, b, _ = _mid(r)
    ok, ln = _len_ok(r)
    return ok and luma(m) < 0.35 * min(luma(a), luma(b)), f"{ln}; middle brightness {luma(m):.0f} (A {luma(a):.0f}, B {luma(b):.0f})"


def bright_mid(r: Run) -> tuple[bool, str]:
    m, a, b, _ = _mid(r)
    ok, ln = _len_ok(r)
    return ok and luma(m) > max(luma(a), luma(b)) + 40, f"{ln}; middle brightness {luma(m):.0f} (A {luma(a):.0f}, B {luma(b):.0f})"


def _slide_fit(m: np.ndarray, a: np.ndarray, b: np.ndarray) -> tuple[float, int, np.ndarray]:
    """Best match of the middle frame to "A pushed out + B pushed in" (horizontal slides either way)."""
    h, w = m.shape[:2]
    best = (1e9, 0, m)
    for k in range(8, w - 7, 8):
        for left in (True, False):  # B enters from the right (slide left) or from the left
            if left:
                exp = np.concatenate([a[:, k:], b[:, :k]], axis=1)
            else:
                exp = np.concatenate([b[:, w - k:], a[:, :w - k]], axis=1)
            d = diff(m, exp)
            if d < best[0]:
                best = (d, k, exp)
    return best


def split_mid(r: Run) -> tuple[bool, str]:
    """A wipe / iris: part of the frame is already B (in place), the rest still A — not a 50/50 blend.
    A slide moves both pictures: the frame equals A pushed out + B pushed in at some offset."""
    m, a, b, _ = _mid(r)
    ok, ln = _len_ok(r)
    mix = diff(m, (a + b) / 2)
    if r.applied[0].skill == "slide":
        d, k, _exp = _slide_fit(m, a, b)
        w = m.shape[1]
        return ok and d < 10 and 0.1 * w < k < 0.9 * w and mix > 8, \
            f"{ln}; middle frame = A pushed out + B pushed in by {k}px of {w} (diff {d:.1f}); vs a blend {mix:.1f}"
    h, w = m.shape[:2]
    if r.applied[0].skill == "iris_circle":
        # a soft circle: the middle is (nearly) B, the corners are still A
        c = (slice(int(h * .4), int(h * .6)), slice(int(w * .4), int(w * .6)))
        k = (slice(0, h // 6), slice(0, w // 6))
        cb, ca = diff(m[c], b[c]), diff(m[c], a[c])
        kb, ka = diff(m[k], b[k]), diff(m[k], a[k])
        return ok and cb < ca and ka < kb and mix > 8, \
            f"{ln}; centre closer to B ({cb:.1f} vs A {ca:.1f}), corner closer to A ({ka:.1f} vs B {kb:.1f}); vs blend {mix:.1f}"
    blocks = [(y, x) for y in range(0, h - 15, 16) for x in range(0, w - 15, 16)]
    isb = [diff(m[y:y + 16, x:x + 16], b[y:y + 16, x:x + 16]) < 12 for y, x in blocks]
    isa = [diff(m[y:y + 16, x:x + 16], a[y:y + 16, x:x + 16]) < 12 for y, x in blocks]
    share_b, share_a = float(np.mean(isb)), float(np.mean(isa))
    return ok and share_b > 0.04 and share_a > 0.2 and share_a + share_b > 0.7 and mix > 8, \
        f"{ln}; frame already B {share_b:.0%}, still A {share_a:.0%}; vs a 50/50 blend {mix:.1f} (not a blend)"


def differs_mid(r: Run) -> tuple[bool, str]:
    m, a, b, _ = _mid(r)
    ok, ln = _len_ok(r)
    return ok and diff(m, a) > 12 and diff(m, b) > 12 and diff(m, (a + b) / 2) > 8, \
        f"{ln}; middle frame vs A {diff(m, a):.1f}, vs B {diff(m, b):.1f}, vs blend {diff(m, (a + b) / 2):.1f}"


def _hiband(p: Path, start: float, length: float) -> float:
    """Energy above 1.5 kHz (dB). The test clips are pure 440 / 880 Hz tones: a whoosh is broadband noise."""
    x = pcm(p, start, length)
    if len(x) < 512:
        return -120.0
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / 16000)
    return float(10 * np.log10(spec[f > 1500].sum() + 1e-12))


def smeared_mid(r: Run) -> tuple[bool, str]:
    """A whip = the slide frame smeared sideways: the middle frame matches the best slide frame BLURRED
    horizontally better than the sharp one. Plus a whoosh: broadband sound over the cut."""
    from scipy.ndimage import uniform_filter1d

    m, a, b, _ = _mid(r)
    ok, ln = _len_ok(r)
    d_sharp, k, exp = _slide_fit(m, a, b)
    d_blur = diff(m, uniform_filter1d(exp, size=41, axis=1))
    t = next(x for x in r.plan.transitions if x.after == 0)
    at = r.plan.timeline()[1].start + t.duration / 2
    whoosh = _hiband(r.out, at - 0.2, 0.4) - _hiband(r.plain, at - 0.2, 0.4)
    return ok and d_blur < 0.8 * d_sharp and whoosh > 10, \
        f"{ln}; middle frame vs the slide frame blurred sideways {d_blur:.1f}, vs sharp {d_sharp:.1f}; " \
        f"broadband sound +{whoosh:.0f} dB (whoosh)"


def torn_mid(r: Run) -> tuple[bool, str]:
    m, a, b, _ = _mid(r)
    ok, ln = _len_ok(r)
    # RGB tear: red and blue no longer line up (shifted copies), noise on top
    rb = float(np.abs(np.roll(m[..., 0], 14, axis=1) - m[..., 2]).mean())
    rb0 = float(np.abs(np.roll(a[..., 0], 14, axis=1) - a[..., 2]).mean())
    return ok and _hf(m) > 1.3 * max(_hf(a), _hf(b)) and diff(m, a) > 12, \
        f"{ln}; fine noise in the middle {_hf(m):.2f} (A {_hf(a):.2f}, B {_hf(b):.2f}); R/B tear {rb:.1f} (A {rb0:.1f})"


# ---- H. audio ------------------------------------------------------------------------------------------------------
def band_db(p: Path, start: float, length: float, lo: float, hi: float) -> float:
    x = pcm(p, start, length)
    if len(x) < 512:
        return -120.0
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / 16000)
    return float(10 * np.log10(spec[(f >= lo) & (f < hi)].sum() / len(x) + 1e-12))


def _pauses(r: Run) -> list[tuple[float, float]]:
    return [(s, e) for s, e in detect_silence(r.plain, noise_db=-35, min_dur=0.6) if e - s > 0.8]


def music_present(r: Run) -> tuple[bool, str]:
    """The test song's kick is 55 Hz: in the speech pauses there is now a 40-80 Hz band that was not there."""
    ps = _pauses(r)
    if not ps:
        return False, "the talk clip has no pause to listen in"
    s, e = ps[0]
    a, b = band_db(r.out, s + 0.1, min(1.0, e - s - 0.2), 40, 80), band_db(r.plain, s + 0.1, min(1.0, e - s - 0.2), 40, 80)
    return a > b + 15 and r.plan.audio.ducking, f"55 Hz kick band in a pause {b:.0f}→{a:.0f} dB; ducked under speech: {r.plan.audio.ducking}"


def music_ducked(r: Run) -> tuple[bool, str]:
    """Kick band while speaking vs in a pause: with ducking the music drops while the voice is on."""
    ws = r.words(r.out)
    if not ws:
        return False, "no words found to compare against"
    sp = max(((b - a, a) for _, a, b in ws), default=(0, 0))
    speech_t = ws[len(ws) // 2][1]
    ps = [(s, e) for s, e in detect_silence(r.out, noise_db=-40, min_dur=0.5)]
    on = band_db(r.out, speech_t, 0.4, 40, 80)
    on0 = band_db(r.plain, speech_t, 0.4, 40, 80)
    return on < on0 - 4, f"kick band during speech {on0:.0f}→{on:.0f} dB (music ducked under the voice); longest word {sp[0]:.2f}s"


def louder_by(r: Run) -> tuple[bool, str]:
    from cutmind.ffmpeg_utils import measure_loudness

    a, b = measure_loudness(r.out)["lufs"], measure_loudness(r.plain)["lufs"]
    want = min(-9.0, b + r.params["gain_db"])
    return abs(a - want) <= 1.5, f"{b:.1f} → {a:.1f} LUFS (want {want:.1f})"


def muted_window(r: Run) -> tuple[bool, str]:
    i, o = rms_db(r.out, 1.2, 1.6), rms_db(r.out, 4.0, 1.0)
    o0 = rms_db(r.plain, 4.0, 1.0)
    return i < -50 and abs(o - o0) < 2, f"sound inside 1-3 s {i:.0f} dB; outside {o0:.0f}→{o:.0f} dB"


def sound_fades(r: Run) -> tuple[bool, str]:
    mid = rms_db(r.out, 4.0, 0.5)
    st, en = rms_db(r.out, 0.0, 0.15), rms_db(r.out, dur(r.out) - 0.15, 0.15)
    st0 = rms_db(r.plain, 0.0, 0.15)
    return st < mid - 12 and en < mid - 12 and st < st0 - 8, f"first 0.15 s {st0:.0f}→{st:.0f} dB, last 0.15 s {en:.0f} dB, middle {mid:.0f} dB"


def lufs_on_target(r: Run) -> tuple[bool, str]:
    from cutmind.ffmpeg_utils import measure_loudness

    m = measure_loudness(r.out)
    t = r.params["target_lufs"]
    return abs(m["lufs"] - t) <= 1.0 and m["max_volume"] <= -0.5, f"{m['lufs']:.1f} LUFS for {t:g}; peak {m['max_volume']:.1f} dB"


def noise_lower(r: Run) -> tuple[bool, str]:
    """In the gaps between the 'voice' bursts only the noise is left: it must be much quieter; the voice not."""
    g, g0 = rms_db(r.out, 2.7, 0.6), rms_db(r.plain, 2.7, 0.6)
    v, v0 = band_db(r.out, 1.0, 1.0, 250, 350), band_db(r.plain, 1.0, 1.0, 250, 350)
    return g < g0 - 6 and v > v0 - 4, f"noise in a gap {g0:.0f}→{g:.0f} dB; the voice tone {v0:.0f}→{v:.0f} dB"


def presence_up(r: Run) -> tuple[bool, str]:
    ws = r.words(r.plain)
    t = ws[len(ws) // 2][1] if ws else 1.0
    def tilt(p: Path) -> float:
        return band_db(p, t, 1.0, 2500, 4500) - band_db(p, t, 1.0, 150, 400)
    a, b = tilt(r.out), tilt(r.plain)
    return a > b + 2, f"presence (2.5-4.5 kHz) vs body (150-400 Hz) {b:.1f}→{a:.1f} dB"


def cuts_on_beats(r: Run) -> tuple[bool, str]:
    from cutmind.tools.b_audio import song_beats
    from cutmind.tools.engine import ToolCtx

    ctx = ToolCtx(sources={}, gen_dir=r.out.parent / "generated", music_dirs=[Path(r.media["_music"])])
    beats = song_beats(r.plan, ctx)
    cuts = [e.start for e in r.plan.timeline()[1:]]
    off = [min(abs(c - b) for b in beats) for c in cuts]
    return bool(cuts) and max(off) < 0.05, f"cut times {[round(c, 2) for c in cuts]} — distance to the nearest beat {[round(o, 3) for o in off]}"


def whoosh_at_cut(r: Run) -> tuple[bool, str]:
    cut = r.plan.timeline()[1].start
    a, b = _hiband(r.out, cut - 0.2, 0.4), _hiband(r.plain, cut - 0.2, 0.4)
    return a > b + 10, f"broadband sound at the cut {b:.0f}→{a:.0f} dB"


def tail_added(r: Run) -> tuple[bool, str]:
    """clip_b's tone stops at 3.0 s: right after it the echoes keep ringing."""
    a, b = rms_db(r.out, 3.05, 0.25), rms_db(r.plain, 3.05, 0.25)
    return a > b + 10, f"just after the tone stops {b:.0f}→{a:.0f} dB (echo tail)"


def only_music(r: Run) -> tuple[bool, str]:
    f = peak_hz(r.out, 1.0, 1.0)
    k, k0 = band_db(r.out, 1.0, 1.0, 40, 80), band_db(r.plain, 1.0, 1.0, 40, 80)
    t, t0 = band_db(r.out, 1.0, 1.0, 420, 460), band_db(r.plain, 1.0, 1.0, 420, 460)
    return k > k0 + 15 and t < t0 - 20, f"55 Hz kick {k0:.0f}→{k:.0f} dB; the clip's 440 Hz tone {t0:.0f}→{t:.0f} dB; loudest {f:.0f} Hz"


def audio_file(r: Run) -> tuple[bool, str]:
    from cutmind.ffmpeg_utils import decode_check

    f = r.out.with_suffix("." + r.params["format"])
    if not f.exists():
        return False, f"no {f.name} next to the video"
    ok, err = decode_check(f)
    d = probe(f).duration
    return ok and near(d, dur(r.out), 0.15), f"{f.name}: {d:.2f}s (video {dur(r.out):.2f}s), decodes: {ok}"


# ---- E. text and captions --------------------------------------------------------------------------------------
FRAMES = Path(__file__).resolve().parents[2] / "docs" / "test_frames" / "tier1"


def save_frame(r: Run, t: float, name: str) -> Path:
    """Keep a frame for a human to look at (Devanagari shaping is checked by eye — no OCR here)."""
    from PIL import Image

    FRAMES.mkdir(parents=True, exist_ok=True)
    out = FRAMES / f"{name}.png"
    Image.fromarray(frame(r.out, t).astype(np.uint8)).save(out)
    return out


def changed_mask(r: Run, t: float, t_plain: float | None = None) -> np.ndarray:
    return np.abs(frame(r.out, t) - frame(r.plain, t if t_plain is None else t_plain)).mean(axis=2) > 40


def _box_of(mask: np.ndarray) -> tuple[float, float, float, float] | None:
    """Where the changed pixels are (2nd-98th percentile: scattered encoder noise does not stretch the box)."""
    ys, xs = np.where(mask)
    if len(xs) < 30:
        return None
    h, w = mask.shape
    return (float(np.percentile(xs, 2)) / w, float(np.percentile(ys, 2)) / h,
            float(np.percentile(xs, 98)) / w, float(np.percentile(ys, 98)) / h)


def captions_on_speech(r: Run) -> tuple[bool, str]:
    caps = [t for t in r.plan.text if t.kind == "caption"]
    if not caps:
        return False, "no captions in the plan"
    c = caps[len(caps) // 2]
    mid = (c.start + c.end) / 2
    m = changed_mask(r, mid)
    h = m.shape[0]
    bottom, top = m[int(h * 0.6):].mean(), m[: int(h * 0.4)].mean()
    gaps = [(a.end, b.start) for a, b in zip(caps, caps[1:], strict=False) if b.start - a.end > 0.6]
    quiet = changed_mask(r, (gaps[0][0] + gaps[0][1]) / 2).mean() if gaps else 0.0
    save_frame(r, mid, "auto_captions")
    return bottom > 0.004 and top < 0.002 and quiet < 0.001, \
        f"{len(caps)} captions; text pixels in the bottom band {bottom:.2%} while '{c.text}' is said, top {top:.2%}; " \
        f"in a pause {quiet:.2%}"


def karaoke_colors(r: Run) -> tuple[bool, str]:
    caps = [t for t in r.plan.text if t.kind == "caption"]
    if not caps or any(t.style.animation != "karaoke" for t in caps):
        return False, "captions are not karaoke"
    c = max(caps, key=lambda t: t.end - t.start)
    t = c.start + (c.end - c.start) * 0.6
    f = frame(r.out, t)
    m = changed_mask(r, t)  # caption pixels (the plain render has no captions)
    yellow = ((f[..., 0] > 200) & (f[..., 1] > 170) & (f[..., 2] < 90) & m).mean()
    white = ((f[..., 0] > 220) & (f[..., 1] > 220) & (f[..., 2] > 220) & m).mean()
    save_frame(r, c.start + (c.end - c.start) * 0.6, "karaoke_captions")
    return yellow > 0.0002 and white > 0.0002, f"part of '{c.text}' lit yellow ({yellow:.3%} of the frame), the rest white ({white:.3%})"


def caption_recolored(r: Run) -> tuple[bool, str]:
    caps = [t for t in r.plan.text if t.kind == "caption"]
    c = caps[len(caps) // 2]
    t = (c.start + c.end) / 2
    f, g = frame(r.out, t), frame(r.plain, t)
    m = np.abs(f - g).mean(axis=2) > 40  # the letters whose colour changed

    def yellow(x: np.ndarray) -> float:
        return float(((x[..., 0] > 200) & (x[..., 1] > 170) & (x[..., 2] < 90) & m).mean())
    save_frame(r, t, "caption_style_yellow")
    return yellow(f) > 0.0002 and yellow(g) < 0.00005, f"recoloured caption pixels: yellow in the old {yellow(g):.3%}, in the new {yellow(f):.3%}"


def text_bottom_left(r: Run) -> tuple[bool, str]:
    b = _box_of(changed_mask(r, 2.5))
    out = changed_mask(r, 4.6).mean()
    save_frame(r, 2.5, "lower_third")
    return b is not None and b[0] < 0.2 and b[1] > 0.55 and b[2] < 0.75 and out < 0.001, \
        f"text box (x0 y0 x1 y1 share of frame) {tuple(round(v, 2) for v in b) if b else None}; after its window {out:.2%}"


def text_in_window(r: Run) -> tuple[bool, str]:
    inside, before, after = changed_mask(r, 2.5).mean(), changed_mask(r, 0.5).mean(), changed_mask(r, 4.6).mean()
    b = _box_of(changed_mask(r, 2.5))
    return inside > 0.004 and before < 0.0005 and after < 0.0005 and b is not None and 0.2 < (b[0] + b[2]) / 2 < 0.8, \
        f"text pixels before {before:.2%}, inside 1-4 s {inside:.2%}, after {after:.2%}; box {tuple(round(v, 2) for v in b) if b else None}"


def text_grows(r: Run) -> tuple[bool, str]:
    a, b, c = changed_mask(r, 1.15).mean(), changed_mask(r, 1.8).mean(), changed_mask(r, 3.5).mean()
    save_frame(r, 3.5, "typewriter_hindi")
    return a < b < c + 1e-6 and c > 0.004, f"text pixels at 1.15 / 1.8 / 3.5 s: {a:.2%} < {b:.2%} < {c:.2%} (typed out)"


def text_pops(r: Run) -> tuple[bool, str]:
    b0, b1 = _box_of(changed_mask(r, 1.05)), _box_of(changed_mask(r, 1.8))
    w0 = (b0[2] - b0[0]) if b0 else 0.0
    w1 = (b1[2] - b1[0]) if b1 else 0.0
    return w1 > 0.05 and w0 < 0.85 * w1, f"text width at 1.05 s {w0:.2f}, at 1.8 s {w1:.2f} (grows in)"


def neon_glow(r: Run) -> tuple[bool, str]:
    f, g = frame(r.out, 2.5), frame(r.plain, 2.5)
    d = np.abs(f - g).mean(axis=2)
    core = ((f.min(axis=2) > 180) & (d > 40)).mean()                   # bright, near-white letter core
    pink = ((f[..., 0] > 170) & (f[..., 2] > 90) & (f[..., 1] < 120) & (d > 25)).mean()  # coloured tube / glow
    save_frame(r, 2.5, "neon_text")
    return core > 0.0005 and pink > 0.0005, f"bright letter core {core:.2%}; pink glow {pink:.2%}"


def text_moves_in(r: Run) -> tuple[bool, str]:
    b0, b1 = _box_of(changed_mask(r, 1.08)), _box_of(changed_mask(r, 2.5))
    x0 = (b0[0] + b0[2]) / 2 if b0 else -1
    x1 = (b1[0] + b1[2]) / 2 if b1 else -1
    return b1 is not None and (b0 is None or x0 < x1 - 0.05), f"text centre x at 1.08 s {x0:.2f}, at 2.5 s {x1:.2f} (comes in from the left)"


def logo_corner(r: Run) -> tuple[bool, str]:
    f = frame(r.out, 2.0)
    h, w = f.shape[:2]
    corner = f[: int(h * 0.3), int(w * 0.75):]
    redness = float(((corner[..., 0] - corner[..., 1]) > 60).mean())
    rest = changed_mask(r, 2.0)[int(h * 0.4):, : int(w * 0.6)].mean()
    return redness > 0.05 and rest < 0.001, f"red logo pixels in the top-right corner {redness:.1%}; rest of the frame changed {rest:.2%}"


def bar_fills(r: Run) -> tuple[bool, str]:
    def width(t: float) -> float:
        f = frame(r.out, t)
        row = f[-3]
        yellow = (row[:, 0] > 200) & (row[:, 1] > 170) & (row[:, 2] < 90)
        return float(yellow.mean())
    a, b, c = width(1.0), width(6.0), width(11.5)
    return a < b < c and c > 0.9, f"bar width at 1 / 6 / 11.5 s: {a:.0%}, {b:.0%}, {c:.0%}"


# ---- F. stylize and overlays ------------------------------------------------------------------------------------
def differs_in_window(r: Run) -> tuple[bool, str]:
    i = diff(frame(r.out, 2.0), frame(r.plain, 2.0))
    o = diff(frame(r.out, 4.5), frame(r.plain, 4.5))
    save_frame(r, 2.0, r.applied[0].skill)
    return i > 8 and o < 2, f"picture changed {i:.1f} inside 1-3 s, {o:.1f} outside"


def channels_apart(r: Run) -> tuple[bool, str]:
    """Red is shifted against blue: the best horizontal alignment of R onto B moves away from 0."""
    f, g = frame(r.out, 2.0), frame(r.plain, 2.0)

    def shift(c: int) -> int:  # how far channel c moved against the plain picture's same channel
        return min(range(-30, 31), key=lambda k: float(np.abs(np.roll(g[..., c], k, axis=1) - f[..., c])[:, 40:-40].mean()))
    kr, kb = shift(0), shift(2)
    return abs(kr - kb) >= 8, f"red moved {kr:+d}px, blue {kb:+d}px (pulled apart by {abs(kr - kb)}px)"


def flash_peaks(r: Run) -> tuple[bool, str]:
    peak, before, after = luma(frame(r.out, 2.0)), luma(frame(r.out, 1.6)), luma(frame(r.out, 2.5))
    p0 = luma(frame(r.plain, 2.0))
    return peak > p0 + 40 and abs(before - luma(frame(r.plain, 1.6))) < 3 and abs(after - luma(frame(r.plain, 2.5))) < 3, \
        f"brightness at the flash {p0:.0f}→{peak:.0f}; 0.4 s before / 0.5 s after unchanged"


def warm_glow(r: Run) -> tuple[bool, str]:
    a, b = frame(r.out, 2.0), frame(r.plain, 2.0)
    lift = luma(a) - luma(b)
    warm = _rb(a) - _rb(b)
    o = diff(frame(r.out, 4.5), frame(r.plain, 4.5))
    save_frame(r, 2.0, "light_leak")
    return lift > 3 and warm > 3 and o < 2, f"brighter by {lift:.1f}, warmer (R-B) by {warm:.1f} inside; outside changed {o:.1f}"


def mirrored(r: Run) -> tuple[bool, str]:
    f = frame(r.out, 2.0)
    w = f.shape[1]
    sym = diff(f[:, : w // 2], f[:, w - w // 2:][:, ::-1])
    sym0 = diff(frame(r.plain, 2.0)[:, : w // 2], frame(r.plain, 2.0)[:, w - w // 2:][:, ::-1])
    return sym < 4 and sym0 > 20, f"left vs mirrored right half {sym0:.1f} → {sym:.1f}"


def _gbox(r: Run, f: np.ndarray) -> np.ndarray:
    """The censor box of the plan (shrunk 10 % so its own border is not measured)."""
    g = r.plan.graphics[0]
    h, w = f.shape[:2]
    x0, y0 = int((g.x + 0.1 * g.w) * w), int((g.y + 0.1 * g.h) * h)
    x1, y1 = int((g.x + 0.9 * g.w) * w), int((g.y + 0.9 * g.h) * h)
    return f[y0:y1, x0:x1]


def censored_pixelate(r: Run) -> tuple[bool, str]:
    a, b = _gbox(r, frame(r.out, 2.0)), _gbox(r, frame(r.plain, 2.0))
    # blocks: neighbouring pixels are equal far more often than in the original picture
    flat = float((np.abs(np.diff(a.mean(axis=2), axis=1)) < 1.5).mean())
    flat0 = float((np.abs(np.diff(b.mean(axis=2), axis=1)) < 1.5).mean())
    o = diff(frame(r.out, 4.5), frame(r.plain, 4.5))
    save_frame(r, 2.0, "pixelate_censor")
    return flat > flat0 + 0.15 and o < 2, f"equal-neighbour share in the box {flat0:.0%} → {flat:.0%} (blocks); outside the window {o:.1f}"


def _sharp(f: np.ndarray) -> float:
    """Squared-gradient energy: a blur spreads a step into many small steps, so it goes DOWN (mean |gradient|
    stays about the same and cannot see a blur)."""
    g = f.mean(axis=2)
    return float((np.diff(g, axis=0) ** 2).mean() + (np.diff(g, axis=1) ** 2).mean())


def censored_blur(r: Run) -> tuple[bool, str]:
    a, b = _sharp(_gbox(r, frame(r.out, 2.0))), _sharp(_gbox(r, frame(r.plain, 2.0)))
    corner = diff(frame(r.out, 2.0)[:40, :40], frame(r.plain, 2.0)[:40, :40])
    save_frame(r, 2.0, "blur_box_censor")
    return a < 0.3 * b and corner < 3, f"sharpness in the box {b:.0f} → {a:.0f}; a corner outside the box {corner:.1f}"


def shape_drawn(r: Run) -> tuple[bool, str]:
    f = frame(r.out, 2.0)
    m = changed_mask(r, 2.0)
    yellow = ((f[..., 0] > 200) & (f[..., 1] > 170) & (f[..., 2] < 90) & m).mean()
    b = _box_of(m)
    save_frame(r, 2.0, "shape_highlight")
    return yellow > 0.002 and b is not None and 0.25 < (b[0] + b[2]) / 2 < 0.75, f"yellow ring pixels {yellow:.2%} around {tuple(round(v, 2) for v in b) if b else None}"


def sticker_shown(r: Run) -> tuple[bool, str]:
    m = changed_mask(r, 2.0)
    h, w = m.shape
    corner = m[: int(h * 0.45), int(w * 0.55):].mean()
    rest = m[int(h * 0.55):, : int(w * 0.45)].mean()
    after = changed_mask(r, 4.5).mean()
    save_frame(r, 2.0, "sticker")
    return corner > 0.02 and rest < 0.002 and after < 0.002, f"sticker pixels top-right {corner:.1%}, elsewhere {rest:.2%}, after its window {after:.2%}"


def countdown_shows(r: Run) -> tuple[bool, str]:
    shown = [changed_mask(r, t).mean() for t in (1.5, 2.5, 3.5)]
    before, after = changed_mask(r, 0.5).mean(), changed_mask(r, 4.5).mean()
    nums = [t.text for t in r.plan.text]
    save_frame(r, 1.5, "countdown")
    return all(x > 0.001 for x in shown) and before < 0.001 and after < 0.001 and nums[-3:] == ["3", "2", "1"], \
        f"numbers {nums[-3:]}; text pixels at 1.5/2.5/3.5 s {[f'{x:.1%}' for x in shown]}, before {before:.2%}, after {after:.2%}"


# ---- I. analysis and delivery -----------------------------------------------------------------------------------
def cuts_at_scenes(r: Run) -> tuple[bool, str]:
    """clip_c_scenes: blue → colour bars at 4 s → test pattern at 8 s."""
    cuts = [round(e.start, 2) for e in r.plan.timeline()[1:]]
    ok = any(abs(c - 4.0) < 0.15 for c in cuts) and any(abs(c - 8.0) < 0.15 for c in cuts) and len(cuts) == 2
    return ok and near(dur(r.out), dur(r.plain), 0.1), f"cuts at {cuts} (the clip changes scene at 4.0 and 8.0 s)"


def platform_specs(r: Run) -> tuple[bool, str]:
    info = probe(r.out)
    from cutmind.tools.b_delivery import PLATFORMS

    spec = PLATFORMS[r.params["platform"]]
    kbps = info.size_bytes * 8 / 1000 / max(0.1, info.duration)
    return (info.width, info.height) == (720, 1280) and abs(info.fps - spec["fps"]) < 0.1 and info.video_codec == "h264" \
        and info.audio_codec == "aac" and kbps < spec["kbps"] * 1.1, \
        f"{info.width}x{info.height} {info.fps:g} fps {info.video_codec}/{info.audio_codec}, {kbps:.0f} kbit/s (cap {spec['kbps']})"


def steadier(r: Run) -> tuple[bool, str]:
    def jitter(p: Path) -> float:
        return float(np.mean([diff(frame(p, t), frame(p, t + 1 / 30)) for t in (1.0, 2.0, 3.0, 3.5)]))
    a, b = jitter(r.out), jitter(r.plain)
    return a < 0.8 * b, f"frame-to-frame change {b:.1f} → {a:.1f}"


def boomerang(r: Run) -> tuple[bool, str]:
    d, d0 = dur(r.out), dur(r.plain)
    mirror = diff(frame(r.out, 1.0), frame(r.out, 2 * d0 - 1.0))
    other = diff(frame(r.out, 1.0), frame(r.out, 2 * d0 - 2.2))
    return near(d, 2 * d0, 0.15) and mirror < 6 and mirror < 0.6 * other, \
        f"{d0:.2f}→{d:.2f}s; frame at 1.0 s = frame at {2 * d0 - 1.0:.1f}s (diff {mirror:.1f}, vs another {other:.1f})"


def thumbnail_file(r: Run) -> tuple[bool, str]:
    from PIL import Image

    f = r.out.with_suffix(".jpg")
    if not f.exists():
        return False, "no JPG next to the video"
    img = np.asarray(Image.open(f).convert("RGB")).astype(float)
    d = diff(img, frame(r.out, r.params["at"]))
    return img.shape[:2] == frame(r.out, 0.5).shape[:2] and d < 6, f"{f.name} {img.shape[1]}x{img.shape[0]}, = frame at {r.params['at']}s (diff {d:.1f})"


def srt_file(r: Run) -> tuple[bool, str]:
    f = r.out.with_suffix(".srt")
    if not f.exists():
        return False, "no .srt next to the video"
    blocks = [b for b in f.read_text(encoding="utf-8").strip().split("\n\n") if b.strip()]
    caps = [t for t in r.plan.text if t.kind == "caption"]
    import re as _re

    times_ok = all(_re.match(r"\d+\n\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}\n.+", b) for b in blocks)
    return len(blocks) == len(caps) and times_ok and len(caps) > 0, f"{len(blocks)} SRT entries for {len(caps)} captions; well-formed: {times_ok}"


CHECKS = {k: v for k, v in globals().items() if callable(v) and k not in (
    "frame", "diff", "dur", "pcm", "peak_hz", "rms_db", "edges", "near", "Run", "sat", "luma", "_in_out", "_rb",
    "_hf", "_zoomed", "scale_at", "_pan_x", "_mid", "_len_ok", "_slide_fit", "_hiband", "band_db", "_pauses",
    "save_frame", "changed_mask", "_box_of", "FRAMES", "_gbox", "_sharp", "dataclass", "field", "detect_silence",
    "extract_frame", "ffmpeg_bin", "probe", "EditPlan", "Path", "Any")}
