"""A. Cutting and structure — trim, split, delete, merge, reorder, silence / filler / pause removal, fit to a
length, highlights, hook, montage, J / L cuts, B-roll, intro / outro cards."""

from __future__ import annotations

from typing import Any

from ..ffmpeg_utils import detect_silence
from ..plan import EditPlan, TimelineEntry
from . import generated
from .engine import ToolCtx, tool
from .timeline import EPS, ToolError, boundaries, keep_range, remove_range, split_at
from .timewin import When

FILLERS = {
    "en": {"um", "umm", "uh", "uhh", "uhm", "erm", "er", "hmm", "ah"},
    # Hindi / Hinglish: only sounds that are never a real word. "matlab", "toh", "na", "haan" are often real
    # words, so they are NOT removed (docs/SYNONYMS_FOR_HUMAN_REVIEW.md asks a native speaker).
    "hi": {"aa", "aaa", "aah", "umm", "hmm", "हम्म", "आ", "अ"},
}
_SIL_CACHE: dict[tuple[str, float, float], list[tuple[float, float]]] = {}


def _out_window(e: TimelineEntry, s: float, t: float) -> tuple[float, float] | None:
    """Source window [s, t] of the entry's clip → its output window (None if outside the segment)."""
    seg = e.segment
    s, t = max(s, seg.in_), min(t, seg.out)
    if t - s <= 1e-3:
        return None
    k = e.duration / seg.source_duration
    if seg.reverse:
        return e.start + (seg.out - t) * k, e.start + (seg.out - s) * k
    return e.start + (s - seg.in_) * k, e.start + (t - seg.in_) * k


def _remove_windows(plan: EditPlan, wins: list[tuple[float, float]], ctx: ToolCtx, what: str) -> EditPlan:
    """Remove output windows, last first (earlier times stay valid). Windows inside a transition are kept."""
    kept = 0
    for a, b in sorted(_merge(wins), reverse=True):
        try:
            plan = remove_range(plan, a, b)
        except ToolError:
            kept += 1
    if kept:
        ctx.notes.append(f"{kept} {what} kept (inside a transition or too short to cut)")
    return plan


def _merge(wins: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(wins):
        if out and a <= out[-1][1] + 0.02:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out if b - a >= 0.1]


@tool("trim")
def trim(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    total = plan.total_duration()
    a, b = float(p["start"]), float(p["end"]) if p.get("end") is not None else total
    if b > total:
        ctx.notes.append(f"the video is {total:.1f}s: kept up to the end")
        b = total
    if not 0 <= a < b:
        raise ToolError(f"trim needs start < end inside the video (0-{total:.1f}s)")
    return keep_range(plan, a, b)


@tool("split")
def split(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    t = float(p["at"])
    if any(abs(t - x) <= EPS for x in boundaries(plan)):
        ctx.notes.append(f"there is already a cut at {t:.2f}s")
        return plan
    return split_at(plan, t)


@tool("delete_segment")
def delete_segment(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    if p.get("shot") is not None:
        tl = plan.timeline()
        i = int(p["shot"]) - 1
        if not 0 <= i < len(tl):
            raise ToolError(f"there is no shot {i + 1} (the edit has {len(tl)})")
        a, b = tl[i].start, tl[i].end - plan.overlap_after(i)
    else:
        a, b = float(p["start"]), float(p["end"])
    return remove_range(plan, a, b)


@tool("merge_clips")
def merge_clips(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    from .invariants import source_duration

    ids = [c for c in ctx.clip_ids if c in ctx.sources] or sorted({c.source for c in plan.clips})
    clips = [{"source": c, "in": 0.0, "out": round(source_duration(ctx.sources[c]), 3), "order": i}
             for i, c in enumerate(ids)]
    data = plan.to_json()
    data.update(clips=clips, transitions=[t for t in data["transitions"] if t["after"] < 0],
                effects=[e for e in data["effects"] if e["target"] == -1], text=[t for t in data["text"]
                                                                                if t["kind"] == "watermark"],
                stickers=[], graphics=[], audio_edits=[])
    new = EditPlan.model_validate({**data, "text": []})
    total = new.total_duration()
    data["text"] = [dict(t, start=0.0, end=round(total, 3)) for t in data["text"]]
    data["overlays"] = [dict(o, end=min(o["end"], round(total, 3))) for o in data["overlays"] if o["start"] < total]
    ctx.notes.append(f"{len(ids)} clips joined in upload order, whole, hard cuts")
    return EditPlan.model_validate(data)


@tool("reorder_clips")
def reorder_clips(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    tl = plan.timeline()
    n = len(tl)
    if p.get("new_order"):
        new = [int(x) - 1 for x in p["new_order"]]
        if sorted(new) != list(range(n)):
            raise ToolError(f"give every shot number 1-{n} once (got {', '.join(str(x + 1) for x in new)})")
    elif p.get("move") is not None:
        frm, to = int(p["move"]) - 1, int(p.get("to", 1)) - 1
        if not (0 <= frm < n and 0 <= to < n):
            raise ToolError(f"shots are numbered 1-{n}")
        new = list(range(n))
        new.insert(to, new.pop(frm))
    else:
        new = list(reversed(range(n)))  # "ulta order"
    if new == list(range(n)):
        return plan
    data = plan.to_json()
    order = sorted(range(len(data["clips"])), key=lambda k: data["clips"][k]["order"])
    pos = {old: i for i, old in enumerate(new)}
    for old, k in enumerate(order):
        data["clips"][k]["order"] = pos[old]
    data["effects"] = [dict(e, target=pos[e["target"]]) if e["target"] >= 0 else e for e in data["effects"]]
    pairs = [t for t in data["transitions"] if t["after"] >= 0]
    data["transitions"] = [t for t in data["transitions"] if t["after"] < 0]
    data["audio_edits"] = []
    # timed items inside one shot move with it; items across shots stay where they are
    starts: dict[int, float] = {}
    cursor = 0.0
    durs = [e.duration for e in tl]
    for old in new:
        starts[old] = cursor
        cursor += durs[old]
    for key in ("text", "stickers", "graphics"):
        for it in data.get(key, []):
            home = next((e for e in tl if e.start - EPS <= it["start"] and it["end"] <= e.end + EPS), None)
            if home is not None:
                d = starts[home.index] - home.start
                it["start"], it["end"] = round(it["start"] + d, 3), round(it["end"] + d, 3)
    if pairs:  # same transition between the new neighbours (the old pairs no longer exist)
        t0 = pairs[0]
        new_plan = EditPlan.model_validate({**data, "transitions": data["transitions"]})
        ntl = new_plan.timeline()
        for i in range(n - 1):
            limit = 0.5 * min(ntl[i].duration, ntl[i + 1].duration) - 0.01
            if limit >= 0.12:
                data["transitions"].append({"type": t0["type"], "after": i, "duration": round(min(t0["duration"], limit), 3)})
        ctx.notes.append(f"'{t0['type']}' transitions re-made between the new neighbours")
    ctx.notes.append("new order: " + ", ".join(str(x + 1) for x in new))
    return EditPlan.model_validate(data)


def _silences(ctx: ToolCtx, cid: str, db: float, gap: float) -> list[tuple[float, float]]:
    key = (cid, db, gap)
    if key not in _SIL_CACHE:
        _SIL_CACHE[key] = detect_silence(ctx.sources[cid], noise_db=db, min_dur=gap)
    return _SIL_CACHE[key]


def _silence_windows(plan: EditPlan, ctx: ToolCtx, db: float, gap: float, keep: float) -> list[tuple[float, float]]:
    wins = []
    for e in plan.timeline():
        for s, t in _silences(ctx, e.segment.source, db, gap):
            # keep `keep` s of the pause on both sides (a hard cut right on a word sounds chopped)
            w = _out_window(e, s + keep, t - keep)
            if w and w[1] - w[0] >= 0.1:
                wins.append(w)
    return wins


@tool("remove_silence")
def remove_silence(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    wins = _silence_windows(plan, ctx, float(p["threshold_db"]), float(p["min_gap"]), float(p["keep"]))
    if not wins:
        ctx.notes.append(f"no pause longer than {p['min_gap']:g}s below {p['threshold_db']:g} dB")
        return plan
    before = plan.total_duration()
    plan = _remove_windows(plan, wins, ctx, "pauses")
    ctx.notes.append(f"{len(wins)} pauses removed: {before:.1f}s → {plan.total_duration():.1f}s")
    return plan


def _words(ctx: ToolCtx) -> list[tuple[str, float, float]]:
    ws = ctx.words()
    if not ws:
        raise ToolError("no speech found in this video (speech-to-text found no words)")
    return ws


@tool("remove_fillers")
def remove_fillers(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    fillers = set().union(*(FILLERS.get(lang, set()) for lang in p["languages"]))
    wins = [(s - 0.03, e + 0.03) for w, s, e in _words(ctx) if w.lower().strip(".,!?-") in fillers]
    if not wins:
        ctx.notes.append("no filler sounds (um / uh / aa) found")
        return plan
    plan = _remove_windows(plan, wins, ctx, "fillers")
    ctx.notes.append(f"{len(wins)} filler sounds removed")
    return plan


@tool("jump_cut_tighten")
def jump_cut_tighten(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    gap = float(p["max_gap"])
    try:
        ws = _words(ctx)
    except ToolError:
        ws = []
    if ws:
        wins = []
        for (_, _s1, e1), (_, s2, _e2) in zip(ws, ws[1:], strict=False):
            if s2 - e1 > gap + 0.1:
                wins.append((e1 + gap / 2, s2 - gap / 2))
        how = "gaps between words"
    else:  # no transcript: the same rule on the silence map (deterministic fallback)
        wins = _silence_windows(plan, ctx, -35.0, gap + 0.1, gap / 2)
        how = "pauses (no transcript: measured from the sound)"
    if not wins:
        ctx.notes.append(f"no pause longer than {gap:g}s")
        return plan
    before = plan.total_duration()
    plan = _remove_windows(plan, wins, ctx, "pauses")
    ctx.notes.append(f"{len(wins)} {how} tightened to {gap:g}s: {before:.1f}s → {plan.total_duration():.1f}s")
    return plan


@tool("fit_to_duration")
def fit_to_duration(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    target = float(p["target_sec"])
    total = plan.total_duration()
    if total <= target + 0.05:
        ctx.notes.append(f"the video is already {total:.1f}s (≤ {target:g}s); nothing cut — it can't be made longer "
                         "without slowing it down")
        return plan
    for _ in range(4):  # shorten every shot's tail by the same share (keeps every shot's start)
        total = plan.total_duration()
        if total <= target + 0.05:
            break
        r = target / total
        wins = []
        for e in plan.timeline():
            end = e.end - plan.overlap_after(e.index)
            keep = max(0.4, (end - e.start) * r)
            if end - (e.start + keep) >= 0.1:
                wins.append((e.start + keep, end))
        if not wins:
            break
        plan = _remove_windows(plan, wins, ctx, "shot tails")
    total = plan.total_duration()
    if total > target + 0.05:  # many tiny shots: drop the last ones
        plan = keep_range(plan, 0.0, target)
    ctx.notes.append(f"every shot shortened from its end: now {plan.total_duration():.1f}s")
    return plan


def _scores(ctx: ToolCtx, e: TimelineEntry) -> list[tuple[float, float, float]]:
    """(score, src_start, src_end) per 0.5 s of the entry's clip: picture change + loudness + speech."""
    if ctx.analysis is None:
        raise ToolError("needs the clip analysis (motion / sound), which is not available here")
    a = ctx.analysis().get(e.segment.source)
    curve = a.motion_curve or []
    out = []
    t = e.segment.in_
    words = [(w.start, w.end) for w in a.words]
    while t + 0.5 <= e.segment.out + 1e-6:
        k = int(t / 0.5)
        m = curve[k] if k < len(curve) else 0.0
        speech = any(s < t + 0.5 and w > t for s, w in words)
        silent = any(s <= t and t + 0.5 <= w for s, w in a.silences)
        out.append((m + (0.3 if speech else 0.0) - (0.2 if silent else 0.0), t, t + 0.5))
        t += 0.5
    return out


def _best_windows(plan: EditPlan, ctx: ToolCtx, length: float, count: int) -> list[tuple[str, float, float, float]]:
    """Top `count` non-overlapping windows of `length` s (source time): (clip, start, end, score)."""
    cands = []
    for e in plan.timeline():
        sc = _scores(ctx, e)
        n = max(1, int(round(length / 0.5)))
        for i in range(0, max(1, len(sc) - n + 1)):
            part = sc[i:i + n]
            s0, s1 = part[0][1], min(part[-1][2], e.segment.out)
            if s1 - s0 >= min(length, e.segment.source_duration) - 0.26:
                cands.append((sum(x[0] for x in part) / len(part), e.segment.source, s0, s1, e.index))
    cands.sort(key=lambda c: -c[0])
    picked: list[tuple[str, float, float, float]] = []
    for score, cid, s0, s1, _i in cands:
        if all(c != cid or s1 <= a or s0 >= b for c, a, b, _ in picked):
            picked.append((cid, s0, s1, score))
        if len(picked) >= count:
            break
    return picked


def _rebuild(plan: EditPlan, pieces: list[tuple[str, float, float]]) -> EditPlan:
    data = plan.to_json()
    data.update(clips=[{"source": c, "in": round(a, 3), "out": round(b, 3), "order": i}
                       for i, (c, a, b) in enumerate(pieces)],
                transitions=[], effects=[e for e in data["effects"] if e["target"] == -1],
                text=[t for t in data["text"] if t["kind"] == "watermark"], stickers=[], graphics=[], audio_edits=[])
    new = EditPlan.model_validate({**data, "text": []})
    total = new.total_duration()
    data["text"] = [dict(t, start=0.0, end=round(total, 3)) for t in data["text"]]
    data["overlays"] = [dict(o, start=0.0, end=round(total, 3)) for o in data["overlays"]]
    return EditPlan.model_validate(data)


@tool("extract_highlights")
def extract_highlights(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    picked = _best_windows(plan, ctx, float(p["length"]), int(p["count"]))
    if not picked:
        raise ToolError("no moment long enough to use as a highlight")
    order = {c: i for i, c in enumerate(ctx.clip_ids)}
    picked.sort(key=lambda x: (order.get(x[0], 0), x[1]))  # in story order
    ctx.notes.append("highlights: " + "; ".join(f"{c} {a:.1f}-{b:.1f}s (score {s:.2f})" for c, a, b, s in picked)
                     + " — picked by picture change + speech, not a human's taste")
    return _rebuild(plan, [(c, a, b) for c, a, b, _ in picked])


@tool("hook_first")
def hook_first(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    length = float(p["hook_len"])
    best = _best_windows(plan, ctx, length, 1)
    if not best:
        raise ToolError("no moment long enough for a hook")
    cid, a, b, score = best[0]
    data = plan.to_json()
    if p["mode"] == "move":  # cut it out where it was and open with it
        out = None
        for e in plan.timeline():
            w = _out_window(e, a, b) if e.segment.source == cid else None
            if w:
                out = w
                break
        if out is None:
            raise ToolError("the best moment is not in the edit")
        plan = remove_range(plan, *out)
        data = plan.to_json()
    for c in data["clips"]:
        c["order"] += 1
    data["clips"].append({"source": cid, "in": round(a, 3), "out": round(b, 3), "order": 0})
    for e in data["effects"]:
        if e["target"] >= 0:
            e["target"] += 1
    for t in data["transitions"]:
        if t["after"] >= 0:
            t["after"] += 1
    for x in data.get("audio_edits", []):
        x["after"] += 1
    shift = (b - a)
    for key in ("text", "stickers", "graphics", "overlays"):
        for it in data.get(key, []):
            if it.get("kind") == "watermark":
                it["end"] = round(it["end"] + shift, 3)
                continue
            it["start"], it["end"] = round(it["start"] + shift, 3), round(it["end"] + shift, 3)
    ctx.notes.append(f"opens with {cid} {a:.1f}-{b:.1f}s (highest picture-change + speech score {score:.2f})"
                     + (" — also kept in its place" if p["mode"] == "teaser" else ""))
    return EditPlan.model_validate(data)


@tool("montage_builder")
def montage_builder(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    shot = float(p["shot_len"])
    total = float(p["total"]) if p.get("total") else None
    per_clip: dict[str, list[tuple[float, float, float]]] = {}
    for e in plan.timeline():
        for score, s0, s1 in _scores(ctx, e):
            per_clip.setdefault(e.segment.source, []).append((score, s0, s1))
    # best `shot`-long windows of every clip, then round-robin across clips (a montage mixes sources)
    queues: list[list[tuple[str, float, float]]] = []
    for cid, sc in per_clip.items():
        n = max(1, int(round(shot / 0.5)))
        wins = []
        for i in range(0, len(sc) - n + 1, n):
            part = sc[i:i + n]
            wins.append((sum(x[0] for x in part), cid, part[0][1], part[-1][2]))
        wins.sort(key=lambda w: -w[0])
        queues.append([(c, a, b) for _, c, a, b in wins])
    pieces: list[tuple[str, float, float]] = []
    budget = total or sum(len(q) for q in queues) * shot
    while any(queues) and len(pieces) * shot < budget - 1e-6 and len(pieces) < 60:
        for q in queues:
            if q and len(pieces) * shot < budget - 1e-6:
                pieces.append(q.pop(0))
    if len(pieces) < 2:
        raise ToolError(f"not enough footage for a montage of {shot:g}s shots")
    ctx.notes.append(f"{len(pieces)} shots of {shot:g}s, mixed across {len(queues)} clips")
    return _rebuild(plan, pieces)


def _cut_index(plan: EditPlan, p: dict[str, Any]) -> list[int]:
    n = len(plan.clips)
    if n < 2:
        raise ToolError("needs at least two shots (there is no cut yet)")
    if p.get("cut") is not None:
        i = int(p["cut"]) - 1
        if not 0 <= i < n - 1:
            raise ToolError(f"cuts are numbered 1-{n - 1}")
        return [i]
    return list(range(n - 1))


def _audio_edit(plan: EditPlan, p: dict[str, Any], ctx: ToolCtx, kind: str, secs: float) -> EditPlan:
    data = plan.to_json()
    tl = plan.timeline()
    edits = [x for x in data.get("audio_edits", []) if x["after"] not in _cut_index(plan, p)]
    done = 0
    for i in _cut_index(plan, p):
        if plan.overlap_after(i) > 0:
            continue  # a transition already blends the sound here
        a, b = tl[i], tl[i + 1]
        # J: the next shot's sound starts early → it needs `secs` of source BEFORE its in-point
        # L: this shot's sound runs on → it needs `secs` of source AFTER its out-point
        from .invariants import source_duration

        if kind == "j" and (b.segment.reverse or b.segment.in_ < secs * b.segment.speed):
            continue
        if kind == "l" and (a.segment.reverse or
                            a.segment.out + secs * a.segment.speed > source_duration(ctx.sources[a.segment.source])):
            continue
        s = min(secs, 0.45 * a.duration, 0.45 * b.duration)
        edits.append({"after": i, "kind": kind, "seconds": round(s, 3)})
        done += 1
    if not done:
        raise ToolError(f"no cut has the extra {secs:g}s of sound a {kind.upper()}-cut needs "
                        "(the clip starts / ends right at the cut, or a transition is there)")
    data["audio_edits"] = sorted(edits, key=lambda x: x["after"])
    ctx.notes.append(f"{kind.upper()}-cut at {done} cut(s)")
    return EditPlan.model_validate(data)


@tool("j_cut")
def j_cut(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _audio_edit(plan, p, ctx, "j", float(p["lead_sec"]))


@tool("l_cut")
def l_cut(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _audio_edit(plan, p, ctx, "l", float(p["tail_sec"]))


@tool("insert_broll")
def insert_broll(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    """A cutaway: another clip's PICTURE over the edit for a while; the main sound keeps playing."""
    from .invariants import source_duration

    total = plan.total_duration()
    cid = p.get("clip")
    used = {c.source for c in plan.clips}
    if not cid:  # the first uploaded clip that is not in the edit, else the last clip
        cid = next((c for c in ctx.clip_ids if c not in used), ctx.clip_ids[-1] if ctx.clip_ids else None)
        if cid is None:
            raise ToolError("upload a second clip to use as B-roll")
        ctx.notes.append(f"B-roll from clip {cid} (assumed)")
    if cid not in ctx.sources:
        raise ToolError(f"there is no clip '{cid}'")
    start = float(p["start"]) if p.get("start") is not None else round(total / 3, 2)
    length = min(float(p["len"]), total - start, source_duration(ctx.sources[cid]) - float(p["src_in"]))
    if length < 0.3:
        raise ToolError("not enough room for B-roll there")
    data = plan.to_json()
    data.setdefault("graphics", []).append({
        "kind": "layer", "source": cid, "src_in": float(p["src_in"]), "start": round(start, 3),
        "end": round(start + length, 3), "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "fit": "crop",
    })
    ctx.notes.append(f"B-roll {cid} over {start:.1f}-{start + length:.1f}s; the main sound continues")
    return EditPlan.model_validate(data)


@tool("intro_outro")
def intro_outro(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    w, h = plan.canvas.size
    dur = float(p["duration"])
    which = p["which"]
    data = plan.to_json()
    for side in (["intro", "outro"] if which == "both" else [which]):
        text = p["text"] if side == "intro" or which != "both" else p["outro_text"]
        card_id, path = generated.card(ctx.gen_dir, w, h, dur, p["background"], plan.canvas.fps)
        ctx.sources[card_id] = path
        if side == "intro":
            for c in data["clips"]:
                c["order"] += 1
            for e in data["effects"]:
                if e["target"] >= 0:
                    e["target"] += 1
            for t in data["transitions"]:
                if t["after"] >= 0:
                    t["after"] += 1
            for x in data.get("audio_edits", []):
                x["after"] += 1
            for key in ("text", "stickers", "graphics", "overlays"):
                for it in data.get(key, []):
                    it["start"], it["end"] = round(it["start"] + dur, 3), round(it["end"] + dur, 3)
            data["clips"].append({"source": card_id, "in": 0.0, "out": dur, "order": 0})
            start = 0.0
        else:
            n = len(data["clips"])
            data["clips"].append({"source": card_id, "in": 0.0, "out": dur, "order": n})
            start = EditPlan.model_validate({**data, "clips": data["clips"][:-1], "text": [], "stickers": [],
                                             "graphics": [], "overlays": []}).total_duration()
        data["text"].append({"kind": "title", "text": text, "start": round(start + 0.1, 3),
                             "end": round(start + dur - 0.1, 3),
                             "style": {"position": "center", "size": 88, "box_color": None, "animation": "fade"}})
        ctx.notes.append(f"{side} card '{text}' ({dur:g}s, {p['background']})")
    return EditPlan.model_validate(data)
