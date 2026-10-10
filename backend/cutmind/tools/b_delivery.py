"""I. Analysis and delivery — scene detection, platform export presets, stabilisation, boomerang loop, thumbnail,
.srt captions.

Platform numbers were checked on 2026-10-09 against public spec guides (third-party; the platforms change them —
re-check before launch): Instagram Reels / YouTube Shorts 1080x1920 9:16, 30 fps, H.264 + AAC, ≤ 3 min;
WhatsApp Status: guides disagree (30 / 60 / 90 s) — we use the safe 30 s and ~16 MB (720p).
"""

from __future__ import annotations

from typing import Any

from ..plan import EditPlan, Effect
from .engine import ToolCtx, tool
from .timeline import ToolError, isolate, split_at
from .timewin import When

PLATFORMS: dict[str, dict[str, Any]] = {
    "instagram_reels": {"aspect": "9:16", "res": 1080, "fps": 30, "max_s": 180, "kbps": 8000, "crf": 21, "label": "Instagram Reels"},
    "youtube_shorts": {"aspect": "9:16", "res": 1080, "fps": 30, "max_s": 180, "kbps": 10000, "crf": 20, "label": "YouTube Shorts"},
    "whatsapp_status": {"aspect": "9:16", "res": 720, "fps": 30, "max_s": 30, "kbps": 3800, "crf": 26, "label": "WhatsApp Status"},
    "youtube": {"aspect": "16:9", "res": 1080, "fps": 30, "max_s": None, "kbps": 12000, "crf": 20, "label": "YouTube (long form)"},
    "linkedin": {"aspect": "1:1", "res": 1080, "fps": 30, "max_s": 600, "kbps": 8000, "crf": 22, "label": "LinkedIn feed"},
    "instagram_feed": {"aspect": "4:5", "res": 1080, "fps": 30, "max_s": 60, "kbps": 8000, "crf": 21, "label": "Instagram feed (4:5)"},
}


@tool("scene_detect")
def scene_detect(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    """Cut the shots wherever the picture changes scene (PySceneDetect, measured on each clip)."""
    if ctx.analysis is None:
        raise ToolError("scene detection needs the clip analysis, which is not available here")
    an = ctx.analysis()
    cuts: list[float] = []
    for e in plan.timeline():
        a = an.clips.get(e.segment.source)
        if a is None:
            continue
        for s in a.scenes:
            if e.segment.in_ + 0.3 < s < e.segment.out - 0.3:
                frac = (s - e.segment.in_) / e.segment.source_duration
                t = e.start + (1 - frac if e.segment.reverse else frac) * e.duration
                cuts.append(round(t, 3))
    done = 0
    for t in sorted(cuts, reverse=True):
        try:
            plan = split_at(plan, t)
            done += 1
        except ToolError:
            continue
    ctx.notes.append(f"{done} scene change(s) found and cut: {', '.join(f'{t:.1f}s' for t in sorted(cuts))}"
                     if done else "no scene change found")
    return plan


@tool("export_preset")
def export_preset(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    spec = PLATFORMS[p["platform"]]
    data = plan.to_json()
    data["canvas"].update(aspect_ratio=spec["aspect"], resolution=spec["res"] if p["quality"] == "high" else 720, fps=spec["fps"])
    data["export"].update(platform=p["platform"], crf=spec["crf"], max_bitrate_kbps=spec["kbps"], preset="veryfast",
                          audio_bitrate="128k")
    new = EditPlan.model_validate(data)
    w, h = new.canvas.size
    ctx.notes.append(f"{spec['label']}: {w}x{h}, {spec['fps']} fps, H.264 ≤ {spec['kbps'] / 1000:g} Mbit/s, AAC 128k")
    total = new.total_duration()
    if spec["max_s"] and total > spec["max_s"]:
        ctx.notes.append(f"the video is {total:.0f}s; {spec['label']} takes up to {spec['max_s']}s — shorten it "
                         f"('{spec['max_s']} sec ka karo') or it will be cut / rejected there")
    return new


@tool("stabilize")
def stabilize(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    if when.whole:
        targets = [-1]
    else:
        targets = []
        for a, b in when.windows:
            plan, got = isolate(plan, a, b)
            targets += got
    data = plan.to_json()
    for t in targets:
        data["effects"] = [e for e in data["effects"] if not (e["type"] == "stabilize" and e["target"] == t)]
        data["effects"].append(Effect(type="stabilize", target=t, strength=float(p["strength"])).model_dump())
    ctx.notes.append(f"stabilised (FFmpeg deshake, edges cropped {4 * float(p['strength']):.0f} %) ({when.describe()})")
    return EditPlan.model_validate(data)


@tool("loop_boomerang")
def loop_boomerang(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    """Forward, then the same backwards (and again `times` times): the Boomerang loop."""
    total = plan.total_duration()
    if total > 20:
        raise ToolError(f"a boomerang is for short moments: the edit is {total:.0f}s — trim it to ≤ 20s first")
    if any(t.after >= 0 for t in plan.transitions) or any(e.type == "speed_ramp" for e in plan.effects):
        raise ToolError("a boomerang needs hard cuts and no speed ramp")
    data = plan.to_json()
    order = sorted(data["clips"], key=lambda c: c["order"])
    seq = list(order)
    for k in range(int(p["times"])):
        back = [dict(c, reverse=not c["reverse"]) for c in reversed(order)]
        fwd = [dict(c) for c in order]
        seq += back + (fwd if k < int(p["times"]) - 1 else [])
    for i, c in enumerate(seq):
        c["order"] = i
    for c in seq:
        if c["reverse"] and c["out"] - c["in"] > 12.0:
            raise ToolError("one shot is longer than 12s — too long to play backwards")
    data["clips"] = seq
    data["effects"] = [e for e in data["effects"] if e["target"] < 0]
    data["audio_edits"] = []
    new = EditPlan.model_validate(data)
    ctx.notes.append(f"boomerang: forward + backwards x{p['times']} ({total:.1f}s → {new.total_duration():.1f}s)")
    return new


@tool("thumbnail")
def thumbnail(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    total = plan.total_duration()
    at = float(p["at"]) if p.get("at") is not None else round(total / 3, 2)
    if not 0 <= at < total:
        raise ToolError(f"{at:g}s is outside the video ({total:.1f}s)")
    data = plan.to_json()
    if "thumbnail" not in data["export"]["extras"]:
        data["export"]["extras"].append("thumbnail")
    data["export"]["thumbnail_at"] = at
    ctx.notes.append(f"cover image from {at:g}s (JPG next to the video)" + ("" if p.get("at") is not None else " — assumed a third in"))
    return EditPlan.model_validate(data)


@tool("srt_export")
def srt_export(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    if not any(t.kind == "caption" for t in plan.text):
        raise ToolError("there are no captions to save — add captions first")
    data = plan.to_json()
    if "srt" not in data["export"]["extras"]:
        data["export"]["extras"].append("srt")
    ctx.notes.append("captions also saved as an .srt file (upload it to YouTube for searchable subtitles)")
    return EditPlan.model_validate(data)
