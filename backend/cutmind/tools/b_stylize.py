"""F. Stylize and overlays — glitch, VHS, RGB split, flash, light leak, mirror, pixelate / blur censor boxes,
highlight shapes, stickers, countdown."""

from __future__ import annotations

from typing import Any

from ..plan import EditPlan, Effect, TextItem, TextStyle
from .engine import ToolCtx, tool
from .timeline import ToolError, isolate
from .timewin import When


def _targets(plan: EditPlan, when: When) -> tuple[EditPlan, list[int]]:
    if when.whole:
        return plan, [-1]
    idx: list[int] = []
    for a, b in when.windows:
        plan, got = isolate(plan, a, b)
        idx += got
    return plan, sorted(set(idx))


def _effect(plan: EditPlan, when: When, ctx: ToolCtx, kind: str, strength: float, what: str,
            params: dict[str, Any] | None = None) -> EditPlan:
    plan, targets = _targets(plan, when)
    data = plan.to_json()
    for t in targets:
        data["effects"] = [e for e in data["effects"] if not (e["type"] == kind and e["target"] == t)]
        data["effects"].append(Effect(type=kind, target=t, strength=max(0.05, min(4.0, strength)),
                                      params=params or {}).model_dump())
    ctx.notes.append(f"{what} ({when.describe()})")
    return EditPlan.model_validate(data)


@tool("glitch")
def glitch(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _effect(plan, when, ctx, "glitch", float(p["intensity"]), f"digital glitch x{p['intensity']:g}")


@tool("vhs_retro")
def vhs_retro(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _effect(plan, when, ctx, "vhs", float(p["intensity"]), "VHS tape look")


@tool("rgb_split")
def rgb_split(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _effect(plan, when, ctx, "rgb_split", float(p["amount"]), f"RGB split x{p['amount']:g}")


@tool("flash")
def flash(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    tl = plan.timeline()
    times = when.instants or ([a for a, _ in when.windows] if when.windows else [e.start for e in tl[1:]])
    if not times:
        times = [0.0]
        ctx.notes.append("one flash at the start (there is no cut)")
    data = plan.to_json()
    per: dict[int, list[float]] = {}
    for t in times:
        e = next((x for x in tl if x.start - 1e-6 <= t < x.end), tl[-1])
        per.setdefault(e.index, []).append(round(max(0.0, t - e.start), 3))
    for i, ts in per.items():
        data["effects"] = [x for x in data["effects"] if not (x["type"] == "flash" and x["target"] == i)]
        data["effects"].append(Effect(type="flash", target=i, times=sorted(ts), strength=float(p["intensity"])).model_dump())
    ctx.notes.append(f"white flash at {sum(len(v) for v in per.values())} moment(s)")
    return EditPlan.model_validate(data)


@tool("light_leak")
def light_leak(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    total = plan.total_duration()
    wins = when.windows if when.windows else [(0.0, min(total, float(p["duration"])))]
    data = plan.to_json()
    for a, b in wins:
        data["graphics"].append({"kind": "light_leak", "start": round(a, 3), "end": round(min(b, total), 3),
                                 "strength": float(p["strength"]), "color": p["color"]})
    ctx.notes.append(f"warm light leak ({', '.join(f'{a:.1f}-{b:.1f}s' for a, b in wins)})")
    return EditPlan.model_validate(data)


@tool("mirror_effect")
def mirror_effect(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    if p["axis"] == "both":
        return _effect(plan, when, ctx, "kaleidoscope", 1.0, "four-way mirror")
    return _effect(plan, when, ctx, "mirror", 1.0, f"mirror ({'left onto right' if p['axis'] == 'h' else 'top onto bottom'})",
                   {"axis": p["axis"]})


REGIONS = {"center": (0.35, 0.3, 0.3, 0.4), "top": (0.3, 0.05, 0.4, 0.3), "bottom": (0.3, 0.65, 0.4, 0.3),
           "left": (0.05, 0.3, 0.3, 0.4), "right": (0.65, 0.3, 0.3, 0.4), "top_left": (0.05, 0.05, 0.3, 0.35),
           "top_right": (0.65, 0.05, 0.3, 0.35), "bottom_left": (0.05, 0.6, 0.3, 0.35), "bottom_right": (0.65, 0.6, 0.3, 0.35)}


def _region(plan: EditPlan, p: dict[str, Any], ctx: ToolCtx, a: float, b: float) -> tuple[float, float, float, float]:
    """The box to censor / highlight: given numbers, a named area, or the face found in that window."""
    if p.get("region") == "face":
        from .b_layout import track_paths

        paths = track_paths(plan, ctx, "face")
        boxes = []
        for e in plan.timeline():
            if e.index in paths and e.end > a and e.start < b:
                boxes += [q[1:5] for q in paths[e.index]]
        if not boxes:
            raise ToolError("no face found there — give the area instead (e.g. 'top right')")
        import numpy as np

        cx, cy, w, h = (float(np.median([bx[k] for bx in boxes])) for k in range(4))
        w, h = w * 1.6, h * 1.6  # a margin: the face moves a little inside the window
        ctx.notes.append("box over the face (median position in that window; a moving face is not followed frame by frame)")
        return max(0.0, cx - w / 2), max(0.0, cy - h / 2), min(1.0, w), min(1.0, h)
    return REGIONS.get(p.get("region") or "center", REGIONS["center"])


def _censor(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx, kind: str) -> EditPlan:
    total = plan.total_duration()
    wins = when.windows if when.windows else [(0.0, total)]
    data = plan.to_json()
    for a, b in wins:
        x, y, w, h = _region(plan, p, ctx, a, b)
        data["graphics"].append({"kind": kind, "start": round(a, 3), "end": round(min(b, total), 3), "x": round(x, 4),
                                 "y": round(y, 4), "w": round(w, 4), "h": round(h, 4), "strength": float(p["strength"])})
    ctx.notes.append(f"{'pixelated' if kind == 'pixelate' else 'blurred'} box over the {p.get('region') or 'centre'} "
                     f"({', '.join(f'{a:.1f}-{b:.1f}s' for a, b in wins)})")
    return EditPlan.model_validate(data)


@tool("pixelate_censor")
def pixelate_censor(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _censor(plan, p, when, ctx, "pixelate")


@tool("blur_box_censor")
def blur_box_censor(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _censor(plan, p, when, ctx, "blur")


@tool("shape_highlight")
def shape_highlight(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    total = plan.total_duration()
    a, b = when.windows[0] if when.windows else (0.0, min(total, 3.0))
    x, y, w, h = _region(plan, p, ctx, a, b)
    data = plan.to_json()
    data["graphics"].append({"kind": p["shape"], "start": round(a, 3), "end": round(min(b, total), 3), "x": round(x, 4),
                             "y": round(y, 4), "w": round(w, 4), "h": round(h, 4), "color": p["color"],
                             "angle": float(p.get("angle") or 0.0), "animate": "pop"})
    ctx.notes.append(f"{p['shape']} in {p['color']} around the {p.get('region') or 'centre'} ({a:.1f}-{b:.1f}s)")
    return EditPlan.model_validate(data)


@tool("sticker_lottie")
def sticker_lottie(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    """An animated emoji sticker (pops in, sits, fades out). Server: our emoji PNG renderer; Lottie files play
    only on the phone (lottie-android) — no licence-safe server Lottie renderer is vetted yet."""
    from .. import stickers

    if not stickers.available():
        raise ToolError("no colour emoji font on this server (Noto Color Emoji) — stickers are not available")
    total = plan.total_duration()
    a, b = when.windows[0] if when.windows else (min(1.0, total / 3), min(total, min(1.0, total / 3) + 2.5))
    data = plan.to_json()
    data["stickers"].append({"emoji": p["emoji"], "word": "", "start": round(a, 3), "end": round(min(b, total), 3),
                             "position": p["position"], "size": float(p["size"])})
    ctx.notes.append(f"{p['emoji']} sticker {p['position'].replace('_', ' ')} ({a:.1f}-{b:.1f}s)")
    return EditPlan.model_validate(data)


@tool("countdown_timer")
def countdown_timer(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    n = int(p["from"])
    total = plan.total_duration()
    start = when.windows[0][0] if when.windows else float(p["at"])
    if start + n > total + 0.05:
        raise ToolError(f"a {n}-second countdown from {start:g}s does not fit in the video ({total:.1f}s)")
    data = plan.to_json()
    for k in range(n):
        st = TextStyle(position="center", size=int(p["size"]), box_color=None, animation="pop", outline=6,
                       outline_color="#000000", color=p["color"])
        data["text"].append(TextItem(kind="text", text=str(n - k), start=round(start + k, 3),
                                     end=round(min(total, start + k + 0.95), 3), style=st).model_dump())
    ctx.notes.append(f"countdown {n} → 1 from {start:g}s")
    return EditPlan.model_validate(data)
