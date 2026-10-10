"""Skill calls → an Intent patch (the structured way agents and the app use the registry).

    call = {"id": "zoom_in", "params": {"strength": 1.4},
            "time": {"mode": "between_times", "start": 2, "end": 4}}

Time modes: whole · between_times (start, end) · intermittent (every, length[, start, end]) · at_moment (at[, length])
· segment (start, end of a shot — same as between_times). at_beats / on_words / on_scene_change are served by the
skills that implement them inside the agents (punch on beats, stickers on words) and are refused for the rest.

The patch has `from_comment=True`: memory merges it on top of the current edit (earlier changes stay, timed parts
add up). Unknown skills, planned / blocked skills, unsupported time modes and out-of-range parameters are refused
with a clear message — never silently ignored.
"""

from __future__ import annotations

from typing import Any

from .intent import Intent, TimedEffect, parse_intent
from .skill_registry import fill, load

MOMENT_SECONDS = 2.5


class SkillError(ValueError):
    pass


def _params(s: dict[str, Any], given: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in (given or {}).items():
        spec = s["params"].get(k)
        if spec is None:
            raise SkillError(f"{s['id']}: unknown parameter '{k}' (allowed: {', '.join(s['params']) or 'none'})")
        if spec["type"] in ("number", "integer"):
            try:
                v = float(v)
            except (TypeError, ValueError) as exc:
                raise SkillError(f"{s['id']}: '{k}' must be a number") from exc
            if ("min" in spec and v < spec["min"]) or ("max" in spec and v > spec["max"]):
                raise SkillError(f"{s['id']}: '{k}' must be between {spec.get('min')} and {spec.get('max')}")
        if spec["type"] == "enum" and v not in spec.get("choices", []):
            raise SkillError(f"{s['id']}: '{k}' must be one of {spec.get('choices')}")
        out[k] = v
    return out


def _windows(time: dict[str, Any], total: float) -> list[tuple[float, float]]:
    mode = time.get("mode", "whole")
    if mode in ("between_times", "segment"):
        a, b = float(time.get("start", 0)), float(time.get("end", total))
        if not 0 <= a < b <= total + 0.05:
            raise SkillError(f"time {a:g}-{b:g}s is outside the video (0-{total:.1f}s)")
        return [(a, min(b, total))]
    if mode == "at_moment":
        a = float(time.get("at", 0))
        if not 0 <= a < total:
            raise SkillError(f"{a:g}s is outside the video (0-{total:.1f}s)")
        return [(a, min(total, a + float(time.get("length", MOMENT_SECONDS))))]
    if mode == "intermittent":  # "beech beech me": every N s for L s
        every, length = float(time.get("every", 5.0)), float(time.get("length", 1.0))
        if every <= length or length <= 0:
            raise SkillError("intermittent needs every > length > 0")
        start, end = float(time.get("start", 0)), float(time.get("end", total))
        out, t = [], start
        while t < min(end, total) - 0.2 and len(out) < 40:
            out.append((round(t, 3), round(min(t + length, total), 3)))
            t += every
        return out
    raise SkillError(f"time mode '{mode}' is not available for this skill here")


def apply(calls: list[dict[str, Any]], total: float) -> tuple[Intent, list[str]]:
    """Skill calls → (Intent patch, plain notes). Raises SkillError with a user-facing reason."""
    from .moment import moment_intent, read_comment

    reg = load()
    it = Intent(from_comment=True)
    notes: list[str] = []
    default = Intent().model_dump()
    timed: list[TimedEffect] = []
    for call in calls:
        sid = str(call.get("id", ""))
        s = reg.get(sid)
        if s is None:
            raise SkillError(f"unknown skill '{sid}'")
        if s["status"] in ("planned", "blocked") or s["impl"]["kind"] in ("planned", "blocked"):
            raise SkillError(f"'{s['name']}' is not available yet ({s['status']}): {s['impl'].get('reason', '')}")
        params = _params(s, call.get("params") or {})
        time = call.get("time") or {"mode": "whole"}
        mode = time.get("mode", "whole")
        if mode not in s["time_modes"]:
            raise SkillError(f"'{s['name']}' cannot be used '{mode}' (it supports: {', '.join(s['time_modes'])})")
        kind, ref = s["impl"]["kind"], fill(str(s["impl"].get("ref", "")), s, **params)
        strength = float(params.get(s["impl"].get("strength_param", ""), 1.0)) if s["impl"].get("strength_param") else 1.0
        if kind == "effect":
            if mode == "whole":
                it.effects = [*it.effects, ref]
            else:
                for a, b in _windows(time, total):
                    timed.append(TimedEffect(effect=ref, start=a, end=b, strength=max(0.2, min(3.0, strength)),
                                             preset=params.get("preset"), easing=params.get("easing")))
        elif kind == "look":
            it.color_preset = ref  # type: ignore[assignment]
        elif kind == "transition":
            it.transition = ref  # type: ignore[assignment]
        elif kind == "text_style":
            it.text_style = ref
        elif kind == "text_anim":
            it.text_animation = ref  # type: ignore[assignment]
        elif kind == "intent":
            got = parse_intent(ref).model_dump()
            for k, v in got.items():
                if k not in ("recognized", "inferred_fields", "limits") and v != default.get(k):
                    setattr(it, k, v)
        elif kind == "moment":
            (a, b), = _windows(time, total)
            c = read_comment(ref)
            if not c["understood"]:
                raise SkillError(f"'{s['name']}': '{ref}' is not understood")
            m = moment_intent({"at": a, "end": b, **c})
            it.moment_stickers = [*it.moment_stickers, *m.moment_stickers]
            it.timed_texts = [*it.timed_texts, *m.timed_texts]
        notes.append(f"{s['name']}" + ("" if mode == "whole" else f" ({mode})"))
    it.timed_effects = [*it.timed_effects, *timed]
    it.recognized = [f"skill: {n}" for n in notes]
    return it, notes
