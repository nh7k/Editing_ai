"""Run Tier 1 tool calls on an Edit Plan: params → time → builder → invariants → explain-back.

A call is {"id": "zoom_in", "params": {...}, "time": {"mode": "between_times", "start": 2, "end": 5}}.
All calls of one request are applied in order on a copy; if any fails, nothing is applied (the old plan stays —
the user's previous version is untouched, and undo / restore work on versions as before).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..plan import EditPlan
from . import invariants, spec
from .timeline import ToolError
from .timewin import When, resolve

Builder = Callable[[EditPlan, dict[str, Any], When, "ToolCtx"], EditPlan]
_BUILDERS: dict[str, Builder] = {}
MODULES = ("b_beat", "b_speech", "b_cutting", "b_layout", "b_color", "b_motion", "b_transitions", "b_audio", "b_text", "b_stylize",
           "b_delivery", "b_restore")


def tool(name: str) -> Callable[[Builder], Builder]:
    def deco(fn: Builder) -> Builder:
        _BUILDERS[name] = fn
        return fn
    return deco


def _load_builders() -> None:
    for m in MODULES:
        try:
            importlib.import_module(f"{__package__}.{m}")
        except ModuleNotFoundError as exc:  # a category not built yet
            if exc.name != f"{__package__}.{m}":
                raise


def builder_names() -> set[str]:
    _load_builders()
    return {f"{fn.__module__.rsplit('.', 1)[-1][2:]}.{name}" for name, fn in _BUILDERS.items()}


@dataclass
class ToolCtx:
    sources: dict[str, Path]                                  # clip id → media (read-only originals)
    gen_dir: Path                                             # generated media (cards, sound effects)
    clip_ids: list[str] = field(default_factory=list)         # upload order
    analysis: Callable[[], Any] | None = None                 # lazy ProjectAnalysis (words, silences, scenes…)
    beats: Callable[[], list[float]] | None = None            # output-time beats of the music
    music_dirs: list[Path] = field(default_factory=list)
    logo: Path | None = None
    notes: list[str] = field(default_factory=list)
    plan: EditPlan | None = None                              # the plan the current call works on

    def words(self) -> list[tuple[str, float, float]]:
        """Words in OUTPUT time (only those still in the edit), from the analysis' source-time words."""
        if self.analysis is None or self.plan is None:
            return []
        an = self.analysis()
        out = []
        for cid, ca in getattr(an, "clips", {}).items():
            for w in getattr(ca, "words", []):
                s, e = self.plan.source_to_output(cid, w.start), self.plan.source_to_output(cid, w.end)
                if s is not None and e is not None and e > s:
                    out.append((w.text, round(s, 3), round(e, 3)))
        return sorted(out, key=lambda x: x[1])


@dataclass
class Applied:
    skill: str
    name: str
    params: dict[str, Any]
    assumed: list[str]
    where: str
    notes: list[str]
    adjust: list[dict[str, Any]]
    span: tuple[float, float] | None = None  # output seconds it changed (None: the whole video) — for the verifier

    def to_dict(self) -> dict[str, Any]:
        return {"skill": self.skill, "name": self.name, "params": self.params, "assumed": self.assumed,
                "where": self.where, "notes": self.notes, "adjust": self.adjust, "undo": True,
                "span": list(self.span) if self.span else None}


def fill_params(s: dict[str, Any], given: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Validate the given params and fill defaults; returns (params, assumed) — `assumed` is said back."""
    out: dict[str, Any] = {}
    assumed: list[str] = []
    unknown = set(given) - set(s["params"])
    if unknown:
        raise ToolError(f"{s['id']} has no setting {', '.join(sorted(unknown))}")
    for k, p in s["params"].items():
        if k in given and given[k] is not None:
            v = given[k]
            t = p["type"]
            try:
                if t == "number":
                    v = float(v)
                elif t == "integer":
                    v = int(v)
                elif t == "bool":
                    v = bool(v)
                elif t in ("string", "text", "color"):
                    v = str(v)
            except (TypeError, ValueError) as exc:
                raise ToolError(f"{s['id']}: {k} must be a {t}") from exc
            if t in ("number", "integer") and ("min" in p and v < p["min"] or "max" in p and v > p["max"]):
                raise ToolError(f"{s['id']}: {k} must be between {p.get('min')} and {p.get('max')} (got {v:g})")
            if t == "choice" and v not in p["choices"]:
                raise ToolError(f"{s['id']}: {k} must be one of {', '.join(map(str, p['choices']))}")
            out[k] = v
        elif p.get("required"):
            raise ToolError(f"{s['name']}: please say the {p.get('desc', k)}")
        elif "default" in p:
            out[k] = p["default"]
            if p["default"] is not None:
                unit = p.get("unit", "")
                assumed.append(f"{k} = {p['default']}{unit} (default)")
    return out, assumed


def adjust_options(s: dict[str, Any], params: dict[str, Any], time: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Quick follow-ups shown under the explain card: more / less, another style, a different time."""
    opts: list[dict[str, Any]] = []
    for k, p in s["params"].items():
        v = params.get(k)
        if p["type"] in ("number", "integer") and isinstance(v, int | float) and "min" in p and "max" in p and v:
            for label, f in (("zyada", 1.5), ("kam", 0.6)):
                nv = min(p["max"], max(p["min"], v * f))
                nv = int(round(nv)) if p["type"] == "integer" else round(nv, 3)
                if nv != v:
                    opts.append({"label": f"{k} {label}", "call": {"id": s["id"], "params": {**params, k: nv},
                                                                  "time": time}})
        elif p["type"] == "choice":
            for c in [c for c in p["choices"] if c != v][:2]:
                opts.append({"label": f"{k}: {c}", "call": {"id": s["id"], "params": {**params, k: c}, "time": time}})
        if len(opts) >= 4:
            break
    return opts[:4]


def _span(when: Any) -> tuple[float, float] | None:
    if getattr(when, "whole", False):
        return None
    if getattr(when, "windows", None):
        a, b = when.windows[0]
        return (round(float(a), 3), round(float(b), 3))
    if getattr(when, "instants", None):
        t = float(when.instants[0])
        return (round(t, 3), round(t + 0.5, 3))
    return None


def run(plan: EditPlan, calls: list[dict[str, Any]], ctx: ToolCtx) -> tuple[EditPlan, list[Applied]]:
    """Apply the calls in order (atomically). Raises ToolError with a user-facing reason."""
    _load_builders()
    specs = spec.load()
    applied: list[Applied] = []
    cur = plan
    for call in calls:
        sid = call.get("id")
        s = specs.get(sid or "")
        if s is None:
            raise ToolError(f"unknown skill '{sid}'")
        fn_name = s["builder"].split(".", 1)[1]
        fn = _BUILDERS.get(fn_name)
        if fn is None:
            raise ToolError(f"{s['name']} is not built yet")
        params, assumed = fill_params(s, call.get("params") or {})
        ctx.plan = cur
        beats = ctx.beats
        if beats is None and cur.audio.music:  # the music's own beats (output seconds)
            from .b_audio import song_beats

            beats = (lambda plan=cur: song_beats(plan, ctx))
        when = resolve(call.get("time"), s["time_modes"], cur, beats, ctx.words)
        ctx.notes = []
        before = cur
        try:
            new = fn(cur, params, when, ctx)
        except ValueError as exc:  # pydantic ValidationError is a ValueError
            if isinstance(exc, ToolError):
                raise
            raise ToolError(f"{s['name']}: that change makes an invalid edit ({str(exc).splitlines()[-1][:160]})") from exc
        invariants.check(before, new, s, ctx)
        from ..engines.stack import resolve as stack

        new, stack_notes = stack(new)
        cur = new
        applied.append(Applied(sid, s["name"], params, assumed + when.assumed, when.describe(),
                               ctx.notes + [n for n in stack_notes if not n.startswith("effects ordered")],
                               adjust_options(s, params, call.get("time")), _span(when)))
    return cur, applied


def first_plan(clip_ids: list[str], durations: dict[str, float], aspect: str = "16:9",
               resolution: int = 720) -> EditPlan:
    """No edit yet: every clip in upload order, whole, hard cuts (what "merge_clips" means)."""
    clips = [{"source": c, "in": 0.0, "out": round(durations[c], 3), "order": i} for i, c in enumerate(clip_ids)]
    return EditPlan.model_validate({"canvas": {"aspect_ratio": aspect, "resolution": resolution}, "clips": clips})
