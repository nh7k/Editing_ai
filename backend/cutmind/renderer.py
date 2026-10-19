"""Deterministic FFmpeg renderer: Edit Plan JSON in, MP4 out. The only module that edits video."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from . import segmentation
from .ffmpeg_utils import ffmpeg_bin, probe, run_ffmpeg
from .framing import Frame, follow_zoom, piecewise, resample
from .fx_catalog import TRANSITIONS_BY_ID, FxContext, effect_filters, xfade_name
from .luts import LOOKS, LUT_DIR, ensure_luts
from .plan import FADE_IN, FADE_OUT, Canvas, EditPlan, Effect, TextItem, TimelineEntry

ProgressFn = Callable[[float, str], None]

# xfade transition names for each plan transition type

# intermediates are re-encoded once more at the end, so favour speed (quality loss at crf 17 is negligible)
INTERMEDIATE_V = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "17", "-pix_fmt", "yuv420p"]
# the "original quality" export: near-lossless intermediates (bigger temp files, the final encode decides the quality)
MASTER_V = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "10", "-pix_fmt", "yuv420p"]


def inter_v(plan: EditPlan) -> list[str]:
    return MASTER_V if plan.export.is_master else INTERMEDIATE_V
# PCM, not AAC: every AAC file starts with ~21 ms of encoder priming that the concat demuxer does not trim — it
# put a silent gap at EVERY hard cut (measured: 21-50 ms of zeros where a split should be inaudible)
INTERMEDIATE_A = ["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"]


class RenderError(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------------
# filter builders (pure functions — unit tested)
# ---------------------------------------------------------------------------------------------
def atempo_chain(speed: float) -> list[str]:
    """atempo only accepts 0.5..2.0 per instance, so chain them."""
    parts: list[str] = []
    s = speed
    while s >= 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s <= 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    if abs(s - 1.0) > 1e-6:
        parts.append(f"atempo={s:.6f}")
    return parts


def color_filters(plan: EditPlan, clip_id: str) -> list[str]:
    c = plan.color
    out: list[str] = []
    brightness = c.brightness + c.clip_brightness.get(clip_id, 0.0)
    if (abs(brightness) > 1e-3 or abs(c.contrast - 1) > 1e-3 or abs(c.saturation - 1) > 1e-3
            or abs(c.gamma - 1) > 1e-3):
        out.append(f"eq=brightness={brightness:.3f}:contrast={c.contrast:.3f}:saturation={c.saturation:.3f}"
                   f":gamma={c.gamma:.3f}")
    if abs(c.warmth) > 1e-3:
        # colortemperature: lower Kelvin = warmer (more red), higher = cooler (more blue)
        kelvin = int(6500 - c.warmth * 3000)
        out.append(f"colortemperature=temperature={kelvin}:mix=1")
    if c.preset == "cinematic":
        out.append("curves=r='0/0 0.25/0.22 0.75/0.8 1/1':b='0/0.06 0.25/0.28 0.75/0.7 1/0.94'")
    elif c.preset == "vintage":
        out.append("curves=preset=vintage")
    elif c.preset == "bw":
        out.append("hue=s=0")
    elif c.preset in LOOKS:
        ensure_luts()
        out.append(f"lut3d=file={c.preset}.cube")  # relative: the segment is rendered with cwd = LUT_DIR
    elif c.preset == "sepia":
        out.append("colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131")
    return out


def orientation_filters(canvas: Canvas) -> list[str]:
    """Rotate (clockwise) / mirror the source before it is fitted to the canvas."""
    out = {90: ["transpose=1"], 180: ["transpose=1", "transpose=1"], 270: ["transpose=2"]}.get(canvas.rotate, [])
    if canvas.flip in ("h", "hv"):
        out.append("hflip")
    if canvas.flip in ("v", "hv"):
        out.append("vflip")
    return out


def reframe_filter(w: int, h: int, mode: str, src_label: str, out_label: str) -> str:
    """Fit any source into the canvas: crop to fill, or blurred background + centred foreground."""
    if mode == "blur_pad":
        return (
            f"[{src_label}]split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=20:2[bg];"
            f"[fgsrc]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[{out_label}]"
        )
    if mode == "pad":
        return (f"[{src_label}]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black[{out_label}]")
    return f"[{src_label}]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}[{out_label}]"


def subject_frame(e: Effect, W: int, H: int, w: int, h: int) -> Frame:
    zoom = follow_zoom(W, H, w, h) * (1.6 if e.type == "person_zoom" else 1.0)
    return Frame(W, H, w, h, "follow", zoom)


def follow_crop(e: Effect, W: int, H: int, w: int, h: int, src_label: str, out_label: str) -> str:
    """Crop that keeps the tracked person in frame (auto-reframe). x/y are per-frame expressions in t."""
    fr = subject_frame(e, W, H, w, h)
    sw, sh = fr.scaled
    keys = resample([tuple(p) for p in e.points])
    xs = [(p[0], fr.crop_origin(p[1], p[2])[0]) for p in keys]
    ys = [(p[0], fr.crop_origin(p[1], p[2])[1]) for p in keys]
    return f"[{src_label}]scale={sw}:{sh},crop={w}:{h}:x={piecewise(xs)}:y={piecewise(ys)}[{out_label}]"


def spotlight_filter(e: Effect, follow: Effect | None, W: int, H: int, w: int, h: int, reframe: str) -> str:
    """Vignette whose centre sits on the tracked person."""
    fr = subject_frame(follow, W, H, w, h) if follow is not None else Frame(W, H, w, h, reframe)
    keys = resample([tuple(p) for p in e.points])
    pts = [(p[0], *fr.to_output(p[1], p[2], (p[1], p[2]) if follow is not None else None)) for p in keys]
    x0 = piecewise([(t, min(max(x, 0), w)) for t, x, _y in pts])
    y0 = piecewise([(t, min(max(y, 0), h)) for t, _x, y in pts])
    return f"vignette=angle=PI/2.6:x0={x0}:y0={y0}:eval=frame"


def motion_filters(effects: list[Effect], index: int, w: int, h: int, duration: float, fps: int = 30) -> list[str]:
    """Motion + video effects for one segment, straight from the FX catalogue (cutmind/fx_catalog.py)."""
    out: list[str] = []
    for e in effects:
        if e.target not in (-1, index):
            continue
        if e.type in ("camera_move", "keyframes"):
            from .camera_move import replay_filters

            out += replay_filters(e.points, w, h, duration, e.strength, fps,
                                  easing=(e.easing or "ease_in_out") if e.type == "keyframes" else None)
            continue
        out += effect_filters(e.type, FxContext(w=w, h=h, duration=duration, fps=fps, strength=e.strength,
                                                 times=tuple(e.times), params=dict(e.params)))
    return out


def continues(plan: EditPlan, i: int) -> bool:
    """Segment i+1 picks up exactly where segment i stops (a split, not a cut): no edge fades between them."""
    tl = plan.timeline()
    if i < 0 or i + 1 >= len(tl) or plan.overlap_after(i) > 0:
        return False
    a, b = tl[i].segment, tl[i + 1].segment
    return (a.source == b.source and not a.reverse and not b.reverse and not a.hold and not b.hold
            and abs(a.speed - b.speed) < 1e-6 and abs(a.out - b.in_) < 0.002)


def _anchor(w: int, h: int, align: int, margin_v: int) -> tuple[int, int]:
    x = {1: int(w * 0.06), 4: int(w * 0.06), 7: int(w * 0.06), 3: w - int(w * 0.06), 6: w - int(w * 0.06),
         9: w - int(w * 0.06)}.get(align, w // 2)
    y = {2: h - margin_v, 1: h - margin_v, 3: h - margin_v, 8: margin_v, 7: margin_v, 9: margin_v}.get(align, h // 2)
    return x, y


# ASS override tags per animation (times in ms from the start of the line). Pure libass: no extra render cost.
_ANIM_TAGS = {
    "fade": r"\fad(180,180)",
    "pop": r"\fscx40\fscy40\t(0,140,\fscx112\fscy112)\t(140,240,\fscx100\fscy100)",
    "bounce": r"\t(0,120,\fscx122\fscy122)\t(120,240,\fscx92\fscy92)\t(240,340,\fscx100\fscy100)",
    "zoom_in": r"\fscx0\fscy0\t(0,260,\fscx100\fscy100)",
    "zoom_out": r"\fscx230\fscy230\alpha&HFF&\t(0,260,\fscx100\fscy100\alpha&H00&)",
    "spin_in": r"\frz-200\fscx20\fscy20\t(0,320,\frz0\fscx100\fscy100)",
    "flip_in": r"\fry90\t(0,320,\fry0)",
    "blur_in": r"\blur18\alpha&HFF&\t(0,320,\blur0\alpha&H00&)",
    "swing": r"\frz-10\t(0,300,\frz8)\t(300,600,\frz-5)\t(600,900,\frz2)\t(900,1100,\frz0)",
    "shake": r"\t(0,70,\fax0.18)\t(70,140,\fax-0.18)\t(140,210,\fax0.12)\t(210,280,\fax-0.08)\t(280,350,\fax0)",
    "heartbeat": r"\t(0,140,\fscx120\fscy120)\t(140,280,\fscx100\fscy100)\t(420,560,\fscx120\fscy120)"
                 r"\t(560,700,\fscx100\fscy100)",
    "flicker": r"\alpha&HFF&\t(0,60,\alpha&H00&)\t(100,140,\alpha&HD0&)\t(160,200,\alpha&H00&)\t(260,300,\alpha&H90&)"
               r"\t(320,360,\alpha&H00&)",
    "glow_pulse": r"\blur0\t(0,400,\blur7)\t(400,800,\blur0)\t(800,1200,\blur7)\t(1200,1600,\blur0)",
    "color_cycle": r"\t(0,500,\c&HEED322&)\t(500,1000,\c&HFF5C7C&)\t(1000,1500,\c&H15CCFA&)\t(1500,2000,\c&HFFFFFF&)",
    "stretch": r"\fscx260\fscy55\t(0,180,\fscx90\fscy115)\t(180,300,\fscx100\fscy100)",
}
_MOVE_ANIMS = {"slide_up", "drop_in", "fly_left", "fly_right"}


def _text_animation(item: TextItem, w: int, h: int, align: int, margin_v: int) -> str:
    """ASS override tags for caption/title animations (CapCut-style text presets)."""
    anim = item.style.animation
    tags = [r"\blur%.1f" % (item.style.glow * min(w, h) / 1080)] if item.style.glow else []
    if anim in _ANIM_TAGS:
        tags.append(_ANIM_TAGS[anim])
    elif anim in _MOVE_ANIMS and not item.track:
        x, y = _anchor(w, h, align, margin_v)
        x0, y0 = {"slide_up": (x, y + int(h * 0.06)), "drop_in": (x, y - int(h * 0.12)),
                  "fly_left": (-int(w * 0.3), y), "fly_right": (w + int(w * 0.3), y)}[anim]
        tags.append(rf"\move({x0},{y0},{x},{y},0,{220 if anim == 'slide_up' else 320})\fad(120,0)")
    elif anim in _MOVE_ANIMS:  # tracked text already moves with the person: just fade in
        tags.append(r"\fad(150,0)")
    return "{" + "".join(tags) + "}" if tags else ""


_DEV_MARK = "\u0900\u0901\u0902\u0903\u093a\u093b\u093c\u093e\u093f\u0940\u0941\u0942\u0943\u0944\u0945\u0946" \
            "\u0947\u0948\u0949\u094a\u094b\u094c\u094d\u094e\u094f\u0951\u0952\u0953\u0954\u0955\u0956\u0957" \
            "\u0962\u0963\u200c\u200d"
_VIRAMA = "\u094d"


def letters(text: str) -> list[str]:
    """Visible letters (grapheme clusters / aksharas), not code points: a Devanagari consonant keeps its matras,
    nukta and virama + next consonant (conjuncts like क्ष, त्र, श्र) together. Splitting by code point put override
    tags between a consonant and its matra, and libass then shaped them apart (a broken word)."""
    out: list[str] = []
    for ch in text:
        if out and (ch in _DEV_MARK or out[-1].endswith(_VIRAMA)):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def _timed_text(item: TextItem, text: str) -> str:
    """Typewriter (letters) / karaoke (words) / wave / cascade (per letter); other animations: text unchanged."""
    anim = item.style.animation
    total_cs = max(10, int(round((item.end - item.start) * 100)))
    if anim == "typewriter":
        chars = letters(text)
        step = max(2, min(8, int(total_cs * 0.6 / max(1, len(chars)))))
        return "".join(rf"{{\k{step}}}{ch}" for ch in chars)
    if anim == "karaoke":
        words = text.split(" ")
        wt = item.word_times
        if len(wt) == len(words) and wt:
            # each word lights up when it is SAID (the speech's own word times), a lead-in before the first one
            marks = [max(0, int(round(t * 100))) for t in wt] + [total_cs]
            lead = rf"{{\k{marks[0]}}}" if marks[0] > 0 else ""
            return lead + " ".join(rf"{{\k{max(1, marks[i + 1] - marks[i])}}}{wd}" for i, wd in enumerate(words))
        step = max(5, int(total_cs * 0.85 / max(1, len(words))))
        return " ".join(rf"{{\k{step}}}{wd}" for wd in words)
    if anim == "wave":
        return "".join(ch if ch == " " else
                       rf"{{\t({i * 60},{i * 60 + 160},\fscy145)\t({i * 60 + 160},{i * 60 + 320},\fscy100)}}{ch}"
                       for i, ch in enumerate(letters(text)))
    if anim == "cascade":
        return "".join(ch if ch == " " else rf"{{\alpha&HFF&\t({i * 45},{i * 45 + 200},\alpha&H00&)}}{ch}"
                       for i, ch in enumerate(letters(text)))
    return text


def _ass_color(hex_rgb: str, alpha: int = 0) -> str:
    r, g, b = hex_rgb[1:3], hex_rgb[3:5], hex_rgb[5:7]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ass_time(t: float) -> str:
    cs = int(round(max(t, 0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass(items: list[TextItem], w: int, h: int) -> str:
    """ASS subtitle file for captions, titles, text and tracked labels (rendered by libass)."""
    from .text_styles import font_family

    scale = min(w, h) / 1080
    align = {"bottom": 2, "center": 5, "top": 8, "top_right": 9, "bottom_right": 3, "bottom_left": 1, "top_left": 7}
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
    ]
    events = ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for i, item in enumerate(items):
        st = item.style
        size = max(12, int(round(st.size * scale)))
        margin_v = int(h * (st.margin if st.margin is not None else 0.09)) if st.position != "center" else 0
        if item.kind == "watermark":
            margin_v = int(h * 0.04)
        alpha = 0x70 if item.kind == "watermark" else 0  # watermarks are semi-transparent
        width = st.outline * scale if st.outline is not None else max(2, size // 12)
        if st.box_color:
            # BorderStyle 3 = opaque box drawn with OutlineColour
            border, outline, outline_col, back = 3, max(4, size // 4), _ass_color(st.box_color), _ass_color(st.box_color)
        elif st.outline_color:
            border, outline, outline_col, back = 1, round(width, 1), _ass_color(st.outline_color, alpha), "&H80000000"
        else:
            border, outline, outline_col, back = 1, round(width, 1), f"&H{alpha:02X}000000", "&H80000000"
        shadow = round(st.shadow * scale, 1)
        name = f"S{i}"
        primary, secondary = _ass_color(st.color, alpha), "&H000000FF"
        if st.animation == "typewriter":
            secondary = "&HFF" + primary[4:]   # not-yet-typed letters fully transparent
        elif st.animation == "karaoke":
            # the word being said turns the highlight colour (yellow by default); the rest keeps the text colour
            primary, secondary = _ass_color(st.highlight or "#FACC15", alpha), _ass_color(st.color, alpha)
        family, bold = font_family(st.font)
        lines.append(
            f"Style: {name},{family},{size},{primary},{secondary},{outline_col},{back},{-1 if bold else 0},0,0,0,100,100,"
            f"0,0,{border},{outline},{shadow},{align[st.position]},{int(w * 0.06)},{int(w * 0.06)},{margin_v},1"
        )
        raw = item.text.upper() if st.uppercase else item.text
        text = raw.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")
        body = _timed_text(item, text)
        layer = {"caption": 0, "title": 1, "watermark": 2, "text": 3}[item.kind]
        anim = _text_animation(item, w, h, align[st.position], margin_v)
        if item.track:
            # follow the person: one line per keyframe pair, each moving from one point to the next
            pts = [p for p in item.track if item.start - 0.25 <= p[0] <= item.end + 0.25]
            pts = pts if len(pts) >= 2 else (pts * 2 if pts else [])
            for k, (a, b) in enumerate(zip(pts, pts[1:], strict=False)):
                t0, t1 = max(item.start, a[0]), min(item.end, b[0])
                if t1 <= t0:
                    continue
                mv = rf"{{\an2\move({a[1]:.0f},{a[2]:.0f},{b[1]:.0f},{b[2]:.0f})}}"
                events.append(f"Dialogue: {layer},{_ass_time(t0)},{_ass_time(t1)},{name},,0,0,0,,"
                              f"{mv}{anim if k == 0 else ''}{body if k == 0 else text}")
            continue
        events.append(f"Dialogue: {layer},{_ass_time(item.start)},{_ass_time(item.end)},{name},,0,0,0,,{anim}{body}")
    return "\n".join(lines + events) + "\n"


# ---------------------------------------------------------------------------------------------
# render stages
# ---------------------------------------------------------------------------------------------
def frame_time(t: float, fps: float) -> float:
    """t on the output frame grid."""
    return round(t * fps) / fps


def segment_frames(entry: TimelineEntry, fps: float) -> tuple[int, float]:
    """(frames, seconds) of a segment on the timeline's frame grid — the cuts stay within half a frame of the plan
    and never drift."""
    n = max(1, round(entry.end * fps) - round(entry.start * fps))
    return n, n / fps


def render_segment(plan: EditPlan, entry: TimelineEntry, src: Path, out: Path) -> Path:
    """Trim + speed + reframe + color + motion effects for one segment → uniform intermediate."""
    seg = entry.segment
    w, h = plan.canvas.size
    fps = plan.canvas.fps
    info = probe(src)
    src_dur = seg.out - seg.in_
    if seg.in_ >= info.duration - 0.05:
        raise RenderError(f"segment {entry.index} starts at {seg.in_:.2f}s but clip is only {info.duration:.2f}s")
    reframe = "blur_pad" if plan.canvas.reframe == "blur_pad" or any(
        e.type == "blur_background" and e.target in (-1, entry.index) for e in plan.effects) else plan.canvas.reframe
    ramp = next((e for e in plan.effects if e.type == "speed_ramp" and e.target in (-1, entry.index)), None)

    # read a little MORE than needed and trim exactly in the filters: an input "-t" cut the AAC sound of the
    # source ~21 ms short (its encoder delay), and apad filled that with silence — a gap at every cut
    args: list[str] = ["-ss", f"{seg.in_:.3f}", "-t", f"{src_dur + 0.25:.3f}", "-i", str(src.resolve())]
    audio_in = "0:a"
    if seg.hold:  # freeze frame: one frame held for the segment's length, silent
        args = ["-ss", f"{seg.in_:.3f}", "-i", str(src.resolve()),
                "-f", "lavfi", "-t", f"{src_dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        audio_in = "1:a"
    elif not info.has_audio:
        args += ["-f", "lavfi", "-t", f"{src_dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        audio_in = "1:a"

    graph: list[str] = []
    post = [*color_filters(plan, seg.source), *motion_filters(plan.effects, entry.index, w, h, entry.duration, fps)]
    base_speed = seg.speed
    if ramp is not None and ramp.strength != 1.0:
        # first half at base speed, second half at base*ramp (both video and audio)
        half = src_dur / 2
        s2 = base_speed * ramp.strength
        graph.append("[0:v]split=2[va][vb]")
        graph.append(f"[va]trim=0:{half:.3f},setpts=(PTS-STARTPTS)/{base_speed:.4f}[va2]")
        graph.append(f"[vb]trim={half:.3f}:{src_dur:.3f},setpts=(PTS-STARTPTS)/{s2:.4f}[vb2]")
        graph.append("[va2][vb2]concat=n=2:v=1:a=0[vsp]")
        a1 = ",".join(["atrim=0:%.3f" % half, "asetpts=PTS-STARTPTS", *atempo_chain(base_speed)])
        a2 = ",".join(["atrim=%.3f:%.3f" % (half, src_dur), "asetpts=PTS-STARTPTS", *atempo_chain(s2)])
        graph.append(f"[{audio_in}]asplit=2[aa][ab]")
        graph.append(f"[aa]{a1}[aa2]")
        graph.append(f"[ab]{a2}[ab2]")
        graph.append("[aa2][ab2]concat=n=2:v=0:a=1[asp]")
    elif seg.hold:
        graph.append(f"[0:v]trim=end_frame=1,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={src_dur:.3f}[vsp]")
        graph.append(f"[{audio_in}]asetpts=PTS-STARTPTS[asp]")
    else:
        # reversed segments: reverse first (frames still in source time), then apply speed
        vrev, arev = (["reverse"], ["areverse"]) if seg.reverse else ([], [])
        graph.append("[0:v]" + ",".join(["setpts=PTS-STARTPTS", f"trim=0:{src_dur:.3f}", *vrev,
                                         f"setpts=(PTS-STARTPTS)/{base_speed:.4f}"]) + "[vsp]")
        graph.append(f"[{audio_in}]" + ",".join(["asetpts=PTS-STARTPTS", f"atrim=0:{src_dur:.3f}", *arev,
                                                  "asetpts=PTS-STARTPTS", *atempo_chain(base_speed)]) + "[asp]")

    # drop to the output frame rate BEFORE scaling/grading: a 60 fps source then costs half the work;
    # rotate / mirror before the source is fitted into the canvas
    graph.append("[vsp]" + ",".join([f"fps={fps}", *orientation_filters(plan.canvas)]) + "[vfps]")
    subj = {e.type: e for e in plan.effects
            if e.type in ("follow", "person_zoom", "spotlight") and e.target == entry.index and e.points}
    rotated = plan.canvas.rotate in (90, 270)
    follow = subj.get("person_zoom") or subj.get("follow")
    if follow is not None and not rotated:
        graph.append(follow_crop(follow, info.width, info.height, w, h, "vfps", "vfr"))
    else:
        graph.append(reframe_filter(w, h, reframe, "vfps", "vfr"))
    if "spotlight" in subj and not rotated:
        post.append(spotlight_filter(subj["spotlight"], follow, info.width, info.height, w, h, reframe))
    vchain = [*post, f"fps={fps}", "format=yuv420p", "setsar=1"]
    graph.append("[vfr]" + ",".join(vchain) + "[vout]")
    # 30 ms fades at both edges of every segment: no clicks/pops at the cuts — except where the next piece
    # continues the same sound (a split): a fade there would be an audible dip
    # frame-exact length: every segment ends on the output frame grid of the WHOLE timeline (its frames =
    # round(end·fps) − round(start·fps)), picture and sound alike. Before, "-t 0.650" at 30 fps wrote 20 frames
    # (0.667 s) while the sound stayed 0.650 s: every cut came a little later than the music, the error added up
    # (measured +0.21 s after 25 beat cuts — the beat edit looked "off the beat", tools/beatcheck.py)
    n_frames, dur_q = segment_frames(entry, fps)
    edge = min(0.03, dur_q / 4)
    fin = "" if continues(plan, entry.index - 1) else f"afade=t=in:st=0:d={edge:.3f},"
    fout = "" if continues(plan, entry.index) else f",afade=t=out:st={max(0.0, dur_q - edge):.4f}:d={edge:.3f}"
    graph.append(f"[asp]volume={seg.volume:.3f},aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                 f"{fin}apad{fout},atrim=0:{dur_q:.6f}[aout]")
    args += ["-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]",
             "-frames:v", str(n_frames), "-t", f"{dur_q:.6f}", "-r", str(fps), *inter_v(plan), *INTERMEDIATE_A,
             str(out.resolve())]
    # cwd = LUT folder so `lut3d=file=<look>.cube` needs no Windows drive-letter escaping
    uses_lut = plan.color.preset in LOOKS or any(e.type == "grade" and e.params.get("look") and e.target in (-1, entry.index)
                                                  for e in plan.effects)
    run_ffmpeg(args, cwd=LUT_DIR if uses_lut else None)
    return out


def join_segments(plan: EditPlan, parts: list[Path], out: Path) -> Path:
    """Join intermediates with xfade/acrossfade where the plan asks for transitions, concat elsewhere."""
    timeline = plan.timeline()
    if len(parts) == 1:
        shutil.copyfile(parts[0], out)
        return out
    if not any(t.after >= 0 for t in plan.transitions):
        # no cross-transitions: intermediates share codec settings (PCM sound, see INTERMEDIATE_A), so join by
        # stream copy (no re-encode, no gap at the cuts)
        listing = out.with_suffix(".txt")
        listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
        run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)])
        return out
    args: list[str] = []
    for p in parts:
        args += ["-i", str(p)]
    # one timebase for every piece: concat outputs 1/1000000, encoded segments 1/15360 — xfade refuses to mix them
    # (a crossfade right after a hard cut failed on a travel edit)
    graph: list[str] = [f"[{k}:v]settb=AVTB[s{k}]" for k in range(len(parts))]
    v_prev, a_prev = "s0", "0:a"
    for k in range(1, len(parts)):
        t = next((t for t in plan.transitions if t.after == k - 1), None)
        v_out, a_out = f"v{k}", f"a{k}"
        if t is not None:
            # offset = when segment k starts in the output timeline
            offset = frame_time(timeline[k].start, plan.canvas.fps)  # the same frame grid as the segments
            graph.append(f"[{v_prev}][s{k}]xfade=transition={xfade_name(t.type)}:duration={t.duration:.3f}:offset={offset:.3f}[{v_out}]")
            graph.append(f"[{a_prev}][{k}:a]acrossfade=d={t.duration:.3f}:c1=tri:c2=tri[{a_out}]")
        else:
            graph.append(f"[{v_prev}][s{k}]concat=n=2:v=1:a=0[{v_out}]")
            graph.append(f"[{a_prev}][{k}:a]concat=n=2:v=0:a=1[{a_out}]")
        v_prev, a_prev = v_out, a_out
    # transitions with their own look over the overlap (whip blur, glitch tear): filters enabled in the window only
    post: list[str] = []
    for t in plan.transitions:
        fx = TRANSITIONS_BY_ID.get(t.type)
        if t.after >= 0 and fx is not None and fx.post is not None:
            a = timeline[t.after + 1].start
            post += fx.post(a, a + t.duration)
    if post:
        graph.append(f"[{v_prev}]" + ",".join(post) + "[vpost]")
        v_prev = "vpost"
    args += ["-filter_complex", ";".join(graph), "-map", f"[{v_prev}]", "-map", f"[{a_prev}]",
             *inter_v(plan), *INTERMEDIATE_A, str(out)]
    run_ffmpeg(args)
    return out


def _is_digital_silence(path: Path) -> bool:
    log = run_ffmpeg(["-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", log)
    return m is None or m.group(1) == "-inf" or float(m.group(1)) < -90


def _ffcolor(hex_rgb: str) -> str:
    return "0x" + hex_rgb[1:]


def overlay_graph(plan: EditPlan, src: str, w: int, h: int, total: float) -> tuple[list[str], str]:
    """Filter-graph parts that draw each Overlay on top of `src`. Returns (parts, output label).

    Every layer is an FFmpeg `gradients` source (2–4 colours, slowly rotating or drifting), shaped by a
    mask: full frame for a wash, a blurred border for a glow frame, a bottom band for a bar.
    """
    parts: list[str] = []
    label = src
    fps = plan.canvas.fps
    k = min(w, h) / 720
    for i, ov in enumerate(plan.overlays):
        d = max(0.1, ov.end - ov.start)
        cols = ":".join(f"c{j}={_ffcolor(c)}" for j, c in enumerate(ov.colors))
        line = f":x0=0:y0=0:x1=0:y1={h}" if ov.motion == "drift" else ""
        speed = 0.0 if ov.motion == "static" else ov.speed
        parts.append(f"gradients=s={w}x{h}:{cols}:nb_colors={len(ov.colors)}{line}:seed=7:speed={speed:.4f}:r={fps}:d={d:.3f},"
                     f"format=rgba,setpts=PTS+{ov.start:.3f}/TB[g{i}]")
        t = max(2, int(round(ov.thickness * k)))
        if ov.kind == "wash":
            parts.append(f"[g{i}]colorchannelmixer=aa={ov.opacity:.3f}[o{i}]")
        else:
            box = (f"drawbox=x=0:y=0:w=iw:h=ih:color=white:t={t}" if ov.kind == "glow_frame"
                   else f"drawbox=x=0:y={h - t}:w=iw:h={t}:color=white:t=fill")
            blur = max(1.0, t * 0.6)
            # the mask never changes: draw + blur ONE frame and repeat it (blurring every frame cost ~15 s per
            # 30 s of 720p output for each glow layer — measured; this way it is ~0.2 s)
            parts.append(f"color=c=black:s={w}x{h}:r={fps}:d={1.5 / fps:.4f},{box},gblur=sigma={blur:.1f},"
                         f"loop=loop=-1:size=1,trim=duration={d:.3f},setpts=PTS+{ov.start:.3f}/TB[m{i}]")
            parts.append(f"[g{i}][m{i}]alphamerge,colorchannelmixer=aa={ov.opacity:.3f}[o{i}]")
        nxt = f"ov{i}"
        parts.append(f"[{label}][o{i}]overlay=eof_action=pass:enable='between(t,{ov.start:.3f},{ov.end:.3f})'[{nxt}]")
        label = nxt
    return parts, label


def _fonts_dir_for(work: Path) -> str:
    """Bundled fonts folder as seen from the ASS working dir (relative: no Windows drive-letter escaping)."""
    from .text_styles import FONT_DIR

    try:
        return os.path.relpath(FONT_DIR, work).replace("\\", "/")
    except ValueError:  # different drive on Windows
        return FONT_DIR.as_posix().replace(":", "\\:")


def finish(plan: EditPlan, joined: Path, out: Path, work: Path, music_path: Path | None,
           mask_dir: Path | None = None, geom: str | None = None, sources: dict[str, Path] | None = None,
           gen_dir: Path | None = None) -> Path:
    """Fades, text overlay (ASS/libass), music + ducking + voice cleanup + loudness, final encode.

    `mask_dir` + `geom` (the cut's geometry key): person cut-outs are kept per cut, so a colour / text / sound
    change does not cut the people out again (that was 60-90 s of every such edit)."""

    def mask_file(kind: str, key: str) -> tuple[Path, bool]:
        if mask_dir is not None and geom:
            mask_dir.mkdir(parents=True, exist_ok=True)
            f = mask_dir / f"mask_{geom}_{kind}_{key}.mkv"
            return f, f.exists()
        f = joined.parent / f"{joined.stem}_{kind}_{key}.mkv"
        return f, f.exists() and f.stat().st_mtime >= joined.stat().st_mtime
    w, h = plan.canvas.size
    total = plan.total_duration()
    vf: list[str] = []
    for t in plan.transitions:
        if t.after == FADE_IN:
            vf.append(f"fade=t=in:st=0:d={t.duration:.3f}")
        elif t.after == FADE_OUT:
            vf.append(f"fade=t=out:st={max(0.0, total - t.duration):.3f}:d={t.duration:.3f}")
    behind = [t for t in plan.text if t.behind] if segmentation.available() else []
    front = [t for t in plan.text if t not in behind]
    if front:
        (work / "text.ass").write_text(build_ass(front, w, h), encoding="utf-8")
        # relative filename + cwd=work avoids Windows drive-letter escaping problems in the filter
        vf.append(f"subtitles=text.ass:fontsdir='{_fonts_dir_for(work)}'")
    vf += ["format=yuv420p"]

    a = plan.audio
    args = ["-i", str(joined.resolve())]
    voice: list[str] = []
    if a.voice_cleanup:
        rnn = Path(__file__).resolve().parent.parent / "assets" / "models" / "rnnoise_sh.rnnn"
        if rnn.exists():  # RNNoise (trained on speech in recording noise): wind, fans, crowd hum
            shutil.copyfile(rnn, work / "rnn.rnnn")  # relative name + cwd=work: no Windows drive-letter escaping
            voice = ["highpass=f=80", "arnndn=m=rnn.rnnn"]
        else:
            voice = ["highpass=f=80", "afftdn=nf=-25"]
    if a.voice_volume != 1.0:  # "voice tej karo": louder than the music bed (loudnorm keeps the total on target)
        voice.append(f"volume={a.voice_volume:.2f}")
    from .render_tools import audio_edit_graph, audio_tool_filters, graphics_graph, sfx_graph

    voice += audio_tool_filters(plan)  # Tier 1: denoise, speech EQ, volume ranges, reverb
    for t in plan.transitions:
        if t.after == FADE_IN:
            voice.append(f"afade=t=in:st=0:d={t.duration:.3f}")
        elif t.after == FADE_OUT:
            voice.append(f"afade=t=out:st={max(0.0, total - t.duration):.3f}:d={t.duration:.3f}")
    if a.mute:
        voice = ["volume=0"]  # original sound off; an audio track is still written
    graph, base = overlay_graph(plan, "0:v", w, h, total)  # animated gradient graphic tracks under the text
    masks: list[Path] = []  # extra inputs, referenced as [{MASK0}:v], [{MASK1}:v] …
    if plan.focus is not None and segmentation.available():
        # main focus: the chosen person stays sharp, the rest is blurred (or darkened) — cut out every frame
        f = plan.focus
        fkey = hashlib.sha1(json.dumps([f.mode, f.color, segmentation.SEG_VERSION]).encode()).hexdigest()[:10]
        fmask, fresh = mask_file("focus", fkey)
        if not fresh:
            segmentation.mask_video(joined, [(0.0, total)], fmask, color=f.color, only_one=True)
        masks.append(fmask)
        rest = "boxblur=luma_radius=18:luma_power=2:chroma_radius=10" if f.mode == "blur" else \
            "eq=brightness=-0.18:saturation=0.55"
        graph.append(f"[{base}]split=2[fo_a][fo_b]")
        graph.append(f"[fo_a]{rest}[fo_bg]")
        graph.append(f"[{{MASK{len(masks) - 1}}}:v]format=gray,scale={w}:{h},boxblur=3[fo_m]")
        graph.append("[fo_b][fo_m]alphamerge[fo_p]")
        graph.append("[fo_bg][fo_p]overlay=format=auto:shortest=1[fo_out]")
        base = "fo_out"
    if behind:
        # text BEHIND people: draw it, then put the people (cut out with their mask) back on top of it
        windows = [(t.start, t.end) for t in behind]
        # kept next to the (cached) picture: a sound or text-style change doesn't cut the person out again
        mkey = hashlib.sha1(json.dumps(windows).encode()).hexdigest()[:10]
        mask, fresh = mask_file("mask", mkey)
        if not fresh:
            segmentation.mask_video(joined, windows, mask)
        # a word the person would hide (close-up: they fill the middle) is drawn in FRONT instead — behind a face
        # that fills the frame, a lyric poster showed no words at all
        hidden = covered_items(mask, behind, total)
        if hidden:
            (work / "front2.ass").write_text(build_ass(hidden, w, h), encoding="utf-8")
            behind = [t for t in behind if t not in hidden]
        if behind:
            (work / "behind.ass").write_text(build_ass(behind, w, h), encoding="utf-8")
            masks.append(mask)
            graph.append(f"[{base}]split=2[bh_a][bh_b]")
            graph.append(f"[bh_a]subtitles=behind.ass:fontsdir='{_fonts_dir_for(work)}'[bh_t]")
            graph.append(f"[{{MASK{len(masks) - 1}}}:v]format=gray,scale={w}:{h}[bh_m]")
            graph.append("[bh_b][bh_m]alphamerge[bh_p]")
            graph.append("[bh_t][bh_p]overlay=format=auto:shortest=1[bh_out]")
            base = "bh_out"
        if hidden:
            graph.append(f"[{base}]subtitles=front2.ass:fontsdir='{_fonts_dir_for(work)}'[bh_front]")
            base = "bh_front"
    gfx_lines, gfx_inputs, base = graphics_graph(plan, sources or {}, base, w, h, total, work,
                                                 gen_dir.parent if gen_dir is not None else None)
    graph += gfx_lines
    stickers = sticker_inputs(plan, work)
    for k, (st, _png) in enumerate(stickers):
        graph += sticker_graph(st, k, base, w, h)
        base = f"stk_out{k}"
    graph.append(f"[{base}]" + ",".join(vf) + "[vout]")
    # THE SOUND IS MADE IN ITS OWN PASS (audio only → WAV), then muxed with the picture. Encoding both in one
    # graph left the sound with a jump at every cut: ~70 ms in older edits, and 3 s once loudnorm (3 s look-ahead)
    # met it (measured 5.10 s → 8.09 s with picture; an audio-only pass of the same graph is gap-free).
    agraph: list[str] = []
    a_args = ["-i", str(joined.resolve())]
    # timestamps from the sample count: the pieces' packet times overlap by a few ms at each cut
    agraph.append("[0:a]" + ",".join(["asetpts=N/SR/TB", *voice]) + "[voice0]")
    aux_lines, _aux_inputs, vlab = ([], [], "voice0") if a.mute else audio_edit_graph(plan, sources or {}, "voice0", work)
    agraph += aux_lines
    sfx_lines, _sfx_inputs, sfx_lab = sfx_graph(plan, gen_dir or work, total)
    agraph += sfx_lines
    if sfx_lab:
        agraph.append(f"[{vlab}][{sfx_lab}]amix=inputs=2:duration=first:normalize=0[voice]")
    else:
        agraph.append(f"[{vlab}]anull[voice]")
    loud = f"loudnorm=I={a.target_lufs}:TP=-1.5:LRA=11,aresample=48000"
    if music_path is None and (a.mute or _is_digital_silence(joined)):
        loud = "aresample=48000"  # loudnorm turns pure digital silence into NaN samples
    if a.bass_boost > 0:  # low shelf around 100 Hz before loudness normalisation (so the level stays on target)
        loud = f"bass=g={a.bass_boost:.1f}:f=100:w=0.6,{loud}"
    # whole-mix audio fades (independent of video fade transitions)
    if a.fade_in > 0:
        loud += f",afade=t=in:st=0:d={min(a.fade_in, total / 2):.3f}"
    if a.fade_out > 0:
        d = min(a.fade_out, total / 2)
        loud += f",afade=t=out:st={max(0.0, total - d):.3f}:d={d:.3f}"

    if music_path is not None:
        if a.music_start > 0:
            a_args += ["-ss", f"{a.music_start:.3f}"]
        a_args += ["-stream_loop", "-1", "-i", str(music_path.resolve())]
        fade_start = max(0.0, total - 1.0)
        agraph.append(f"[1:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,aresample=48000,"
                     f"aformat=sample_fmts=fltp:channel_layouts=stereo,volume={a.music_volume:.3f},"
                     f"afade=t=out:st={fade_start:.3f}:d=1[mus]")
        if a.ducking:
            # music drops duck_amount_db while someone speaks. The sidechain is gated (no noise between words),
            # boosted and limited to a fixed level, so the depth is what was asked whatever the voice's loudness
            # (before: depth followed the voice, 3-18 dB, and "20 dB" vs "6 dB" differed by 1-3 dB). Calibrated
            # with tone bursts at -29 / -23 / -13 dBFS: asked 6 / 12 / 20 -> 6.2 / 12.2 / 20.2 dB at every level.
            agraph.append("[voice]asplit=2[v1][vsc]")
            agraph += duck_graph("mus", "vsc", "duck", a.duck_amount_db)
            agraph.append(f"[v1][duck]amix=inputs=2:duration=first:normalize=0,{loud}[amain]")
        else:
            agraph.append(f"[voice][mus]amix=inputs=2:duration=first:normalize=0,{loud}[amain]")
    else:
        agraph.append(f"[voice]{loud}[amain]")
    # a noise floor ~ -94 dBFS (inaudible): pure digital silence encodes to 6-byte AAC frames that Chrome failed to
    # decode ("PIPELINE_ERROR_DECODE … audio packet") — the user's silent reel stopped at 2.3 s in the app
    agraph.append(f"anoisesrc=d={total + 0.5:.3f}:c=pink:a=0.00002:r=48000,"
                  "aformat=sample_fmts=fltp:channel_layouts=stereo[nfloor]")
    # a final brick-wall limiter: one-pass loudnorm at -14 LUFS overshot to +0.2 dBFS true peak on a podcast clip
    # (audible clipping on phones); 0.85 (-1.4 dBFS) still decoded at 0.0 dBFS on a loud voice+music mix ("make it
    # louder"): AAC overshoots up to ~1.5 dB, so 0.79 (-2 dBFS)
    agraph.append("[amain][nfloor]amix=inputs=2:duration=first:normalize=0,"
                  "alimiter=limit=0.79:attack=5:release=50:level=false,apad=whole_dur=" + f"{total:.3f}[aout]")
    mix = work / "mix.wav"
    run_ffmpeg([*a_args, "-filter_complex", ";".join(agraph), "-map", "[aout]", "-c:a", "pcm_s16le", "-ar", "48000",
                "-ac", "2", "-t", f"{total:.3f}", str(mix.resolve())], cwd=work)
    args += ["-i", str(mix.resolve())]
    first = 2
    for k, m in enumerate(masks):
        args += ["-i", str(m.resolve())]
        graph = [g.replace(f"[{{MASK{k}}}:v]", f"[{first + k}:v]") for g in graph]
    first += len(masks)
    for k, (_st, png) in enumerate(stickers):
        args += ["-loop", "1", "-framerate", str(plan.canvas.fps), "-t", f"{total:.3f}", "-i", str(png.resolve())]
        graph = [g.replace(f"[{{STK{k}}}:v]", f"[{first + k}:v]") for g in graph]
    first += len(stickers)
    for tag, extra, kind in (("GFX", gfx_inputs, "v"),):
        for k, inp in enumerate(extra):
            args += inp
            graph = [g.replace(f"[{{{tag}{k}}}:{kind}]", f"[{first + k}:{kind}]") for g in graph]
        first += len(extra)
    e = plan.export
    args += ["-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "1:a",
             "-c:v", e.video_codec, "-preset", e.preset, "-crf", str(e.crf), "-pix_fmt", "yuv420p",
             # capped quality: film grain / noise otherwise takes 30+ Mbit/s (a 51 s old-movie edit was 234 MB)
             *([] if e.is_master else  # original quality: the CRF alone decides, no bitrate ceiling
               ["-maxrate", f"{e.max_bitrate_kbps}k", "-bufsize", f"{2 * e.max_bitrate_kbps}k"] if e.max_bitrate_kbps else
               ["-maxrate", f"{max_mbps(plan.canvas.resolution)}M", "-bufsize", f"{2 * max_mbps(plan.canvas.resolution)}M"]),
             "-r", str(plan.canvas.fps), "-c:a", "aac", "-b:a", e.audio_bitrate, "-ar", "48000",
             "-t", f"{total:.3f}", "-movflags", "+faststart", str(out.resolve())]
    run_ffmpeg(args, cwd=work)
    return out


# share of a centred word's box the person covers (on average) before it moves in front. Measured: on a lyric poster
# close-up words at 0.65-1.0 coverage were unreadable behind the face; a word at 0.52 reads fine behind a person
COVER_LIMIT = 0.6


def covered_items(mask: Path, items: list[Any], total: float) -> list[Any]:
    """Behind-the-person words that the person would mostly hide (their box is the middle band of the frame)."""
    import numpy as np

    mw, mh, fps = 36, 64, 5
    try:
        raw = subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-i", str(mask), "-vf",
                              f"fps={fps},scale={mw}:{mh}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             capture_output=True, timeout=120).stdout
    except Exception:  # noqa: BLE001 — no measurement: keep the user's choice
        return []
    n = len(raw) // (mw * mh)
    if n == 0:
        return []
    frames = np.frombuffer(raw[: n * mw * mh], dtype=np.uint8).reshape(n, mh, mw) > 127
    out = []
    for t in items:
        if t.style.position != "center":
            continue
        a, b = int(t.start * fps), max(int(t.start * fps) + 1, int(t.end * fps))
        band = frames[a:b, int(mh * 0.38):int(mh * 0.62), int(mw * 0.08):int(mw * 0.92)]
        if band.size and float(band.mean()) > COVER_LIMIT:
            out.append(t)
    return out


STICKER_POP = 0.25  # s of the pop-in / fade-out


def sticker_inputs(plan: EditPlan, work: Path) -> list[tuple[Any, Path]]:
    """Each sticker's PNG (drawn once per emoji, cached in the work dir). No emoji font -> no stickers (said, not hidden)."""
    from . import stickers as stk

    if not plan.stickers or not stk.available():
        return []
    out = []
    for st in plan.stickers:
        name = "stk_" + "_".join(f"{ord(c):x}" for c in st.emoji) + ".png"
        out.append((st, stk.render_png(st.emoji, work / name)))
    return out


def sticker_graph(st: Any, k: int, base: str, w: int, h: int) -> list[str]:
    """Overlay one sticker on [base]: fades in with a small bounce (drops 6 % of its size and settles), fades out."""
    side = max(24, int(round(min(w, h) * st.size)))
    m = int(round(min(w, h) * 0.05))
    a, b = st.start, st.end
    d = min(STICKER_POP, (b - a) / 3)
    x = {"top_left": f"{m}", "bottom_left": f"{m}", "center": "(W-w)/2"}.get(st.position, f"W-w-{m}")
    y0 = {"bottom_left": f"H-h-{m}", "bottom_right": f"H-h-{m}", "center": "(H-h)/2"}.get(st.position, f"{m}")
    bounce = f"{side * 0.06:.1f}*exp(-(t-{a:.3f})*7)*abs(cos((t-{a:.3f})*14))"
    return [
        f"[{{STK{k}}}:v]format=rgba,scale={side}:-1,fade=t=in:st={a:.3f}:d={d:.3f}:alpha=1,"
        f"fade=t=out:st={max(a, b - d):.3f}:d={d:.3f}:alpha=1[stk{k}]",
        f"[{base}][stk{k}]overlay=x={x}:y={y0}-{bounce}:eval=frame:format=auto:"
        f"enable='between(t,{a:.3f},{b:.3f})'[stk_out{k}]",
    ]


def max_mbps(short_side: int) -> int:
    """Upper video bitrate (Mbit/s) — about what Instagram / YouTube keep anyway."""
    return 40 if short_side >= 2160 else 20 if short_side >= 1440 else 12 if short_side >= 1080 else 6 if short_side >= 720 else 3


def render_workers() -> int:
    """How many segments render at once (RENDER_WORKERS env var; default: a third of the CPU threads, 2-4)."""
    env = os.environ.get("RENDER_WORKERS", "").strip()
    if env.isdigit() and int(env) > 0:
        return int(env)
    return max(2, min(4, (os.cpu_count() or 2) // 3))


# effects that only change colour / texture: the people are where they were (their cut-out can be reused)
COLOUR_ONLY_FX = {"mono", "silhouette", "invert_mono", "film_bw", "film_grain", "vignette", "sharpen", "old_film",
                  "vhs", "posterize", "negative", "color_pop", "duotone_blue_pink", "duotone_teal_gold", "dreamy",
                  "thermal", "night_vision", "scanlines", "flash", "strobe"}


def geometry_key(plan: EditPlan, sources: dict[str, Path]) -> str:
    """Where every pixel comes from (cuts, canvas, moving effects, transitions) — not its colour."""
    p2 = plan.model_copy(deep=True)
    p2.color = type(plan.color)()
    p2.effects = [e for e in plan.effects if e.type not in COLOUR_ONLY_FX]
    return "g" + picture_key(p2, sources)[:16]


def picture_key(plan: EditPlan, sources: dict[str, Path]) -> str:
    """Everything that shapes the joined picture (cuts, canvas, colour, effects, cross transitions, sources).
    Text, overlays, music and fades are applied later in `finish`, so they are not part of it."""
    src = {k: f"{p.resolve()}|{p.stat().st_size}|{p.stat().st_mtime_ns}" for k, p in sorted(sources.items()) if p.exists()}
    data = {"canvas": plan.canvas.model_dump(), "clips": [c.model_dump(by_alias=True) for c in plan.clips],
            "effects": [e.model_dump() for e in plan.effects], "color": plan.color.model_dump(),
            "transitions": [t.model_dump() for t in plan.transitions if t.after >= 0], "sources": src,
            "v": 2, "master": plan.export.is_master}  # 2: frame-exact segment lengths + the sharper beat punch
    return hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:20]


def render(plan: EditPlan, sources: dict[str, Path], work: Path, out: Path,
           music_dir: Path | list[Path] | None = None, progress: ProgressFn | None = None,
           cache_dir: Path | None = None) -> Path:
    """Execute the full plan. `sources` maps clip id → file path.

    With `cache_dir`, the joined picture is kept: a later render whose cuts/colour/effects are the same (e.g. only
    captions, text style, music or a title changed) skips every segment and only runs the final pass."""
    work.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    report = progress or (lambda p, m: None)
    missing = [s.source for s in plan.clips if s.source not in sources]
    if missing:
        raise RenderError(f"plan references unknown clips: {sorted(set(missing))}")
    music_path: Path | None = None
    if plan.audio.music:
        dirs = music_dir if isinstance(music_dir, list) else [music_dir] if music_dir else []
        music_path = next((d / plan.audio.music for d in dirs if (d / plan.audio.music).is_file()),
                          None if dirs else Path(plan.audio.music))
        if music_path is None or not music_path.is_file():
            raise RenderError(f"music track not found: {plan.audio.music}")

    timeline = plan.timeline()
    n = len(timeline)
    cached = cache_dir / f"joined_{picture_key(plan, sources)}.mp4" if cache_dir is not None else None
    geom = geometry_key(plan, sources) if cache_dir is not None else None
    if cached is not None and cached.exists():
        report(0.5, "reusing the cut (only text / audio changed)")
        return _finish_and_export(plan, cached, work, out, music_path, report, cache_dir, geom, sources)
    done = 0
    lock = threading.Lock()

    def one(entry: Any) -> Path:
        nonlocal done
        part = render_segment(plan, entry, sources[entry.segment.source], work / f"seg_{entry.index:03d}.mp4")
        with lock:
            done += 1
            report(done / (n + 2), f"rendering segment {done}/{n}")
        return part

    # segments are independent FFmpeg runs, mostly start-up + seek bound: a few at once is much faster
    # (37 one-second cuts: ~75 s one by one on the test laptop). Order is kept by map().
    report(0.0, f"rendering {n} segments")
    with ThreadPoolExecutor(max_workers=max(1, min(render_workers(), n))) as pool:
        parts = list(pool.map(one, timeline))
    report(len(timeline) / (len(timeline) + 2), "joining segments")
    joined = join_segments(plan, parts, work / "joined.mp4")
    if cached is not None:
        cached.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(joined, cached)
        for old in sorted(cached.parent.glob("joined_*.mp4"), key=lambda q: q.stat().st_mtime)[:-4]:
            old.unlink(missing_ok=True)  # keep the 4 newest cuts per project
    report((len(timeline) + 1) / (len(timeline) + 2), "adding text, music and final encode")
    return _finish_and_export(plan, joined, work, out, music_path, report, cache_dir, geom, sources)


def _finish_and_export(plan: EditPlan, joined: Path, work: Path, out: Path, music_path: Path | None,
                       report: ProgressFn, cache_dir: Path | None = None, geom: str | None = None,
                       sources: dict[str, Path] | None = None) -> Path:
    tmp_out = work / "final.mp4"
    gen_dir = cache_dir.parent / "generated" if cache_dir is not None else work / "generated"
    finish(plan, joined, tmp_out, work, music_path, cache_dir / "masks" if cache_dir is not None else None, geom,
           sources, gen_dir)
    if plan.audio.exact_loudness or plan.audio.gain_db != 0:
        report(0.97, "measuring the loudness")
        correct_loudness(tmp_out, plan.audio.target_lufs + plan.audio.gain_db, work)
    if cache_dir is not None:  # keep the 12 newest cut-outs per project
        for old in sorted((cache_dir / "masks").glob("mask_*.mkv"), key=lambda q: q.stat().st_mtime)[:-12]:
            old.unlink(missing_ok=True)
    shutil.move(str(tmp_out), str(out))
    if plan.export.extras:
        report(0.98, "exporting " + " + ".join(x.upper() for x in plan.export.extras))
        export_extras(plan, out)
    report(1.0, "render complete")
    return out


def correct_loudness(path: Path, target: float, work: Path, tol: float = 1.0) -> float:
    """Measure the finished mix and correct its level to `target` LUFS (picture copied, sound re-encoded).
    One-pass loudnorm lands 2-5 dB short on dynamic speech; a measured static gain + a soft limiter does not.
    Returns the final measured LUFS."""
    from .ffmpeg_utils import measure_loudness

    target = min(target, -9.0)  # louder than -9 LUFS only clips: platforms turn it down anyway
    lufs = measure_loudness(path).get("lufs", -99.0)
    for _ in range(3):
        if lufs <= -70 or abs(lufs - target) <= tol:
            break
        gain = target - lufs
        tmp = work / "loud_fix.mp4"
        # gain, then a compressor that only touches peaks, then the brick-wall limiter (-2 dBFS, see finish())
        run_ffmpeg(["-i", str(path), "-map", "0:v", "-map", "0:a", "-c:v", "copy", "-af",
                    f"volume={gain:.2f}dB,acompressor=threshold=0.35:ratio=4:attack=2:release=80:makeup=1,"
                    "alimiter=limit=0.79:attack=3:release=60:level=false",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(tmp)])
        shutil.move(str(tmp), str(path))
        lufs = measure_loudness(path).get("lufs", -99.0)
    return lufs


GIF_MAX_SECONDS = 15.0


def extra_path(out: Path, kind: str) -> Path:
    return out.with_suffix(f".{kind}")


def duck_graph(music: str, voice: str, out: str, amount_db: float) -> list[str]:
    """Filter-graph lines that lower [music] by amount_db while [voice] is speaking, written to [out]."""
    thr = 10 ** ((-12.8 - amount_db / 0.95) / 20)
    return [f"[{voice}]agate=threshold=0.01:range=0:attack=5:release=120,volume=40dB,"
            f"alimiter=limit=0.25:attack=5:release=60:level=0[{voice}_lim]",
            f"[{music}][{voice}_lim]sidechaincompress=threshold={thr:.6f}:ratio=20:attack=15:release=350[{out}]"]


def export_extras(plan: EditPlan, out: Path) -> list[Path]:
    """GIF (≤15 s, 480 px wide, 12 fps, optimised palette) and/or MP3 of the final mix, next to the MP4."""
    made: list[Path] = []
    if "gif" in plan.export.extras:
        gif = extra_path(out, "gif")
        w = 480 if plan.canvas.size[0] >= plan.canvas.size[1] else 270
        run_ffmpeg(["-t", f"{min(GIF_MAX_SECONDS, plan.total_duration()):.3f}", "-i", str(out), "-vf",
                    f"fps=12,scale={w}:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer",
                    "-loop", "0", str(gif)])
        made.append(gif)
    if "mp3" in plan.export.extras:
        mp3 = extra_path(out, "mp3")
        run_ffmpeg(["-i", str(out), "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(mp3)])
        made.append(mp3)
    if "wav" in plan.export.extras:
        wav = extra_path(out, "wav")
        run_ffmpeg(["-i", str(out), "-vn", "-c:a", "pcm_s16le", "-ar", "48000", str(wav)])
        made.append(wav)
    if "thumbnail" in plan.export.extras:
        jpg = extra_path(out, "jpg")
        at = plan.export.thumbnail_at if plan.export.thumbnail_at is not None else plan.total_duration() / 3
        run_ffmpeg(["-ss", f"{at:.3f}", "-i", str(out), "-frames:v", "1", "-q:v", "2", str(jpg)])
        made.append(jpg)
    if "srt" in plan.export.extras:
        srt = extra_path(out, "srt")
        caps = sorted((t for t in plan.text if t.kind == "caption"), key=lambda t: t.start)

        def ts(x: float) -> str:
            ms = int(round(x * 1000))
            return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
        srt.write_text("".join(f"{i}\n{ts(c.start)} --> {ts(c.end)}\n{c.text}\n\n" for i, c in enumerate(caps, 1)),
                       encoding="utf-8")
        made.append(srt)
    if "m4a" in plan.export.extras:
        m4a = extra_path(out, "m4a")
        run_ffmpeg(["-i", str(out), "-vn", "-c:a", "copy", str(m4a)])
        made.append(m4a)
    return made
