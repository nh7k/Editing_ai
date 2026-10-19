"""Photos → an edit ("random car edit with 2 photos"), the way an editor cuts stills: every photo gives several
SHOTS — the wide frame, a medium and two close-ups on its most detailed areas (cutmind.photos.photo_views: edge
density, no fixed spots) — and the shots are cut on the song's beat: a wide hero shot opens, close-ups come fast
where the song is loud (a cut every beat) and slower where it is calm (every 2nd beat), a wide shot closes with a
pull-out and a fade. Every shot has its own camera move; the beat edit's punches, flashes and shakes follow the
song's energy on top; a colour look with more contrast and a vignette.

Not generative: the photos are framed and animated, nothing new is painted into them (placing the car on a frozen
lake needs an image / video generation model — cutmind.agent_registry lists it as unavailable on a CPU laptop).
"""

from __future__ import annotations

from statistics import median
from typing import Any

from ..photos import is_photo_clip, photo_original, photo_views
from ..plan import FADE_OUT, EditPlan, Effect
from .engine import ToolCtx, tool
from .timeline import ToolError
from .timewin import When

# camera move per kind of shot: keyframes [t, zoom, dx, dy, angle] relative to the shot (camera_move.replay_filters)
MOVES = ("push_in", "drift_left", "pull_out", "drift_right")


def _move(kind: str, d: float, a: float) -> list[list[float]]:
    if kind == "push_in":
        return [[0.0, 1.0, 0, 0, 0], [d, 1 + a, 0, 0, 0]]
    if kind == "pull_out":
        return [[0.0, 1 + a, 0, 0, 0], [d, 1.0, 0, 0, 0]]
    dx = (-1 if kind == "drift_left" else 1) * a * 0.35
    return [[0.0, 1 + a * 0.6, -dx, 0, 0], [d, 1 + a, dx, 0, 0]]


def _order(photos: list[str], views: dict[str, dict[str, str]], n: int) -> list[tuple[str, str]]:
    """(photo, view) per shot: a wide hero first (every photo once), then close-ups / mediums in turn across the
    photos (never the same view twice in a row), a wide shot last."""
    body_kinds = ("detail1", "medium", "detail2")
    seq = [(p, "wide") for p in photos]
    k = 0
    while len(seq) < n - 1:
        p = photos[k % len(photos)]
        kind = body_kinds[(k // len(photos)) % len(body_kinds)]
        seq.append((p, kind))
        k += 1
    seq = seq[: max(1, n - 1)] + [(photos[0], "wide")]
    return seq[:n]


@tool("photo_montage")
def photo_montage(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    from ..song import analyze_song
    from .b_audio import _audio, _track
    from .b_beat import beat_edit

    photos = [cid for cid in ctx.clip_ids if cid in ctx.sources and is_photo_clip(ctx.sources[cid])]
    if not photos:
        raise ToolError("this project has no photos — add JPG / PNG photos first (videos: say 'beat pe edit karo')")
    if not plan.audio.music:
        t = _track(ctx, None, "upbeat")  # a photo edit needs drive: the user's song, else an upbeat library track
        plan = _audio(plan, music=t.name, music_volume=0.9, music_start=0.0)
        ctx.notes.append(f"music: {t.stem} (yours)" if "projects" in t.parts else f"music: {t.stem}")
    track = _track(ctx, plan.audio.music, None)
    prof = analyze_song(track, ctx.gen_dir, ctx.gen_dir.parent / "analysis")
    if prof is None or not prof.beats:
        raise ToolError("no beat found in the music — try another song")

    # shots per photo, framed for this canvas
    w, h = plan.canvas.size
    views: dict[str, dict[str, str]] = {}
    for cid in photos:
        orig = photo_original(ctx.sources[cid])
        if orig is None:
            raise ToolError("the original photo is missing next to its clip — upload the photo again")
        made = photo_views(orig, w / h, ctx.gen_dir)
        views[cid] = {}
        for kind, path in made.items():
            ctx.sources[path.stem] = path
            views[cid][kind] = path.stem

    # the cuts ARE the song's beats: every beat where the song is louder than its middle, every 2nd beat where calmer
    seconds = float(p["seconds"])
    start = plan.audio.music_start
    grid = [b for b in prof.grid(until=start + seconds + 8) if b >= start - 1e-6]
    if len(grid) < 4:
        raise ToolError("the song is too short for this many seconds")
    first = grid[0]
    mid = median(prof.energy_at(b) for b in grid) if prof.energy else 0.5
    base = max(1, int(p["beats_per_shot"]))
    bounds, i = [0.0], 0
    longest = 4.9  # a still clip is 5 s
    while i < len(grid) - 1 and bounds[-1] < seconds - 1e-6:
        opening, closing = len(bounds) == 1, bounds[-1] >= seconds - 2 * prof.period * base
        step = 2 * base if opening or closing else (base if prof.energy_at(grid[i]) >= mid else 2 * base)
        j = min(i + step, len(grid) - 1)
        t = min(grid[j] - first, bounds[-1] + longest)
        if t - bounds[-1] < 0.25:
            break
        bounds.append(round(t, 4))
        i = j
    lens = [b - a for a, b in zip(bounds, bounds[1:], strict=False)]
    n = len(lens)
    if n < 2:
        raise ToolError("the song is too short for an edit — choose a longer length")
    order = _order(photos, views, n)

    data = plan.to_json()
    data["audio"]["music_start"] = round(first, 3)
    data["clips"] = [{"source": views[ph][kind], "in": 0.0, "out": round(lens[k], 4), "order": k}
                     for k, (ph, kind) in enumerate(order)]
    data["transitions"] = [{"type": "fade", "after": FADE_OUT, "duration": round(min(0.8, lens[-1] * 0.9), 3)}]
    a = float(p["move"])
    fx = []
    for k, (_ph, kind) in enumerate(order):
        if k == n - 1:
            move = "pull_out"  # the last shot opens up and fades
        elif kind == "wide":
            move = "push_in"
        else:
            move = MOVES[k % len(MOVES)]
        amount = a if kind == "wide" else a * 0.7  # close-ups move less (they are already tight)
        fx.append(Effect(type="keyframes", target=k, points=_move(move, lens[k], amount), easing="ease_in_out"))
    if p["look"] != "none":
        data["color"] = {**data["color"], "preset": p["look"], "contrast": 1.12, "saturation": 0.92}
        fx.append(Effect(type="vignette", target=-1, strength=0.9))
    data["effects"] = [e.model_dump() for e in fx]
    new = EditPlan.model_validate(data)
    notes = len(ctx.notes)
    # the hits on top: punches whose density follows the song's energy, flashes, a shake on the drop (beat_edit)
    new = beat_edit(new, {"intensity": p["intensity"], "cuts": False}, when, ctx)
    hits = ctx.notes[notes:]
    del ctx.notes[notes:]
    kinds = sorted({k for _p, k in order})
    ctx.notes.append(f"{len(photos)} photo(s) → {n} shots ({', '.join(kinds)}) cut on the beat ({prof.tempo:.0f} BPM: "
                     f"every beat where the song is loud, every 2nd where calm); a camera move per shot, "
                     + (f"{p['look'].replace('_', ' ')} look, " if p["look"] != "none" else "")
                     + "fade at the end; " + "; ".join(hits)
                     + " — the photos are framed and animated, nothing new is generated into them")
    return new
