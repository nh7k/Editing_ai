"""G. Layout and reframe — aspect ratios, subject-following reframe, blurred fill, letterbox bars,
picture-in-picture, split screen, rotate / flip, crop."""

from __future__ import annotations

from typing import Any

from ..plan import EditPlan, Effect
from .engine import ToolCtx, tool
from .timeline import ToolError, isolate
from .timewin import When

FIT = {"crop": "crop", "fill": "crop", "blur": "blur_pad", "blur_pad": "blur_pad", "fit": "pad", "pad": "pad"}
CORNERS = {"top_left": (0.04, 0.04), "top_right": (None, 0.04), "bottom_left": (0.04, None),
           "bottom_right": (None, None), "center": ("c", "c")}


def _aspect(plan: EditPlan, ratio: str, fit: str, ctx: ToolCtx) -> EditPlan:
    data = plan.to_json()
    data["canvas"]["aspect_ratio"] = ratio
    data["canvas"]["reframe"] = FIT[fit]
    w, h = EditPlan.model_validate(data).canvas.size
    ctx.notes.append(f"{ratio} ({w}x{h}), {'cropped to fill' if FIT[fit] == 'crop' else 'blurred sides' if FIT[fit] == 'blur_pad' else 'whole picture with bars'}")
    return EditPlan.model_validate(data)


@tool("aspect_9_16")
def aspect_9_16(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _aspect(plan, "9:16", p["fit_mode"], ctx)


@tool("aspect_1_1")
def aspect_1_1(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _aspect(plan, "1:1", p["fit_mode"], ctx)


@tool("aspect_16_9")
def aspect_16_9(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _aspect(plan, "16:9", p["fit_mode"], ctx)


@tool("aspect_4_5")
def aspect_4_5(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _aspect(plan, "4:5", p["fit_mode"], ctx)


@tool("blur_background_fill")
def blur_background_fill(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    data = plan.to_json()
    data["canvas"]["reframe"] = "blur_pad"
    ctx.notes.append("the whole picture, centred, on a blurred copy of itself")
    return EditPlan.model_validate(data)


def track_paths(plan: EditPlan, ctx: ToolCtx, target: str) -> dict[int, list[list[float]]]:
    """Subject path per segment (segment seconds, normalised cx cy w h) — the Effects agent's tracking."""
    from ..tracking import track_clip

    from ..agents.effects import MIN_FOUND

    out: dict[int, list[list[float]]] = {}
    tracks: dict[str, Any] = {}
    for e in plan.timeline():
        seg = e.segment
        if seg.reverse or seg.hold or seg.source not in ctx.sources:
            continue
        if seg.source not in tracks:
            try:
                tracks[seg.source] = track_clip(ctx.sources[seg.source], target, ctx.gen_dir.parent / "analysis")
            except (FileNotFoundError, OSError):
                tracks[seg.source] = None
        tr = tracks[seg.source]
        if tr is None or tr.found < MIN_FOUND:
            continue
        first, last = tr.at(seg.in_), tr.at(seg.out)
        pts = [[0.0, *first]] if first else []
        pts += [[round((q[0] - seg.in_) / seg.speed, 3), *q[1:]] for q in tr.points if seg.in_ < q[0] < seg.out]
        if last:
            pts.append([round(e.duration, 3), *last])
        out[e.index] = [[round(v, 4) for v in q] for q in pts]
    return out


@tool("auto_reframe")
def auto_reframe(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    paths = track_paths(plan, ctx, p["target"])
    if not paths:
        raise ToolError(f"no {p['target']} found clearly in this footage — the frame stays centred")
    data = plan.to_json()
    data["effects"] = [e for e in data["effects"] if e["type"] not in ("follow", "person_zoom")]
    for i, pts in paths.items():
        data["effects"].append(Effect(type="follow", target=i, points=pts).model_dump())
    n = len(plan.timeline())
    ctx.notes.append(f"the crop follows the {p['target']} in {len(paths)} of {n} shots"
                     + ("" if len(paths) == n else " (not found clearly in the others: centred there)"))
    return EditPlan.model_validate(data)


@tool("letterbox")
def letterbox(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _segment_effect(plan, when, Effect(type="letterbox", params={"ratio": float(p["ratio"])}),
                           f"black bars for a {p['ratio']}:1 frame", ctx)


def _segment_effect(plan: EditPlan, when: When, fx: Effect, what: str, ctx: ToolCtx) -> EditPlan:
    """Whole video → one effect on every shot; a window → split at its edges and target the shots inside."""
    if when.whole:
        data = plan.to_json()
        data["effects"] = [e for e in data["effects"] if e["type"] != fx.type] + [fx.model_copy(update={"target": -1}).model_dump()]
        ctx.notes.append(what)
        return EditPlan.model_validate(data)
    for a, b in when.windows:
        plan, idx = isolate(plan, a, b)
        data = plan.to_json()
        data["effects"] += [fx.model_copy(update={"target": i}).model_dump() for i in idx]
        plan = EditPlan.model_validate(data)
    ctx.notes.append(f"{what} ({when.describe()})")
    return plan


def _layer_box(pos: str, size: float, W: int, H: int) -> tuple[float, float, float, float]:
    """A corner box `size` wide (share of the frame width) with the source's 16:9 shape kept."""
    w = size
    h = min(0.9, size * W / H * 9 / 16)
    cx, cy = CORNERS.get(pos, (None, None))
    x = (1 - w) / 2 if cx == "c" else (cx if cx is not None else 1 - w - 0.04)
    y = (1 - h) / 2 if cy == "c" else (cy if cy is not None else 1 - h - 0.06)
    return x, y, w, h


@tool("picture_in_picture")
def picture_in_picture(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    from .invariants import source_duration

    cid = _clip(p.get("clip"), plan, ctx)
    total = plan.total_duration()
    a, b = (0.0, total) if when.whole else when.windows[0]
    b = min(b, a + source_duration(ctx.sources[cid]) - float(p["src_in"]))
    W, H = plan.canvas.size
    x, y, w, h = _layer_box(p["position"], float(p["size"]), W, H)
    data = plan.to_json()
    data["graphics"].append({"kind": "layer", "source": cid, "src_in": float(p["src_in"]), "start": round(a, 3),
                             "end": round(b, 3), "x": x, "y": y, "w": w, "h": h, "fit": "crop",
                             "border": 0.006, "color": "#FFFFFF", "animate": "fade"})
    ctx.notes.append(f"{cid} in the {p['position'].replace('_', ' ')} corner ({p['size']:.0%} wide), {a:.1f}-{b:.1f}s; "
                     "the main sound continues")
    return EditPlan.model_validate(data)


def _clip(ref: str | None, plan: EditPlan, ctx: ToolCtx) -> str:
    if ref and ref.startswith("#"):
        k = int(ref[1:]) - 1
        if not 0 <= k < len(ctx.clip_ids):
            raise ToolError(f"there is no clip {k + 1}")
        return ctx.clip_ids[k]
    if ref:
        if ref not in ctx.sources:
            raise ToolError(f"there is no clip '{ref}'")
        return ref
    used = {c.source for c in plan.clips}
    cid = next((c for c in ctx.clip_ids if c not in used), None)
    if cid is None:
        if len(ctx.clip_ids) < 2:
            raise ToolError("upload a second clip for this")
        cid = ctx.clip_ids[1]
    ctx.notes.append(f"second picture: clip {cid} (assumed)")
    return cid


@tool("split_screen")
def split_screen(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    """Two clips side by side (or top / bottom). The edit's own sound continues."""
    from .invariants import source_duration

    ids = [c for c in ctx.clip_ids if c in ctx.sources]
    if len(ids) < 2:
        raise ToolError("split screen needs two clips")
    a_id = _clip(p.get("left"), plan, ctx) if p.get("left") else ids[0]
    b_id = _clip(p.get("right"), plan, ctx) if p.get("right") else next(c for c in ids if c != a_id)
    total = plan.total_duration()
    s, e = (0.0, total) if when.whole else when.windows[0]
    e = min(e, s + min(source_duration(ctx.sources[a_id]), source_duration(ctx.sources[b_id])))
    boxes = ([(0.0, 0.0, 0.5, 1.0), (0.5, 0.0, 0.5, 1.0)] if p["layout"] == "left_right"
             else [(0.0, 0.0, 1.0, 0.5), (0.0, 0.5, 1.0, 0.5)])
    data = plan.to_json()
    for cid, (x, y, w, h) in zip((a_id, b_id), boxes, strict=True):
        data["graphics"].append({"kind": "layer", "source": cid, "src_in": 0.0, "start": round(s, 3),
                                 "end": round(e, 3), "x": x, "y": y, "w": w, "h": h, "fit": "crop"})
    ctx.notes.append(f"{a_id} | {b_id} ({p['layout'].replace('_', '/')}), {s:.1f}-{e:.1f}s")
    return EditPlan.model_validate(data)


@tool("rotate_flip")
def rotate_flip(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    data = plan.to_json()
    c = data["canvas"]
    if p.get("angle") is not None:
        c["rotate"] = int((c["rotate"] + int(p["angle"])) % 360)
    if p.get("axis") not in (None, "none"):
        flips = {"none": set(), "h": {"h"}, "v": {"v"}, "hv": {"h", "v"}}
        cur = flips[c["flip"]] ^ {p["axis"]} if p["axis"] in ("h", "v") else flips[c["flip"]] ^ {"h", "v"}
        c["flip"] = "hv" if cur == {"h", "v"} else (next(iter(cur)) if cur else "none")
    ctx.notes.append(f"rotated {c['rotate']}°, mirror: {c['flip']}")
    return EditPlan.model_validate(data)


@tool("crop")
def crop(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    x, y, w, h = (float(p[k]) for k in ("x", "y", "w", "h"))
    if x + w > 1.001 or y + h > 1.001:
        raise ToolError("the crop box goes outside the picture")
    return _segment_effect(plan, when, Effect(type="crop", params={"x": x, "y": y, "w": w, "h": h}),
                           f"cropped to {w:.0%}x{h:.0%} at ({x:.0%}, {y:.0%})", ctx)
