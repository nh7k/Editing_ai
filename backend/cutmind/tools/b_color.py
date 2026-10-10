"""D. Colour and look — B&W, sepia, brightness, contrast, saturation, warm / cool, cinematic / teal-orange /
vintage looks, vignette, grain, sharpen, blur, auto enhance, colour pop.

Every colour change is one "grade" effect per shot (eq + colour temperature + a look LUT at a strength), so it
works on the whole video or any part of it, and two asks on the same shot merge ("warm" then "more contrast" =
both, not the second replacing the first). The latest value of a setting wins.
"""

from __future__ import annotations

from typing import Any

from ..plan import EditPlan, Effect
from .engine import ToolCtx, tool
from .timeline import isolate
from .timewin import When

GREY_LOOKS = {"grayscale"}


def _targets(plan: EditPlan, when: When) -> tuple[EditPlan, list[int]]:
    if when.whole:
        return plan, [-1]
    idx: list[int] = []
    for a, b in when.windows:
        plan, got = isolate(plan, a, b)
        idx += got
    return plan, sorted(set(idx))


def _grade(plan: EditPlan, when: When, ctx: ToolCtx, params: dict[str, Any], what: str) -> EditPlan:
    plan, targets = _targets(plan, when)
    data = plan.to_json()
    for t in targets:
        cur = next((e for e in data["effects"] if e["type"] == "grade" and e["target"] == t), None)
        if cur is None:
            data["effects"].append(Effect(type="grade", target=t, params=dict(params)).model_dump())
        else:
            cur["params"] = {**cur["params"], **params}
        if params.get("look") in GREY_LOOKS:  # B&W undoes a colour pop on the same shot: the later ask wins
            before = len(data["effects"])
            data["effects"] = [e for e in data["effects"] if not (e["type"] == "color_pop" and e["target"] == t)]
            if len(data["effects"]) < before:
                ctx.notes.append("colour pop removed there (black & white was asked after it)")
    ctx.notes.append(f"{what} ({when.describe()})")
    return EditPlan.model_validate(data)


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


def _look(name: str, label: str):  # noqa: ANN202
    def build(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
        s = float(p["strength"])
        return _grade(plan, when, ctx, {"look": name, "look_strength": s}, f"{label} at {s:.0%}")
    return build


tool("grayscale")(lambda plan, p, when, ctx: _grade(plan, when, ctx, {"look": "grayscale", "look_strength": float(p["intensity"])},
                                                   f"black & white at {float(p['intensity']):.0%}"))
tool("sepia")(_look("sepia", "sepia"))
tool("cinematic_look")(_look("cinematic", "cinematic look"))
tool("teal_orange")(_look("teal_orange", "teal & orange"))
tool("vintage_faded")(_look("vintage", "vintage faded look"))


@tool("brightness")
def brightness(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    a = float(p["amount"])
    return _grade(plan, when, ctx, {"brightness": a}, f"brightness {a:+.2f}")


@tool("contrast")
def contrast(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    a = float(p["amount"])
    return _grade(plan, when, ctx, {"contrast": a}, f"contrast x{a:.2f}")


@tool("saturation")
def saturation(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    a = float(p["amount"])
    return _grade(plan, when, ctx, {"saturation": a}, f"saturation x{a:.2f}")


@tool("warm")
def warm(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    a = float(p["amount"])
    return _grade(plan, when, ctx, {"warmth": a}, f"warmer by {a:.2f}")


@tool("cool")
def cool(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    a = float(p["amount"])
    return _grade(plan, when, ctx, {"warmth": -a}, f"cooler by {a:.2f}")


@tool("vignette")
def vignette(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _effect(plan, when, ctx, "vignette", float(p["amount"]), f"vignette {p['amount']:g}")


@tool("film_grain")
def film_grain(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _effect(plan, when, ctx, "film_grain", float(p["amount"]), f"film grain {p['amount']:g}")


@tool("sharpen")
def sharpen(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _effect(plan, when, ctx, "sharpen", float(p["amount"]), f"sharpen {p['amount']:g}")


@tool("blur")
def blur(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _effect(plan, when, ctx, "blur", float(p["radius"]) / 4, f"blur radius {p['radius']:g}")


@tool("color_pop")
def color_pop(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    plan2 = plan
    if when.whole:  # a whole-video B&W grade would grey the kept colour too
        data = plan.to_json()
        for e in data["effects"]:
            if e["type"] == "grade" and e["params"].get("look") in GREY_LOOKS:
                e["params"] = {k: v for k, v in e["params"].items() if k not in ("look", "look_strength")}
                ctx.notes.append("black & white removed (colour pop was asked after it)")
        plan2 = EditPlan.model_validate(data)
    return _effect(plan2, when, ctx, "color_pop", 1.0, f"only {p['color']} kept in colour", {"color": p["color"]})


def _measured_luma(ctx: ToolCtx, plan: EditPlan) -> dict[str, float]:
    """Mean brightness (0..1) per clip: from the analysis when there is one, else measured on 3 frames."""
    out: dict[str, float] = {}
    an = ctx.analysis() if ctx.analysis else None
    for cid in {c.source for c in plan.clips}:
        a = an.clips.get(cid) if an is not None else None
        if a is not None:
            out[cid] = float(a.luma)
            continue
        from ..ffmpeg_utils import extract_frame, probe

        src = ctx.sources[cid]
        d = probe(src).duration
        vals = [float(extract_frame(src, d * k, 160, 90).mean()) / 255 for k in (0.2, 0.5, 0.8)]
        out[cid] = sum(vals) / len(vals)
    return out


@tool("auto_enhance")
def auto_enhance(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    """Each clip's exposure towards a mid level (measured), a little contrast and colour — like a quick colourist
    pass. Dark clips get brighter, bright ones darker; nothing is guessed."""
    luma = _measured_luma(ctx, plan)
    data = plan.to_json()
    target = 0.48
    for e in plan.timeline():
        lv = luma.get(e.segment.source, target)
        b = round(max(-0.18, min(0.18, (target - lv) * 0.7)) * float(p["strength"]), 3)
        params = {"brightness": b, "contrast": round(1 + 0.08 * float(p["strength"]), 3),
                  "saturation": round(1 + 0.12 * float(p["strength"]), 3)}
        cur = next((x for x in data["effects"] if x["type"] == "grade" and x["target"] == e.index), None)
        if cur is None:
            data["effects"].append(Effect(type="grade", target=e.index, params=params).model_dump())
        else:
            cur["params"] = {**cur["params"], **params}
    ctx.notes.append("exposure per clip: " + ", ".join(f"{c} {v:.2f}→{target:.2f}" for c, v in sorted(luma.items()))
                     + "; contrast +8 %, colour +12 %")
    return EditPlan.model_validate(data)
