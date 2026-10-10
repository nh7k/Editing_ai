"""C. Motion and time — zoom in / out, punch-in, Ken Burns, pan, shake, speed up / slow motion / speed ramp,
reverse, freeze frame.

Moves are keyframes with an easing (engines/motion.py: linear, ease_in_out, back, spring, bounce …), drawn per
shot; a time window is cut into its own shots first, so a move can start anywhere.
"""

from __future__ import annotations

from typing import Any

from ..plan import EditPlan, Effect
from .engine import ToolCtx, tool
from .timeline import ToolError, isolate, split_at
from .timewin import When

PUNCH_UNIT = 0.07  # the punch effect's zoom per unit of strength (fx_catalog._punch)


def _targets(plan: EditPlan, when: When) -> tuple[EditPlan, list[int]]:
    if when.whole:
        return plan, [e.index for e in plan.timeline()]
    idx: list[int] = []
    for a, b in when.windows:
        plan, got = isolate(plan, a, b)
        idx += got
    return plan, sorted(set(idx))


def _keyframes(plan: EditPlan, when: When, ctx: ToolCtx, path, easing: str, what: str) -> EditPlan:  # noqa: ANN001
    """`path(d)` → keyframes [t, zoom, dx, dy, angle] for a shot of d seconds. One move per window: the window's
    shots share it (each shot gets its own part of the move)."""
    plan, targets = _targets(plan, when)
    tl = plan.timeline()
    data = plan.to_json()
    groups: list[list[int]] = []
    for i in targets:  # consecutive shots of one window move together
        if groups and groups[-1][-1] == i - 1 and not when.whole:
            groups[-1].append(i)
        else:
            groups.append([i])
    for g in groups:
        total = sum(tl[i].duration for i in g)
        keys = path(total)
        t0 = 0.0
        for i in g:
            d = tl[i].duration
            local = [[round(k[0] - t0, 4), *k[1:]] for k in keys if t0 - 1e-6 <= k[0] <= t0 + d + 1e-6]
            from .timeline import _interp

            if not local or local[0][0] > 1e-3:
                local.insert(0, [0.0, *_interp(keys, t0)[1:]])
            if local[-1][0] < d - 1e-3:
                local.append([round(d, 4), *_interp(keys, t0 + d)[1:]])
            data["effects"] = [e for e in data["effects"] if not (e["type"] in ("keyframes", "zoom", "zoom_out")
                                                                   and e["target"] == i)]
            data["effects"].append(Effect(type="keyframes", target=i, points=local, easing=easing).model_dump())
            t0 += d
    ctx.notes.append(f"{what}, {easing.replace('_', ' ')} ({when.describe()})")
    return EditPlan.model_validate(data)


@tool("zoom_in")
def zoom_in(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    a = float(p["amount"])
    return _keyframes(plan, when, ctx, lambda d: [[0.0, 1.0, 0, 0, 0], [d, 1 + a, 0, 0, 0]], p["easing"],
                      f"zoom in to {1 + a:.2f}x")


@tool("zoom_out")
def zoom_out(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    a = float(p["amount"])
    return _keyframes(plan, when, ctx, lambda d: [[0.0, 1 + a, 0, 0, 0], [d, 1.0, 0, 0, 0]], p["easing"],
                      f"zoom out from {1 + a:.2f}x")


@tool("ken_burns")
def ken_burns(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    a = float(p["amount"])
    dx = {"left": -1, "right": 1}.get(p["direction"], 0) * a * 0.35
    dy = {"up": -1, "down": 1}.get(p["direction"], 0) * a * 0.35
    if p["direction"] == "out":
        path = lambda d: [[0.0, 1 + a, 0, 0, 0], [d, 1.0, 0, 0, 0]]  # noqa: E731
    else:
        # keyframes are relative to the first one (camera_move.replay_filters): start at 1.0
        path = lambda d: [[0.0, 1.0, -dx, -dy, 0], [d, 1 + a, dx, dy, 0]]  # noqa: E731
    return _keyframes(plan, when, ctx, path, "linear", f"Ken Burns {p['direction']} ({a:.0%})")


@tool("punch_in")
def punch_in(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    scale = float(p["scale"])
    tl = plan.timeline()
    total = plan.total_duration()
    if when.instants:
        times = when.instants
    elif when.windows:
        times = [a for a, _ in when.windows]
    else:  # no time said: every cut, else every 2 s
        times = [e.start for e in tl[1:]] or [round(t * 2.0, 3) for t in range(1, int(total / 2.0) + 1) if t * 2.0 < total - 0.3]
        ctx.notes.append("punches at every cut" if len(tl) > 1 else "a punch every 2 s (assumed)")
    data = plan.to_json()
    per: dict[int, list[float]] = {}
    for t in times:
        e = next((x for x in tl if x.start <= t < x.end), None)
        if e is not None:
            per.setdefault(e.index, []).append(round(t - e.start, 3))
    if not per:
        raise ToolError("no moment inside the video to punch in on")
    for i, ts in per.items():
        data["effects"] = [x for x in data["effects"] if not (x["type"] == "punch" and x["target"] == i)]
        data["effects"].append(Effect(type="punch", target=i, times=sorted(ts)[:20],
                                      strength=min(4.0, (scale - 1) / PUNCH_UNIT)).model_dump())
    ctx.notes.append(f"punch to {scale:.2f}x at {sum(len(v) for v in per.values())} moment(s)")
    return EditPlan.model_validate(data)


PAN = {"left": "pan_left", "right": "pan_right", "up": "pan_up", "down": "pan_down"}


def _effect(plan: EditPlan, when: When, ctx: ToolCtx, kind: str, strength: float, what: str) -> EditPlan:
    plan, targets = _targets(plan, when)
    data = plan.to_json()
    for t in targets:
        data["effects"] = [e for e in data["effects"] if not (e["type"] == kind and e["target"] == t)]
        data["effects"].append(Effect(type=kind, target=t, strength=max(0.05, min(4.0, strength))).model_dump())
    ctx.notes.append(f"{what} ({when.describe()})")
    return EditPlan.model_validate(data)


@tool("pan")
def pan(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _effect(plan, when, ctx, PAN[p["direction"]], float(p["speed"]), f"pan {p['direction']}")


@tool("shake")
def shake(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _effect(plan, when, ctx, "shake", float(p["intensity"]), f"camera shake x{p['intensity']:g}")


def _speed(plan: EditPlan, when: When, ctx: ToolCtx, factor: float, what: str) -> EditPlan:
    plan, targets = _targets(plan, when)
    data = plan.to_json()
    order = sorted(range(len(data["clips"])), key=lambda k: data["clips"][k]["order"])
    for i in targets:
        c = data["clips"][order[i]]
        new = c["speed"] * factor
        if not 0.25 <= new <= 4.0:
            raise ToolError(f"that would play shot {i + 1} at {new:.2f}x (allowed 0.25x-4x)")
        c["speed"] = round(new, 4)
    before = plan.total_duration()
    new_plan = EditPlan.model_validate({**data, "text": [], "stickers": [], "graphics": [], "overlays": []})
    total = new_plan.total_duration()
    # timed items keep their place relative to the video: scaled to the new length
    k = total / before if before else 1.0
    for key in ("text", "stickers", "graphics", "overlays"):
        data[key] = [dict(it, start=round(it["start"] * k, 3), end=round(min(total, it["end"] * k), 3))
                     for it in data.get(key, []) if it["start"] * k < total - 0.1]
    ctx.notes.append(f"{what}: {before:.1f}s → {total:.1f}s ({when.describe()})")
    return EditPlan.model_validate(data)


@tool("speed_up")
def speed_up(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _speed(plan, when, ctx, float(p["factor"]), f"{p['factor']:g}x faster")


@tool("slow_motion")
def slow_motion(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _speed(plan, when, ctx, float(p["factor"]), f"slow motion {p['factor']:g}x")


@tool("speed_ramp")
def speed_ramp(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    """Each target shot plays its first half at normal speed and its second half faster (slow_to_fast) or slower
    (fast_to_slow) — the renderer's ramp (both picture and sound)."""
    s = float(p["strength"])
    strength = s if p["curve"] == "speed_up_later" else 1 / s
    plan, targets = _targets(plan, when)
    data = plan.to_json()
    for t in targets:
        if any(c["reverse"] for c in data["clips"]):
            raise ToolError("a speed ramp can't be combined with reverse playback")
        data["effects"] = [e for e in data["effects"] if not (e["type"] == "speed_ramp" and e["target"] == t)]
        data["effects"].append(Effect(type="speed_ramp", target=t, strength=round(strength, 3)).model_dump())
    before = plan.total_duration()
    new = EditPlan.model_validate({**data, "text": [], "stickers": [], "graphics": [], "overlays": []}).total_duration()
    k = new / before
    for key in ("text", "stickers", "graphics", "overlays"):
        data[key] = [dict(it, start=round(it["start"] * k, 3), end=round(min(new, it["end"] * k), 3))
                     for it in data.get(key, []) if it["start"] * k < new - 0.1]
    ctx.notes.append(f"speed ramp ({p['curve'].replace('_', ' ')}, x{strength:.2f} in the second half): "
                     f"{before:.1f}s → {new:.1f}s")
    return EditPlan.model_validate(data)


@tool("reverse")
def reverse(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    """Play backwards. The whole video: the shots in reverse order AND each shot backwards. A part: those shots
    backwards in place. Long shots are cut into ≤ 10 s pieces first (FFmpeg's reverse keeps frames in memory)."""
    if any(e.type == "speed_ramp" for e in plan.effects):
        raise ToolError("a speed ramp can't be combined with reverse playback")
    plan, targets = _targets(plan, when)
    # pieces of at most 10 s of source
    for i in sorted(targets, reverse=True):
        e = plan.timeline()[i]
        n = int(e.segment.source_duration // 10.0)
        for k in range(n, 0, -1):
            cut = e.start + k * 10.0 / e.segment.speed
            if cut < e.end - 0.3:
                plan = split_at(plan, cut)
    data = plan.to_json()
    order = sorted(range(len(data["clips"])), key=lambda k: data["clips"][k]["order"])
    if when.whole:
        for rank, k in enumerate(reversed(order)):
            data["clips"][k]["order"] = rank
            data["clips"][k]["reverse"] = not data["clips"][k]["reverse"]
        data["transitions"] = [t for t in data["transitions"] if t["after"] < 0]
        data["effects"] = [e for e in data["effects"] if e["target"] < 0]
        data["audio_edits"] = []
        ctx.notes.append("the whole video plays backwards (sound too)")
    else:
        lo, hi = None, None
        for a, b in when.windows:
            lo, hi = a, b
        tl = plan.timeline()
        inside = [e.index for e in tl if e.start >= (lo or 0) - 0.05 and e.end <= (hi or 1e9) + 0.05]
        for i in inside:
            data["clips"][order[i]]["reverse"] = not data["clips"][order[i]]["reverse"]
        # the shots of the window also play in reverse order
        ranks = [data["clips"][order[i]]["order"] for i in inside]
        for i, r in zip(inside, reversed(ranks), strict=True):
            data["clips"][order[i]]["order"] = r
        ctx.notes.append(f"{when.describe()} plays backwards")
    return EditPlan.model_validate(data)


@tool("freeze_frame")
def freeze_frame(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    """Hold the frame at `at` for `duration` seconds (the sound pauses), then the video continues."""
    at, d = float(p["at"]), float(p["duration"])
    total = plan.total_duration()
    if not 0 <= at < total:
        raise ToolError(f"{at:g}s is outside the video (it is {total:.1f}s long)")
    tl = plan.timeline()
    if at > 0.05 and all(abs(at - (e.end - plan.overlap_after(e.index))) > 0.05 for e in tl):
        plan = split_at(plan, at)
        tl = plan.timeline()
    e = next(x for x in tl if abs(x.start - at) <= 0.06 or (at <= 0.05 and x.index == 0))
    seg = e.segment
    frame_at = seg.out - 0.04 if seg.reverse else seg.in_
    data = plan.to_json()
    k = e.index
    for c in data["clips"]:
        if c["order"] >= k:
            c["order"] += 1
    for x in data["effects"]:
        if x["target"] >= k:
            x["target"] += 1
    for t in data["transitions"]:
        if t["after"] >= k:
            t["after"] += 1
    for x in data.get("audio_edits", []):
        if x["after"] >= k:
            x["after"] += 1
    hold = {"source": seg.source, "in": round(frame_at, 3), "out": round(frame_at + d, 3), "order": k, "hold": True}
    data["clips"].append(hold)
    for key in ("text", "stickers", "graphics", "overlays"):
        for it in data.get(key, []):
            if it["start"] >= e.start - 1e-3:
                it["start"], it["end"] = round(it["start"] + d, 3), round(it["end"] + d, 3)
            elif it["end"] > e.start:
                it["end"] = round(it["end"] + d, 3)
    ctx.notes.append(f"frame at {at:.2f}s held for {d:g}s (the sound pauses)")
    return EditPlan.model_validate(data)
