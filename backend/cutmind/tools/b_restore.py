"""Restore and white skills (docs/INTENT_FAILURE_REVIEW.md).

restore_normal     take the effects off a part of the video (or all of it): "yaha normal karo", "pehle jaisa"
brighten_to_white  push a part of the video bright and pale, towards white: "yaha screen white sa karo"
white_screen_card  a plain white screen for a moment (the video waits and continues): "1 sec safed screen"

The white flash and the fade through white already exist (`flash`, `fade_white`).
"""

from __future__ import annotations

from typing import Any

from ..engines.stack import COLOR, FLASH, GEOMETRY, GLITCH, TEXTURE, TIME_BLEND
from ..plan import EditPlan, Effect
from . import generated
from .engine import ToolCtx, tool
from .timeline import ToolError, isolate, split_at
from .timewin import When

FAMILIES: dict[str, set[str]] = {
    "color": set(COLOR),
    "motion": set(GEOMETRY),
    "style": set(GLITCH) | set(TEXTURE) | set(FLASH) | set(TIME_BLEND),
}
WORDS = {"color": "colour", "motion": "zoom / motion", "style": "effects", "overlays": "graphics / stickers"}
NEUTRAL_COLOR = {"brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "warmth": 0.0, "gamma": 1.0, "preset": "none"}


def _family(kind: str) -> str:
    return next((f for f, types in FAMILIES.items() if kind in types), "style")


def _cut_items(items: list[dict[str, Any]], a: float, b: float) -> tuple[list[dict[str, Any]], int]:
    """Timed items (graphics / stickers) without the part inside [a, b]: before / after pieces stay."""
    out, hit = [], 0
    for it in items:
        s, e = float(it["start"]), float(it["end"])
        if e <= a + 1e-3 or s >= b - 1e-3:
            out.append(it)
            continue
        hit += 1
        if s < a - 0.05:
            out.append({**it, "end": round(a, 3)})
        if e > b + 0.05:
            out.append({**it, "start": round(b, 3)})
    return out, hit


def _preset_as_grade(preset: str) -> dict[str, Any] | None:
    """The per-shot grade that looks like a whole-video colour preset (None when there is no such grade)."""
    from ..luts import ALL_LOOKS

    if preset in ("none", ""):
        return None
    if preset in ("bw", "noir"):
        return {"look": "grayscale"}
    if preset == "warm":
        return {"warmth": 0.5}
    if preset == "cool":
        return {"warmth": -0.5}
    if preset in ALL_LOOKS:
        return {"look": preset}
    return None


@tool("restore_normal")
def restore_normal(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    what = str(p.get("what") or "all")
    fams = set(FAMILIES) | {"overlays"} if what == "all" else {what}
    removed: list[str] = []
    if when.whole:
        data = plan.to_json()
        keep = [e for e in data["effects"] if _family(e["type"]) not in fams]
        removed += sorted({e["type"] for e in data["effects"] if e not in keep})
        data["effects"] = keep
        if "color" in fams:
            # the whole grade back to neutral, not only the preset name: a style's own contrast / tint counts too
            # ("purple video ko normal kar do" on a Midnight Drift edit changed nothing before)
            neutral = {k: v for k, v in NEUTRAL_COLOR.items() if data["color"].get(k) != v}
            if neutral:
                removed.append(f"colour grade '{plan.color.preset}'" if plan.color.preset != "none" else "colour grade")
                data["color"] = {**data["color"], **NEUTRAL_COLOR}
            washes = [o for o in data.get("overlays", []) if o["kind"] == "wash"]
            if washes:  # a style's colour wash tints the whole picture: it is colour, not a graphic
                removed.append("colour wash")
                data["overlays"] = [o for o in data["overlays"] if o["kind"] != "wash"]
        if "overlays" in fams:
            # a look's gradient tracks go only with "everything normal" ("stickers hata do" keeps the look)
            tracks = len(data.get("overlays", [])) if what == "all" else 0
            n = len(data.get("graphics", [])) + len(data.get("stickers", [])) + tracks
            if n:
                removed.append(f"{n} graphic(s) / sticker(s)")
            data["graphics"], data["stickers"] = [], []
            if what == "all":
                data["overlays"] = []
        if what == "all" and data.get("style"):
            removed.append(f"style '{data['style']}'")
            data["style"] = None
        if not removed:
            raise ToolError("there is no effect on this video to take off — it already looks normal")
        ctx.notes.append("back to normal everywhere: " + ", ".join(removed))
        return EditPlan.model_validate(data)

    for a, b in when.windows:
        plan, idx = isolate(plan, a, b)
        tl = plan.timeline()
        lo, hi = tl[idx[0]].start, tl[idx[-1]].end
        data = plan.to_json()
        new_fx = []
        for e in data["effects"]:
            if _family(e["type"]) not in fams:
                new_fx.append(e)
            elif e["target"] in idx:
                removed.append(e["type"])
            elif e["target"] == -1:
                # an effect on the whole video: it stays everywhere except here
                removed.append(e["type"])
                new_fx += [Effect.model_validate({**e, "target": x.index}).model_dump() for x in tl if x.index not in idx]
            else:
                new_fx.append(e)
        data["effects"] = new_fx
        if "overlays" in fams:
            data["graphics"], g = _cut_items(data.get("graphics", []), lo, hi)
            data["stickers"], s = _cut_items(data.get("stickers", []), lo, hi)
            o = 0
            if what == "all":
                data["overlays"], o = _cut_items(data.get("overlays", []), lo, hi)
            if g + s + o:
                removed.append(f"{g + s + o} graphic(s) / sticker(s)")
        elif "color" in fams:  # a style's colour wash, only here
            keep = [x for x in data.get("overlays", []) if x["kind"] != "wash"]
            washes, w = _cut_items([x for x in data.get("overlays", []) if x["kind"] == "wash"], lo, hi)
            if w:
                removed.append("colour wash")
                data["overlays"] = keep + washes
        grade = _preset_as_grade(plan.color.preset) if "color" in fams else None
        # the whole-video numbers too (a "bw" edit also has saturation 0 — left alone, this moment stayed grey)
        numbers = {k: v for k in ("brightness", "contrast", "saturation", "warmth")
                   if (v := data["color"].get(k)) != NEUTRAL_COLOR[k]} if "color" in fams else {}
        if numbers:
            grade = {**numbers, **(grade or {})}
        if grade is not None:
            # a whole-video colour preset (the director's "black and white") becomes the same grade on every OTHER
            # shot, so only this moment goes back to normal
            removed.append(f"colour '{plan.color.preset}'" if plan.color.preset != "none" else "colour grade")
            data["color"] = {**data["color"], **NEUTRAL_COLOR}
            for x in tl:
                if x.index in idx:
                    continue
                cur = next((e for e in data["effects"] if e["type"] == "grade" and e["target"] == x.index), None)
                if cur is None:
                    data["effects"].append(Effect(type="grade", target=x.index, params=dict(grade)).model_dump())
                else:
                    cur["params"] = {**grade, **cur["params"]}
        plan = EditPlan.model_validate(data)
    if "color" in fams and plan.color.preset != "none":
        ctx.notes.append(f"the colour grade '{plan.color.preset}' covers the whole video, so it stays here too — "
                         "say 'poori video ka colour normal karo' to take it off everywhere")
    if not removed:
        raise ToolError(f"there is no {WORDS.get(what, 'effect')} here to take off ({when.describe()})")
    ctx.notes.append(f"back to normal ({when.describe()}): removed " + ", ".join(dict.fromkeys(removed)))
    return plan


@tool("brighten_to_white")
def brighten_to_white(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    from .b_color import _grade

    a = float(p["amount"])
    # brighter, flatter and paler: the picture washes out towards white (still readable at 0.5)
    params = {"brightness": round(0.45 * a, 3), "contrast": round(1 - 0.35 * a, 3), "saturation": round(1 - 0.6 * a, 3)}
    return _grade(plan, when, ctx, params, f"washed bright towards white x{a:g}")


@tool("white_screen_card")
def white_screen_card(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    at = when.instants[0] if when.instants else (when.windows[0][0] if when.windows else 0.0)
    d = float(p["duration"])
    total = plan.total_duration()
    if not 0 <= at <= total:
        raise ToolError(f"{at:g}s is outside the video (it is {total:.1f}s long)")
    w, h = plan.canvas.size
    card_id, path = generated.card(ctx.gen_dir, w, h, d, "white", plan.canvas.fps)
    ctx.sources[card_id] = path
    tl = plan.timeline()
    ends = [0.0] + [e.end - plan.overlap_after(e.index) for e in tl]
    if all(abs(at - x) > 0.05 for x in ends):
        plan = split_at(plan, at)
        tl = plan.timeline()
    k = next((x.index for x in tl if abs(x.start - at) <= 0.06), len(tl))  # the card goes before shot k
    data = plan.to_json()
    for c in data["clips"]:
        if c["order"] >= k:
            c["order"] += 1
    for e in data["effects"]:
        if e["target"] >= k:
            e["target"] += 1
    for t in data["transitions"]:
        if t["after"] >= k:
            t["after"] += 1
    for x in data.get("audio_edits", []):
        if x["after"] >= k:
            x["after"] += 1
    for key in ("text", "stickers", "graphics", "overlays"):
        for it in data.get(key, []):
            if it["start"] >= at - 1e-3:
                it["start"], it["end"] = round(it["start"] + d, 3), round(it["end"] + d, 3)
            elif it["end"] > at:
                it["end"] = round(it["end"] + d, 3)
    data["clips"].append({"source": card_id, "in": 0.0, "out": d, "order": k})
    ctx.notes.append(f"{d:g}s white screen at {at:.1f}s (the video continues after it)")
    return EditPlan.model_validate(data)
