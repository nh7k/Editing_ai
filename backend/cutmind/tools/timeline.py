"""Output-time operations on an Edit Plan. Never touches media: only segment in/out points and indices.

Everything the plan says by segment index (effects, transitions, audio edits) is re-indexed, and everything it
says in output seconds (text, stickers, overlays, graphics) is shifted, so a split is invisible and a removed
range takes its captions / stickers with it.
"""

from __future__ import annotations

from typing import Any

from ..plan import EditPlan, TimelineEntry

EPS = 0.05          # snap to an existing cut when this close (s)
MIN_SRC = 0.2       # ClipSegment minimum source length (plan.py)
TIMED = ("text", "overlays", "stickers", "graphics")


class ToolError(ValueError):
    """The tool can't do this on this plan (said to the user as is)."""


def _entry_at(plan: EditPlan, t: float) -> TimelineEntry | None:
    for e in plan.timeline():
        if e.start < t < e.end:
            return e
    return None


def boundaries(plan: EditPlan) -> list[float]:
    tl = plan.timeline()
    return [0.0] + [e.end - plan.overlap_after(e.index) for e in tl[:-1]] + [tl[-1].end]


def _src_at(e: TimelineEntry, t: float) -> float:
    seg = e.segment
    frac = (t - e.start) / e.duration
    return seg.out - frac * seg.source_duration if seg.reverse else seg.in_ + frac * seg.source_duration


def _interp(points: list[list[float]], t: float) -> list[float]:
    """Linear interpolation of a [t, v1, v2, …] key list at time t."""
    pts = sorted(points, key=lambda p: p[0])
    if t <= pts[0][0]:
        return [t, *pts[0][1:]]
    for a, b in zip(pts, pts[1:], strict=False):
        if a[0] <= t <= b[0]:
            k = (t - a[0]) / max(1e-9, b[0] - a[0])
            return [t, *[x + (y - x) * k for x, y in zip(a[1:], b[1:], strict=False)]]
    return [t, *pts[-1][1:]]


def _split_keys(points: list[list[float]], local: float) -> tuple[list[list[float]], list[list[float]]]:
    if not points:
        return [], []
    mid = _interp(points, local)
    first = [p for p in points if p[0] < local] + [mid]
    second = [[0.0, *mid[1:]]] + [[p[0] - local, *p[1:]] for p in points if p[0] > local]
    return first, second


def _shift_index(data: dict[str, Any], i: int, delta: int) -> None:
    """Indices > i move by delta (effects, transitions, audio edits)."""
    for e in data["effects"]:
        if e["target"] > i:
            e["target"] += delta
    for t in data["transitions"]:
        if t["after"] > i:
            t["after"] += delta
    for a in data.get("audio_edits", []):
        if a["after"] > i:
            a["after"] += delta


def split_at(plan: EditPlan, t: float) -> EditPlan:
    """Cut the segment under output time t into two (no visible change; the output length is the same)."""
    if any(abs(t - b) <= EPS for b in boundaries(plan)):
        return plan
    e = _entry_at(plan, t)
    if e is None:
        raise ToolError(f"{t:.2f}s is outside the video")
    i, seg = e.index, e.segment
    if any(x.type == "speed_ramp" and x.target in (-1, i) for x in plan.effects):
        raise ToolError("this shot has a speed ramp; it can't be split (remove the ramp first)")
    ov_in = plan.overlap_after(i - 1) if i > 0 else 0.0
    if t < e.start + ov_in or t > e.end - plan.overlap_after(i):
        raise ToolError(f"{t:.2f}s is inside a transition; pick a time outside it or remove the transition")
    src = _src_at(e, t)
    first, second = sorted((seg.in_, src)), sorted((src, seg.out))
    if seg.reverse:  # the first output half is the END of the source
        first, second = (src, seg.out), (seg.in_, src)
    if first[1] - first[0] < MIN_SRC or second[1] - second[0] < MIN_SRC:
        raise ToolError(f"a split at {t:.2f}s leaves a piece shorter than {MIN_SRC}s")
    data = plan.to_json()
    order = sorted(range(len(data["clips"])), key=lambda k: data["clips"][k]["order"])
    k = order[i]
    for c in data["clips"]:
        if c["order"] > i:
            c["order"] += 1
    a = dict(data["clips"][k], **{"in": round(first[0], 4), "out": round(first[1], 4)})
    b = dict(data["clips"][k], **{"in": round(second[0], 4), "out": round(second[1], 4), "order": i + 1})
    data["clips"][k] = a
    data["clips"].append(b)
    local = t - e.start
    _shift_index(data, i, +1)
    for t_ in data["transitions"]:
        if t_["after"] == i:
            t_["after"] = i + 1
    for a_ in data.get("audio_edits", []):
        if a_["after"] == i:
            a_["after"] = i + 1
    new_fx = []
    for fx in data["effects"]:
        if fx["target"] == i:
            p1, p2 = _split_keys(fx.get("points", []), local)
            t1 = [x for x in fx.get("times", []) if x < local]
            t2 = [round(x - local, 4) for x in fx.get("times", []) if x >= local]
            new_fx.append({**fx, "points": p1, "times": t1})
            new_fx.append({**fx, "target": i + 1, "points": p2, "times": t2})
        else:
            new_fx.append(fx)
    data["effects"] = new_fx
    before = [(t["after"], t["duration"]) for t in data["transitions"]]
    _fit_transitions(data)
    if [(t["after"], t["duration"]) for t in data["transitions"]] != before:
        # a shorter transition would make the video LONGER: a split must never change the length
        raise ToolError(f"{t:.2f}s is too close to a transition to cut there")
    return EditPlan.model_validate(data)


def _fit_transitions(data: dict[str, Any]) -> None:
    """A split can make a shot shorter than a transition on it: shorten the transition to fit (≤ half of each
    neighbour), drop it when even 0.12 s does not fit."""
    tmp = EditPlan.model_validate({**data, "transitions": [], **{k: [] for k in TIMED if k in data}})
    tl = tmp.timeline()
    keep = []
    for t in data["transitions"]:
        if t["after"] < 0:
            keep.append(t)
            continue
        i = t["after"]
        if i + 1 >= len(tl):
            continue
        limit = 0.5 * min(tl[i].duration, tl[i + 1].duration) - 0.01
        if limit >= 0.12:
            keep.append(dict(t, duration=round(min(t["duration"], limit), 3)))
    data["transitions"] = keep


def _snap(plan: EditPlan, t: float) -> float:
    """A cut point that would leave a piece shorter than a segment may be moves to that piece's edge (a pause
    ending 0.15 s before the end of the video is removed to the end, not kept whole)."""
    for e in plan.timeline():
        end = e.end - plan.overlap_after(e.index)
        if e.start - EPS <= t <= end + EPS:
            k = e.segment.speed
            if (t - e.start) * k < MIN_SRC + 0.01:
                return e.start
            if (end - t) * k < MIN_SRC + 0.01:
                return end
            return t
    return t


def isolate(plan: EditPlan, a: float, b: float) -> tuple[EditPlan, list[int]]:
    """Split at a and b so that [a, b] is made of whole segments; returns them (indices in output order)."""
    total = plan.total_duration()
    a, b = max(0.0, a), min(total, b)
    if b - a < 0.1:
        raise ToolError(f"the window {a:.2f}-{b:.2f}s is too short")
    a, b = _snap(plan, a), _snap(plan, b)
    for k, x in enumerate((a, b)):
        if EPS < x < total - EPS:
            try:
                plan = split_at(plan, x)
            except ToolError:
                # too close to a transition: widen the window to the nearest cut on its outer side
                cuts = boundaries(plan)
                x2 = max([c for c in cuts if c <= x] or [0.0]) if k == 0 else min([c for c in cuts if c >= x] or [total])
                if k == 0:
                    a = x2
                else:
                    b = x2
    idx = [e.index for e in plan.timeline() if e.start >= a - EPS and e.end <= b + plan.overlap_after(e.index) + EPS]
    if not idx:
        raise ToolError(f"no whole shot inside {a:.2f}-{b:.2f}s")
    return plan, idx


def remove_segments(plan: EditPlan, victims: list[int]) -> EditPlan:
    """Delete segments by output index; later items move left by the time removed."""
    tl = plan.timeline()
    n = len(tl)
    keep = [i for i in range(n) if i not in set(victims)]
    if not keep:
        raise ToolError("that would remove the whole video")
    old_total = plan.total_duration()
    # removed output windows (for the timed items), measured on the old timeline
    gone = sorted((tl[i].start, tl[i].end - plan.overlap_after(i)) for i in victims)
    data = plan.to_json()
    order = sorted(range(len(data["clips"])), key=lambda k: data["clips"][k]["order"])
    remap = {old: new for new, old in enumerate(keep)}
    data["clips"] = [dict(data["clips"][order[i]], order=remap[i]) for i in keep]
    data["effects"] = [dict(fx, target=remap[fx["target"]]) if fx["target"] >= 0 else fx
                       for fx in data["effects"] if fx["target"] < 0 or fx["target"] in remap]
    trs = []
    for t in data["transitions"]:
        if t["after"] < 0:
            trs.append(t)
        elif t["after"] in remap and t["after"] + 1 in remap and remap[t["after"] + 1] == remap[t["after"]] + 1:
            trs.append(dict(t, after=remap[t["after"]]))
    data["transitions"] = trs
    data["audio_edits"] = [dict(x, after=remap[x["after"]]) for x in data.get("audio_edits", [])
                           if x["after"] in remap and x["after"] + 1 in remap
                           and remap[x["after"] + 1] == remap[x["after"]] + 1]

    def moved(t: float) -> float | None:
        shift = 0.0
        for s, e in gone:
            if t >= e:
                shift += e - s
            elif t > s:
                return None
        return t - shift

    for key in TIMED:
        items = []
        for it in data.get(key, []):
            s, e = moved(it["start"]), moved(it["end"])
            if s is None and e is None:
                continue
            if s is None:  # started inside a removed part: starts at the cut
                s = next(ms for ms in (moved(g[1]) for g in gone if g[0] < it["start"] <= g[1]) if ms is not None)
            if e is None:
                e = next(me for me in (moved(g[0]) for g in gone if g[0] < it["end"] <= g[1]) if me is not None)
            if e - s >= 0.1:
                items.append(dict(it, start=round(s, 3), end=round(e, 3)))
        data[key] = items
    # the transitions removed with the shots change the overlap a little: keep timed items inside the new length
    total = _validated({**data, **{k: [] for k in TIMED if k in data}}).total_duration()
    if total > old_total + 1e-3:
        raise ToolError("internal: removing made the video longer")
    for key in TIMED:
        data[key] = [dict(it, end=min(it["end"], round(total, 3))) for it in data.get(key, [])
                     if it["start"] < total - 0.1]
    return _validated(data)


def remove_range(plan: EditPlan, a: float, b: float) -> EditPlan:
    plan, idx = isolate(plan, a, b)
    return remove_segments(plan, idx)


def keep_range(plan: EditPlan, a: float, b: float) -> EditPlan:
    total = plan.total_duration()
    if b - a >= total - 2 * EPS:
        return plan
    if b < total - EPS:
        plan = remove_range(plan, b, total)
    if a > EPS:
        plan = remove_range(plan, 0.0, a)
    return plan


def remap_timed(old: EditPlan, data: dict[str, Any]) -> dict[str, Any]:
    """The same shots, new timing (a transition overlap, a speed change): every timed item keeps its place inside
    its shot — the output time is mapped shot by shot, scaled by the shot's new length."""
    new = EditPlan.model_validate({**data, **{k: [] for k in TIMED if k in data}})
    ot, nt = old.timeline(), new.timeline()
    if len(ot) != len(nt):
        raise ToolError("internal: remap needs the same shots")
    total = new.total_duration()

    def m(t: float) -> float:
        e = next((x for x in ot if x.start - 1e-6 <= t < x.end), ot[-1])
        n = nt[e.index]
        return n.start + (t - e.start) * (n.duration / e.duration)

    for key in TIMED:
        items = []
        for it in data.get(key, []):
            s, e = round(m(it["start"]), 3), round(min(total, m(min(it["end"], ot[-1].end - 1e-6))), 3)
            if e - s >= 0.1 and s < total - 0.1:
                items.append(dict(it, start=s, end=e))
        data[key] = items
    return data


def _validated(data: dict[str, Any]) -> EditPlan:
    try:
        return EditPlan.model_validate(data)
    except ValueError as exc:
        raise ToolError(f"that change makes an invalid edit: {str(exc)[:200]}") from exc
