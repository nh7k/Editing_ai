"""Effect stack resolver: a deterministic order and conflict rules for the effects on a shot.

The renderer applies a segment's effects in list order, so the order is part of the look:
  geometry (zoom / pan / shake / camera moves / mirror)  — moves the picture first, so nothing drawn later is scaled
  time blend (ghost trail, echo)                         — mixes frames of the moved picture
  colour (B&W, duotone, colour pop, posterize …)          — grades the picture
  glitch (RGB split, pixelate, impact)                    — distorts the graded picture
  texture (grain, VHS, old film, scanlines, vignette, letterbox) — sits on top: a vignette zoomed by a later zoom
                                                            would no longer hug the corners; grain scaled up looks muddy
  flash (flash, strobe)                                    — brightness spikes last, over everything
Text and stickers are drawn after all of this (renderer.finish), transitions join the segments, audio is separate.

Merge: the same effect twice on the same shot (no beat times) keeps the stronger one.
Conflicts: effects that undo each other on the same shot (B&W vs colour pop / duotone, zoom in vs zoom out) — the
one asked for LAST wins and the other is dropped, with a note for the user.
"""

from __future__ import annotations

from typing import Any

GEOMETRY = {"stabilize", "crop", "zoom", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "shake", "swing", "pulse", "rotate_slow", "tilt",
            "follow", "person_zoom", "spotlight", "camera_move", "keyframes", "punch", "punch_static", "drift", "mirror",
            "kaleidoscope", "fisheye", "speed_ramp", "blur_background"}
TIME_BLEND = {"ghost_trail", "echo"}
COLOR = {"grade", "mono", "film_bw", "invert_mono", "silhouette", "duotone_blue_pink", "duotone_teal_gold", "color_pop",
         "posterize", "negative", "thermal", "night_vision", "sketch", "neon_edges", "dreamy", "sharpen", "blur"}
GLITCH = {"glitch", "rgb_split", "pixelate", "impact"}
TEXTURE = {"film_grain", "old_film", "vhs", "scanlines", "vignette", "letterbox"}
FLASH = {"flash", "strobe"}
ORDER = [GEOMETRY, TIME_BLEND, COLOR, GLITCH, TEXTURE, FLASH]

# pairs that undo each other on the same shot
CONFLICTS: list[tuple[set[str], set[str]]] = [
    ({"mono", "film_bw", "invert_mono", "silhouette"}, {"color_pop", "duotone_blue_pink", "duotone_teal_gold"}),
    ({"zoom"}, {"zoom_out"}),
]


def stage(effect_type: str) -> int:
    for i, group in enumerate(ORDER):
        if effect_type in group:
            return i
    return 2  # unknown: with the colour effects


def _overlap(a: Any, b: Any) -> bool:
    return a.target == -1 or b.target == -1 or a.target == b.target


def resolve(plan: Any) -> tuple[Any, list[str]]:
    """The plan with its effects merged, de-conflicted and ordered; plus plain notes of what changed."""
    notes: list[str] = []
    effects = list(plan.effects)
    # 1) merge duplicates (same type, same shot, no beat times): the stronger one stays
    merged: list[Any] = []
    for e in effects:
        twin = next((m for m in merged if m.type == e.type and m.target == e.target and not m.times and not e.times
                     and not m.points and not e.points), None)
        if twin is not None:
            if twin.params or e.params:  # parametric (grade, crop …): one effect with both asks, the later wins per key
                merged[merged.index(twin)] = twin.model_copy(update={"params": {**twin.params, **e.params},
                                                                     "strength": max(twin.strength, e.strength)})
                notes.append(f"{e.type} settings on the same shot merged")
                continue
            if e.strength > twin.strength:
                merged[merged.index(twin)] = e
            notes.append(f"{e.type} was asked twice on the same shot — kept once (the stronger)")
            continue
        merged.append(e)
    # 2) conflicts: the later ask wins
    keep = [True] * len(merged)
    for i, a in enumerate(merged):
        for j in range(i + 1, len(merged)):
            b = merged[j]
            if not (keep[i] and keep[j]) or not _overlap(a, b):
                continue
            for left, right in CONFLICTS:
                if (a.type in left and b.type in right) or (a.type in right and b.type in left):
                    keep[i] = False
                    notes.append(f"{a.type} and {b.type} cancel each other on the same shot — kept {b.type} "
                                 "(asked later)")
    merged = [e for e, k in zip(merged, keep) if k]
    # 3) order by stage (stable: same-stage effects keep the order they were asked in)
    ordered = sorted(merged, key=lambda e: stage(e.type))
    if [e.type for e in ordered] != [e.type for e in merged]:
        notes.append("effects ordered: moves → colour → texture → flashes")
    return plan.model_copy(update={"effects": ordered}), notes
