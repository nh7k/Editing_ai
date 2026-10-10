"""B. Transitions — crossfade, fade through black / white, wipe, slide, zoom, whip pan, iris, glitch.

A transition sits on a cut (between two shots) and overlaps them by `duration`, so the video gets that much
shorter; captions / stickers keep their place inside their shots (timeline.remap_timed). "Fade in / out" at the
very start / end of the video is the same skill with where = start / end / start_end.
"""

from __future__ import annotations

from typing import Any

from ..plan import FADE_IN, FADE_OUT, EditPlan
from .engine import ToolCtx, tool
from .timeline import ToolError, remap_timed
from .timewin import When

MIN_OVERLAP = 0.12


def _cuts(plan: EditPlan, p: dict[str, Any], when: When) -> list[int]:
    n = len(plan.timeline())
    if p.get("cut") is not None:
        i = int(p["cut"]) - 1
        if not 0 <= i < n - 1:
            raise ToolError(f"cuts are numbered 1-{n - 1}")
        return [i]
    if when.windows and not when.whole:  # cuts inside the window(s)
        tl = plan.timeline()
        return [e.index for e in tl[:-1] if any(a - 0.05 <= e.end <= b + 0.05 for a, b in when.windows)]
    return list(range(n - 1))


def apply_transition(plan: EditPlan, kind: str, duration: float, p: dict[str, Any], when: When, ctx: ToolCtx,
                     label: str) -> EditPlan:
    tl = plan.timeline()
    if len(tl) < 2 and p.get("where", "cuts") == "cuts":
        raise ToolError("there is only one shot: no cut for a transition (try fade in / out at the start / end)")
    data = plan.to_json()
    cuts = _cuts(plan, p, when) if p.get("where", "cuts") == "cuts" else []
    done, short = 0, 0
    keep = [t for t in data["transitions"] if t["after"] not in cuts]
    for i in cuts:
        limit = 0.5 * min(tl[i].duration, tl[i + 1].duration) - 0.01
        if limit < MIN_OVERLAP:
            short += 1
            continue
        keep.append({"type": kind, "after": i, "duration": round(min(duration, limit), 3)})
        done += 1
    data["transitions"] = sorted(keep, key=lambda t: t["after"])
    # an audio J/L edit on a cut that now has a transition: the crossfade replaces it
    data["audio_edits"] = [x for x in data.get("audio_edits", []) if x["after"] not in cuts]
    data = remap_timed(plan, data)
    new = EditPlan.model_validate(data)
    if done:
        ctx.notes.append(f"{label} ({min(duration, 9.9):g}s) at {done} cut(s): {plan.total_duration():.1f}s → "
                         f"{new.total_duration():.1f}s (each overlap shortens the video)")
    if short:
        ctx.notes.append(f"{short} cut(s) kept hard: the shots there are too short for a {duration:g}s transition")
    if not done and cuts:
        raise ToolError(f"every shot is too short for a {duration:g}s {label}")
    return new


def _edge_fades(plan: EditPlan, where: str, duration: float, ctx: ToolCtx) -> EditPlan:
    data = plan.to_json()
    tl = plan.timeline()
    wanted = {"start": [FADE_IN], "end": [FADE_OUT], "start_end": [FADE_IN, FADE_OUT]}[where]
    data["transitions"] = [t for t in data["transitions"] if t["after"] not in wanted]
    for w in wanted:
        d = min(duration, (tl[0] if w == FADE_IN else tl[-1]).duration * 0.9)
        data["transitions"].append({"type": "fade", "after": w, "duration": round(d, 3)})
    ctx.notes.append({"start": "fade in from black", "end": "fade out to black",
                      "start_end": "fade in and fade out"}[where] + f" ({duration:g}s)")
    return EditPlan.model_validate(data)


@tool("crossfade")
def crossfade(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return apply_transition(plan, "crossfade", float(p["duration"]), p, when, ctx, "crossfade")


@tool("fade_black")
def fade_black(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    if p["where"] != "cuts" or len(plan.timeline()) < 2:
        return _edge_fades(plan, p["where"] if p["where"] != "cuts" else "start_end", float(p["duration"]), ctx)
    return apply_transition(plan, "fade", float(p["duration"]), p, when, ctx, "fade through black")


@tool("fade_white")
def fade_white(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return apply_transition(plan, "fadewhite", float(p["duration"]), p, when, ctx, "fade through white")


DIR = {"left": "left", "right": "right", "up": "up", "down": "down"}


@tool("wipe")
def wipe(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    kind = "wipe" if p["direction"] == "left" else f"wipe{p['direction']}"
    return apply_transition(plan, kind, float(p["duration"]), p, when, ctx, f"wipe {p['direction']}")


@tool("slide")
def slide(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return apply_transition(plan, f"slide{p['direction']}", float(p["duration"]), p, when, ctx,
                            f"slide {p['direction']}")


@tool("zoom_transition")
def zoom_transition(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return apply_transition(plan, "zoom", float(p["duration"]), p, when, ctx, "zoom through")


@tool("whip_pan")
def whip_pan(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    kind = "whip_right" if p["direction"] == "right" else "whip"
    plan = apply_transition(plan, kind, float(p["duration"]), p, when, ctx, f"whip pan {p['direction']}")
    if p["whoosh"]:  # a whip with no sound feels broken: a whoosh centred on each whip
        data = plan.to_json()
        tl = plan.timeline()
        for t in plan.transitions:
            if t.type == kind and t.after >= 0:
                at = tl[t.after + 1].start + t.duration / 2
                data["audio"]["sfx"].append({"kind": "whoosh", "at": round(at, 3), "volume": 0.6})
        plan = EditPlan.model_validate(data)
        ctx.notes.append("a whoosh on each whip")
    return plan


@tool("iris_circle")
def iris_circle(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    kind = "circleopen" if p["mode"] == "open" else "circleclose"
    return apply_transition(plan, kind, float(p["duration"]), p, when, ctx, f"iris {p['mode']}")


@tool("glitch_transition")
def glitch_transition(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return apply_transition(plan, "glitch_cut", float(p["duration"]), p, when, ctx, "glitch transition")
