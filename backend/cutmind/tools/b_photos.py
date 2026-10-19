"""Photos → an edit ("random car edit with 2 photos"): the project's photos take turns as shots cut on the song's beat,
every shot with its own camera move (push in, pull out, drift left / right — what makes a still feel filmed), a
colour look, a vignette, a flash on the bar starts and a fade at the end.

Not generative: the photos are animated, nothing new is painted into them (placing the car on a frozen lake needs an
image / video generation model — cutmind.agent_registry lists it as unavailable on a CPU laptop).
"""

from __future__ import annotations

from typing import Any

from ..photos import is_photo_clip
from ..plan import FADE_OUT, EditPlan, Effect
from .engine import ToolCtx, tool
from .timeline import ToolError
from .timewin import When

# camera moves, one per shot in turn: keyframes [t, zoom, dx, dy, angle] relative to the shot (camera_move)
MOVES = ("push_in", "pull_out", "drift_left", "drift_right")


def _move(kind: str, d: float, a: float) -> list[list[float]]:
    if kind == "push_in":
        return [[0.0, 1.0, 0, 0, 0], [d, 1 + a, 0, 0, 0]]
    if kind == "pull_out":
        return [[0.0, 1 + a, 0, 0, 0], [d, 1.0, 0, 0, 0]]
    dx = (-1 if kind == "drift_left" else 1) * a * 0.35
    return [[0.0, 1 + a * 0.6, -dx, 0, 0], [d, 1 + a, dx, 0, 0]]


@tool("photo_montage")
def photo_montage(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    from ..song import analyze_song
    from .b_audio import _audio, _track

    photos = [cid for cid in ctx.clip_ids if cid in ctx.sources and is_photo_clip(ctx.sources[cid])]
    if not photos:
        raise ToolError("this project has no photos — add JPG / PNG photos first (videos: say 'beat pe edit karo')")
    if not plan.audio.music:
        t = _track(ctx, None, None)
        plan = _audio(plan, music=t.name, music_volume=0.9, music_start=0.0)
        ctx.notes.append(f"music: {t.stem} (yours)" if "projects" in t.parts else f"music: {t.stem}")
    track = _track(ctx, plan.audio.music, None)
    prof = analyze_song(track, ctx.gen_dir, ctx.gen_dir.parent / "analysis")
    if prof is None or not prof.beats:
        raise ToolError("no beat found in the music — try another song")
    seconds = float(p["seconds"])
    k = int(p["beats_per_shot"])
    from ..ffmpeg_utils import probe

    longest = min(probe(ctx.sources[cid]).duration for cid in photos) - 0.05  # a shot never runs past its still
    # the cuts ARE the song's beats (its grid, every k-th beat from the first one) — equal shot lengths of
    # "k x the average beat" drifted off the beat after a few shots (3 of 11 cuts on a beat, measured)
    start = plan.audio.music_start
    grid = [b for b in prof.grid(until=start + seconds + 8) if b >= start - 1e-6]
    marks = grid[::k]
    if len(marks) < 2:
        raise ToolError("the song is too short for this many seconds")
    first = marks[0]
    bounds = [0.0]
    for m in marks[1:]:
        t = m - first
        while t - bounds[-1] > longest:  # a very slow song: split a long shot (still on the grid's spacing)
            bounds.append(round(bounds[-1] + longest, 4))
        bounds.append(round(t, 4))
        if t >= seconds - 1e-6:
            break
    lens = [b - a for a, b in zip(bounds, bounds[1:], strict=False)]
    n = len(lens)
    if n < len(photos):
        lens = (lens * (len(photos) // max(1, n) + 1))[:len(photos)]
        n = len(lens)
    shot = sum(lens) / n
    data = plan.to_json()
    data["audio"]["music_start"] = round(first, 3)
    data["clips"] = [{"source": photos[i % len(photos)], "in": 0.0, "out": round(lens[i], 4), "order": i}
                     for i in range(n)]
    data["transitions"] = [{"type": "fade", "after": FADE_OUT, "duration": round(min(0.8, lens[-1] * 0.9), 3)}]
    a = float(p["move"])
    fx = [Effect(type="keyframes", target=i, points=_move(MOVES[i % len(MOVES)], lens[i], a), easing="ease_in_out")
          for i in range(n)]
    bar = max(1, round(4 / int(p["beats_per_shot"])))  # a flash where a bar starts (every 4 beats)
    fx += [Effect(type="flash", target=i, strength=0.5, times=[0.0]) for i in range(0, n, bar) if i]
    if p["look"] != "none":
        data["color"] = {**data["color"], "preset": p["look"]}
        fx.append(Effect(type="vignette", target=-1, strength=0.8))
    data["effects"] = [e.model_dump() for e in fx]
    new = EditPlan.model_validate(data)
    ctx.notes.append(f"{len(photos)} photo(s) → {n} shots of {shot:.2f}s on the beat ({prof.tempo:.0f} BPM), "
                     f"camera moves: {', '.join(m.replace('_', ' ') for m in MOVES[:min(n, 4)])}"
                     + (f", {p['look'].replace('_', ' ')} look" if p["look"] != "none" else "")
                     + ", fade at the end; the photos are animated, nothing new is generated into them")
    return new
