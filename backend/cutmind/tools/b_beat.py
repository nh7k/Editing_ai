"""beat_edit — the whole "edit it on the beat of the song" in one skill (docs/BEAT_EDIT.md):

1. the music: the plan's song, else the user's own song (picked / newest upload), else the library;
2. the cuts: the footage's own scene cuts become shots, then every cut is moved onto the nearest beat;
3. the hits (beatmap.py): punches whose density follows the song's energy, a frame before the beat, the drop with
   the strongest punch + a flash + a shake.

Re-running it replaces its own earlier hits (it never stacks punches on punches).
"""

from __future__ import annotations

from typing import Any

from ..beatmap import kick_strength, load_mono, plan_hits
from ..plan import EditPlan, Effect
from .engine import ToolCtx, tool
from .timeline import ToolError, split_at
from .timewin import When

MARK = "beat_edit"  # params marker on the effects this skill places


def _keep_length(plan: EditPlan, total: float, ctx: ToolCtx) -> EditPlan | None:
    """The plan with its last shot trimmed / extended so the edit is `total` long again (None: the footage has no
    room for that)."""
    from .invariants import source_duration

    diff = plan.total_duration() - total
    if abs(diff) < 0.01:
        return plan
    data = plan.to_json()
    last = max(data["clips"], key=lambda c: c["order"])
    new_out = last["out"] - diff * float(last.get("speed", 1.0) or 1.0)
    src = ctx.sources.get(last["source"])
    limit = source_duration(src) if src is not None else last["out"]
    if not last["in"] + 0.2 <= new_out <= limit + 1e-3:
        return None
    last["out"] = round(new_out, 3)
    out = EditPlan.model_validate(data)
    return out if abs(out.total_duration() - total) < 0.02 else None


@tool("beat_edit")
def beat_edit(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    from ..song import analyze_song
    from .b_audio import _audio, _track, beat_sync

    if not plan.audio.music:
        t = _track(ctx, None, None)
        plan = _audio(plan, music=t.name, music_volume=0.9, music_start=0.0)
        ctx.notes.append(f"music: {t.stem} (yours)" if "projects" in t.parts else f"music: {t.stem}")
    track = _track(ctx, plan.audio.music, None)
    prof = analyze_song(track, ctx.gen_dir, ctx.gen_dir.parent / "analysis")
    if prof is None or not prof.beats:
        raise ToolError("no beat found in the music — try another song")
    start = plan.audio.music_start
    total = plan.total_duration()
    grid = [b for b in prof.grid(until=start + total + 1)]
    kicks = kick_strength(load_mono(track), sr=22050, beats=grid)
    beats = [round(b - start, 3) for b in grid if b >= start]
    kicks = [k for b, k in zip(grid, kicks, strict=False) if b >= start]
    drop = round(prof.drop - start, 3) if prof.drop is not None and prof.drop >= start else None

    # 2. cuts: the footage's own scene changes become shots, then the cuts go onto the beats
    if p["cuts"] and len(plan.timeline()) == 1 and ctx.analysis is not None:
        seg = plan.ordered_clips()[0]
        try:
            scenes = ctx.analysis().get(seg.source).scenes
        except Exception:  # noqa: BLE001 — no analysis: no scene cuts, the hits still come
            scenes = []
        made = 0
        for s in sorted(scenes, reverse=True):
            out_t = (s - seg.in_) / seg.speed
            if 0.6 < out_t < total - 0.6:
                try:
                    plan = split_at(plan, round(out_t, 3))
                    made += 1
                except ToolError:
                    continue
        if made:
            ctx.notes.append(f"{made} scene change(s) of the footage became shots")
    if p["cuts"] and len(plan.timeline()) > 1:
        before, unsynced = ctx.notes[:], plan
        plan = beat_sync(plan, {"every": 1, "max_shift": 0.35}, when, ctx)
        ctx.beats = None
        # moving cuts makes shots a little longer / shorter: the length must stay (it failed with "changed the
        # length 15.00 → 15.12 s") — the last shot takes up the difference, else the cuts stay where they were
        plan = _keep_length(plan, total, ctx)
        if plan is None:
            plan = unsynced
            ctx.notes[len(before):] = ["cuts kept where they were (moving them onto the beat would change the length)"]
        elif len(ctx.notes) > len(before):
            ctx.notes[len(before)] = "cuts moved onto the beat: " + ctx.notes[len(before)]
    total = plan.total_duration()

    # 3. hits
    intensity = {"low": 0.7, "medium": 1.0, "high": 1.3}[p["intensity"]]
    bm = plan_hits(beats, lambda t: prof.energy_at(t + start), kicks, total, drop, intensity)
    if not bm.hits:
        raise ToolError("the song has no beats inside this video's length")
    data = plan.to_json()
    data["effects"] = [e for e in data["effects"] if not (e.get("params") or {}).get(MARK)]
    tl = plan.timeline()

    def local(times: list[float], entry: Any) -> list[float]:
        return [round(x - entry.start, 3) for x in times if entry.start <= x < entry.end]

    for entry in tl:
        hits = [h for h in bm.hits if entry.start <= h.t < entry.end]
        if hits:
            data["effects"].append(Effect(type="pulse", target=entry.index, strength=1.0,
                                          times=[round(h.t - entry.start, 3) for h in hits],
                                          params={MARK: 1.0, "amps": ",".join(f"{h.strength:g}" for h in hits)}).model_dump())
        if fl := local(bm.flashes, entry):
            data["effects"].append(Effect(type="flash", target=entry.index, strength=0.55, times=fl,
                                          params={MARK: 1.0}).model_dump())
        if sh := local(bm.shakes, entry):
            data["effects"].append(Effect(type="beat_shake", target=entry.index, strength=1.0, times=sh,
                                          params={MARK: 1.0}).model_dump())
    n_drop = sum(h.kind == "drop" for h in bm.hits)
    ctx.notes.append(f"{len(bm.hits)} punches on the beat (calm part: every 4th beat, medium: every 2nd, loud: every "
                     f"beat), {len(bm.flashes)} flash(es)" + (f", the drop at {drop:.1f}s hits hardest" if n_drop and drop
                                                              is not None else ""))
    return EditPlan.model_validate(data)
