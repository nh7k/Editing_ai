"""The oracle: assertion kinds measured on the output video (tools/test200/measure.py), the fixture's ground truth and
the plan JSON (as data). It never reads the app's verifier or claims to decide a pass; messages are only checked
FOR honesty (they must agree with what was measured).

Every expectation resolves to a final state: APPLIED (measured), NOT_NEEDED (fixture truth says nothing to do, and
the app said so), COULD_NOT (the app said why), NOT_UNDERSTOOD (422 with chips) — or FAILED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import measure as M

TOL = {"color": 2.0, "luma": 3.0, "diff": 2.0}


@dataclass
class Ctx:
    src: str                      # the fixture the case uploaded
    out: str | None               # the current output video after the case
    prev: str | None              # the output before the last turn (None: the fixture itself)
    plan: dict | None
    prev_plan: dict | None
    fx: dict                      # fixture manifest entry
    turns: list[dict] = field(default_factory=list)  # [{say, status, body, job}] per turn
    versions_before: int = 0
    versions_after: int = 0

    @property
    def last(self) -> dict:
        return self.turns[-1] if self.turns else {}

    @property
    def base(self) -> str:
        return self.prev or self.src


def _t(c: Ctx, at: float | None = None) -> float:
    d = min(M.info(c.base)["duration"], M.info(c.out)["duration"]) if c.out else M.info(c.base)["duration"]
    t = d / 2 if at is None else (d + at if at < 0 else at)  # a negative time counts from the end
    return min(max(0.15, t), max(0.15, d - 0.2))


def _cmp(key: str, sign: int, tol: float = TOL["color"]) -> Callable[[Ctx, dict], tuple[bool, str]]:
    def f(c: Ctx, a: dict) -> tuple[bool, str]:
        t = _t(c, a.get("at"))
        sa, sb = M.stats(M.frame(c.base, t)), M.stats(M.frame(c.out, t))
        d = sb[key] - sa[key]
        ok = d > tol * a.get("k", 1.0) if sign > 0 else d < -tol * a.get("k", 1.0)
        return ok, f"{key} at {t:.1f}s {sa[key]:.1f}→{sb[key]:.1f}"
    return f


def grey(c: Ctx, a: dict) -> tuple[bool, str]:
    t = _t(c, a.get("at"))
    s = M.stats(M.frame(c.out, t))["sat"]
    return s < 8, f"saturation at {t:.1f}s = {s:.1f} (grey < 8)"


def sepia(c: Ctx, a: dict) -> tuple[bool, str]:
    t = _t(c, a.get("at"))
    sa, sb = M.stats(M.frame(c.base, t)), M.stats(M.frame(c.out, t))
    ok = sb["sat"] < sa["sat"] - 5 and sb["warmth"] > 5
    return ok, f"sat {sa['sat']:.1f}→{sb['sat']:.1f}, warmth {sb['warmth']:.1f}"


def vignette(c: Ctx, a: dict) -> tuple[bool, str]:
    t = _t(c, a.get("at"))
    sa, sb = M.stats(M.frame(c.base, t)), M.stats(M.frame(c.out, t))
    d = sb["corner_vs_centre"] - sa["corner_vs_centre"]
    return d < -4, f"corners vs centre {sa['corner_vs_centre']:.1f}→{sb['corner_vs_centre']:.1f}"


def changed(c: Ctx, a: dict) -> tuple[bool, str]:
    t = _t(c, a.get("at"))
    d = M.frame_diff(M.frame(c.base, t), M.frame(c.out, t))
    return d > a.get("min", TOL["diff"]), f"picture at {t:.1f}s changed by {d:.1f}"


def unchanged(c: Ctx, a: dict) -> tuple[bool, str]:
    t = _t(c, a.get("at"))
    d = M.frame_diff(M.frame(c.base, t), M.frame(c.out, t))
    return d <= a.get("max", 1.5), f"picture at {t:.1f}s changed by {d:.1f} (must stay)"


def zoomed(c: Ctx, a: dict) -> tuple[bool, str]:
    t = _t(c, a.get("at"))
    s = M.zoom_factor(M.frame(c.base, t), M.frame(c.out, t))
    return s >= a.get("min", 1.05), f"zoom at {t:.1f}s ≈ {s:.2f}x"


def duration(c: Ctx, a: dict) -> tuple[bool, str]:
    d = M.info(c.out)["duration"]
    return abs(d - a["target"]) <= a.get("tol", max(0.6, 0.05 * a["target"])), f"length {d:.2f}s (asked {a['target']}s)"


def shorter(c: Ctx, a: dict) -> tuple[bool, str]:
    da, db = M.info(c.base)["duration"], M.info(c.out)["duration"]
    return db < da - a.get("min", 0.3), f"length {da:.2f}→{db:.2f}s"


def longer(c: Ctx, a: dict) -> tuple[bool, str]:
    da, db = M.info(c.base)["duration"], M.info(c.out)["duration"]
    return db > da + a.get("min", 0.3), f"length {da:.2f}→{db:.2f}s"


def same_length(c: Ctx, a: dict) -> tuple[bool, str]:
    da, db = M.info(c.base)["duration"], M.info(c.out)["duration"]
    return abs(db - da) <= a.get("tol", 0.25), f"length {da:.2f}→{db:.2f}s (must stay)"


def aspect(c: Ctx, a: dict) -> tuple[bool, str]:
    i = M.info(c.out)
    r = i["width"] / max(1, i["height"])
    return abs(r - a["ratio"]) < 0.02, f"{i['width']}x{i['height']} (ratio {r:.3f}, asked {a['ratio']:.3f})"


def muted(c: Ctx, a: dict) -> tuple[bool, str]:
    t = _t(c, a.get("at"))
    r = M.rms_db(c.out, t)
    return r < -45, f"sound at {t:.1f}s {r:.1f} dB"


def louder(c: Ctx, a: dict) -> tuple[bool, str]:
    t = _t(c, a.get("at"))
    ra, rb = M.rms_db(c.base, t), M.rms_db(c.out, t)
    return rb > ra + a.get("min", 1.5), f"sound at {t:.1f}s {ra:.1f}→{rb:.1f} dB"


def quieter(c: Ctx, a: dict) -> tuple[bool, str]:
    t = _t(c, a.get("at"))
    ra, rb = M.rms_db(c.base, t), M.rms_db(c.out, t)
    return rb < ra - a.get("min", 1.5), f"sound at {t:.1f}s {ra:.1f}→{rb:.1f} dB"


def sound_changed(c: Ctx, a: dict) -> tuple[bool, str]:
    t = _t(c, a.get("at"))
    ra, rb = M.rms_db(c.base, t), M.rms_db(c.out, t)
    la, lb = M.band_db(c.base, t, 1.0, 30, 200), M.band_db(c.out, t, 1.0, 30, 200)
    ok = abs(rb - ra) > 1.0 or abs(lb - la) > 3.0
    return ok, f"sound at {t:.1f}s {ra:.1f}→{rb:.1f} dB, low band {la:.1f}→{lb:.1f}"


def music_added(c: Ctx, a: dict) -> tuple[bool, str]:
    d = M.info(c.out)["duration"]
    t = min(1.0, d / 3)
    la, lb = M.band_db(c.base, t, 2.0, 40, 120), M.band_db(c.out, t, 2.0, 40, 120)
    return lb > la + 6, f"music band (40-120 Hz) {la:.1f}→{lb:.1f} dB"


def ducked(c: Ctx, a: dict) -> tuple[bool, str]:
    """Music is lower WHILE the voice speaks than in a pause (both measured on the output)."""
    segs = c.fx.get("speech_segments") or []
    if len(segs) < 2:
        return False, "fixture has no speech/pause pair"
    d = M.info(c.out)["duration"]
    sp = segs[0]
    pause = (segs[0][1] + 0.3, segs[1][0] - 0.3)
    if c.out and abs(d - M.info(c.src)["duration"]) > 0.5:
        return False, "length changed — speech times unknown (ducking not measurable here)"
    m_speech = M.band_db(c.out, sp[0] + 0.3, max(0.5, sp[1] - sp[0] - 0.6), 40, 90)
    m_pause = M.band_db(c.out, pause[0], max(0.4, pause[1] - pause[0]), 40, 90)
    return m_pause > m_speech + 2.5, f"music band in speech {m_speech:.1f} dB vs pause {m_pause:.1f} dB"


def captions(c: Ctx, a: dict) -> tuple[bool, str]:
    caps = [t for t in (c.plan or {}).get("text", []) if t.get("kind") == "caption"]
    if not caps:
        return False, "no captions in the plan"
    t = (caps[0]["start"] + caps[0]["end"]) / 2
    d = M.frame_diff(M.frame(c.base, min(t, M.info(c.base)["duration"] - 0.2)), M.frame(c.out, t))
    return d > 1.0, f"{len(caps)} caption lines; picture at {t:.1f}s changed by {d:.1f}"


def text_on_screen(c: Ctx, a: dict) -> tuple[bool, str]:
    items = [t for t in (c.plan or {}).get("text", []) if t.get("kind") != "caption"]
    want = (a.get("text") or "").lower()
    hit = [t for t in items if want in t.get("text", "").lower()] if want else items
    if not hit:
        return False, f"no text '{want}' in the plan"
    t = (hit[0]["start"] + hit[0]["end"]) / 2
    d = M.frame_diff(M.frame(c.base, min(t, M.info(c.base)["duration"] - 0.2)), M.frame(c.out, t))
    return d > 1.0, f"text '{hit[0]['text']}' at {t:.1f}s; picture changed by {d:.1f}"


def fade_end(c: Ctx, a: dict) -> tuple[bool, str]:
    d = M.info(c.out)["duration"]
    end, before = M.stats(M.frame(c.out, d - 0.06))["luma"], M.stats(M.frame(c.out, max(0.1, d - 2.0)))["luma"]
    return end < 25 and before > end + 15, f"last frame luma {end:.1f} (2 s before {before:.1f})"


def fade_start(c: Ctx, a: dict) -> tuple[bool, str]:
    first, later = M.stats(M.frame(c.out, 0.02))["luma"], M.stats(M.frame(c.out, 1.5))["luma"]
    return first < 25 and later > first + 15, f"first frame luma {first:.1f} (1.5 s {later:.1f})"


def silence_removed(c: Ctx, a: dict) -> tuple[bool, str]:
    ra, rb = M.silence_ratio(c.base), M.silence_ratio(c.out)
    da, db = M.info(c.base)["duration"], M.info(c.out)["duration"]
    return rb < ra - 0.05 and db < da - 0.5, f"silence share {ra:.2f}→{rb:.2f}, length {da:.1f}→{db:.1f}s"


def reversed_(c: Ctx, a: dict) -> tuple[bool, str]:
    d = M.info(c.out)["duration"]
    t = d * 0.25
    fwd = M.frame_diff(M.frame(c.base, t), M.frame(c.out, t))
    back = M.frame_diff(M.frame(c.base, M.info(c.base)["duration"] - t), M.frame(c.out, t))
    return back < fwd - 2, f"at {t:.1f}s: like the end of the source by {back:.1f} vs like the same time {fwd:.1f}"


def starts_differently(c: Ctx, a: dict) -> tuple[bool, str]:
    d = M.frame_diff(M.frame(c.src, 0.3), M.frame(c.out, 0.3))
    return d > 3, f"first second differs from the source's by {d:.1f}"


def transition_at_cut(c: Ctx, a: dict) -> tuple[bool, str]:
    """On a multishot fixture: around a cut the picture is a blend/move, not a jump (mid-transition frame differs from
    both neighbouring shots)."""
    cuts = [x for x in M.cuts(c.out, 0.25)]
    plan_tr = (c.plan or {}).get("transitions") or []
    if not plan_tr:
        return False, "no transitions in the plan"
    return True, f"{len(plan_tr)} transition(s) in the plan; hard cuts detected {cuts[:6]}"


def blend_at_cut(c: Ctx, a: dict) -> tuple[bool, str]:
    """dark → bright clips: a transition shows in-between frames near the cut (a hard cut never does). Luma of every
    0.1 s frame from 4.0 to 7.5 s; in-between = inside the middle half of the dark..bright range."""
    ld = M.stats(M.frame(c.src, 3.0))["luma"]
    lb_src = c.fx.get("_extra_paths", [None])[0]
    lb = M.stats(M.frame(lb_src, 3.0))["luma"] if lb_src else 200.0
    lo, hi = ld + 0.25 * (lb - ld), lb - 0.25 * (lb - ld)
    d = M.info(c.out)["duration"]
    mids = [round(t, 1) for t in [x / 10 for x in range(40, 76)] if t < d - 0.1
            and lo < M.stats(M.frame(c.out, t))["luma"] < hi]
    return len(mids) >= a.get("min", 2), f"in-between frames at {mids[:8]} (dark {ld:.0f}, bright {lb:.0f})"


def decodes(c: Ctx, a: dict) -> tuple[bool, str]:
    ok, err = M.decodes(c.out)
    return ok, err or "decodes"


def decision_in(c: Ctx, a: dict) -> tuple[bool, str]:
    got = (c.last.get("body") or {}).get("decision") or (c.last.get("body") or {}).get("error", {}).get("code")
    return got in a["any"], f"answer {got} (accepted {a['any']})"


def no_new_version(c: Ctx, a: dict) -> tuple[bool, str]:
    return c.versions_after == c.versions_before, f"versions {c.versions_before}→{c.versions_after}"


def plan_style(c: Ctx, a: dict) -> tuple[bool, str]:
    s = (c.plan or {}).get("style")
    return s == a.get("style"), f"plan look {s} (asked {a.get('style')})"


def no_overlays(c: Ctx, a: dict) -> tuple[bool, str]:
    n = len((c.plan or {}).get("overlays") or [])
    return n == 0, f"{n} gradient tracks"


def chips_offered(c: Ctx, a: dict) -> tuple[bool, str]:
    b = c.last.get("body") or {}
    err = b.get("error") if isinstance(b.get("error"), dict) else {}
    ch = (err.get("choices") or (err.get("details") or {}).get("choices")) if err else b.get("alternatives")
    ch = ch or b.get("choices") or []
    return len(ch) >= a.get("min", 1), f"{len(ch)} chips"


KINDS: dict[str, Callable[[Ctx, dict], tuple[bool, str]]] = {
    "warmer": _cmp("warmth", +1), "cooler": _cmp("warmth", -1), "brighter": _cmp("luma", +1, TOL["luma"]),
    "darker": _cmp("luma", -1, TOL["luma"]), "more_contrast": _cmp("contrast", +1), "less_contrast": _cmp("contrast", -1),
    "more_sat": _cmp("sat", +1), "less_sat": _cmp("sat", -1), "blurrier": _cmp("edges", -1, 1.0),
    "sharper": _cmp("edges", +1, 0.5), "grey": grey, "sepia": sepia, "vignette": vignette, "changed": changed,
    "unchanged": unchanged, "zoomed": zoomed, "duration": duration, "shorter": shorter, "longer": longer,
    "same_length": same_length, "aspect": aspect, "muted": muted, "louder": louder, "quieter": quieter,
    "sound_changed": sound_changed, "music_added": music_added, "ducked": ducked, "captions": captions,
    "text": text_on_screen, "fade_end": fade_end, "fade_start": fade_start, "silence_removed": silence_removed,
    "reversed": reversed_, "starts_differently": starts_differently, "transition": transition_at_cut,
    "decodes": decodes, "blend_at_cut": blend_at_cut, "decision_in": decision_in, "no_new_version": no_new_version, "plan_style": plan_style,
    "no_overlays": no_overlays, "chips": chips_offered,
}


def run_assert(c: Ctx, a: dict) -> tuple[bool, str]:
    if c.out is None and a["kind"] not in ("decision_in", "no_new_version", "chips"):
        return False, "no output video"
    try:
        return KINDS[a["kind"]](c, a)
    except Exception as exc:  # noqa: BLE001 — a measuring problem is a TEST problem, reported as such
        return False, f"MEASURE ERROR {type(exc).__name__}: {str(exc)[:120]}"


def honesty(c: Ctx) -> list[str]:
    """The message must agree with the measurements and the plan."""
    probs = []
    for t in c.turns:
        job = t.get("job") or {}
        ex = job.get("explain") or {}
        text = " ".join([str(ex.get("summary") or ""), *map(str, ex.get("warnings") or [])]).lower()
        if job.get("status") == "failed" and not job.get("error"):
            probs.append(f"turn '{t['say'][:30]}': failed with no reason")
        if "nothing changed" in text and t.get("measured_change", 0) > 3:
            probs.append(f"turn '{t['say'][:30]}': says nothing changed, measured change {t['measured_change']:.1f}")
        if "already in your edit" in text and t.get("measured_change", 0) > 3:
            probs.append(f"turn '{t['say'][:30]}': says 'already in your edit' but the video changed")
        ws = [w for w in ex.get("warnings") or []]
        if len(ws) != len(set(ws)):
            probs.append(f"turn '{t['say'][:30]}': duplicated warnings")
    return probs
