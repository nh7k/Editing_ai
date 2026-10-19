"""LangGraph orchestration of one edit job.

    understand ─► analyze ─┬─► audio ─► cutter ─┬─► effects ─► render ─► review ─┬─► finalize
                           └─► color ───────────┘                  ▲            │
                                                                   └── fix ◄────┘ (failing agents, max N rounds)

* `color` runs in parallel with `audio → cutter` (it only needs the analysis); `effects` waits for both.
* Every node is checkpointed (SQLite, thread id = job id), so a crashed job can resume from the last finished
  node (`resume()`); finished stages are not redone.
* The state holds only JSON-able data. Live objects (agent context, tracker, the Director's agents) live in
  `_RUNTIME` for the duration of the job.
* Each node emits `node_started` / `node_completed` events (with milliseconds) through the tracker, which the
  API streams to the app (Server-Sent Events) — every line of the live activity panel is a real step.
"""

from __future__ import annotations

import operator
import re
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from . import live
from .agent_registry import route
from .agents.base import AgentContext, Feedback
from .agents.reviewer import Review
from .editorial import apply_spec, compile_spec, needs_footage_words, wants_editorial
from .intent import Intent, parse_intent
from .music_library import music_dirs
from .plan import EditPlan
from .proxy import PROXY_SHORT_SIDE
from .renderer import extra_path, render

if TYPE_CHECKING:
    from .agents.director import DirectorAgent, JobResult, Tracker

PLAN_AGENTS = ("audio", "cutter", "color", "effects")


def _last(_a: Any, b: Any) -> Any:
    return b


def _merge(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any]:
    return {**(a or {}), **(b or {})}


class EditState(TypedDict, total=False):
    job_id: str
    stage: Annotated[str, _last]
    completed: Annotated[list[str], operator.add]
    intent: dict[str, Any]
    reference_intent: dict[str, Any]
    director_mode: str
    active_agents: list[str]
    sections: Annotated[dict[str, Any], _merge]
    plan: dict[str, Any]
    round: int
    retries: dict[str, int]
    history: list[dict[str, Any]]
    best: dict[str, Any] | None
    review: dict[str, Any]
    failing: list[str]
    output: str
    variations: list[dict[str, Any]]


@dataclass
class Runtime:
    director: DirectorAgent
    ctx: AgentContext
    tracker: Tracker
    output: Path
    attempts: dict[str, int] = field(default_factory=dict)
    modes: dict[str, str] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


_RUNTIME: dict[str, Runtime] = {}


def _rt(s: EditState) -> Runtime:
    return _RUNTIME[s["job_id"]]


def _event(rt: Runtime, kind: str, **data: Any) -> None:
    ev = getattr(rt.tracker, "event", None)
    if ev is not None:
        ev(kind, **data)


def _node(name: str):  # noqa: ANN202 — decorator
    """Wrap a node: emit started/completed/failed events with the real duration."""
    def deco(fn):  # noqa: ANN001, ANN202
        def run(s: EditState) -> dict[str, Any]:
            rt = _rt(s)
            t0 = time.perf_counter()
            _event(rt, "node_started", node=name)
            try:
                out = fn(s, rt) or {}
            except Exception as exc:
                _event(rt, "node_failed", node=name, error=str(exc)[:300], ms=round((time.perf_counter() - t0) * 1000))
                raise
            _event(rt, "node_completed", node=name, ms=round((time.perf_counter() - t0) * 1000))
            return {"stage": name, "completed": [name], **out}
        run.__name__ = name
        return run
    return deco


def _restore(s: EditState, rt: Runtime) -> None:
    """After a resume the live context is fresh: put back what earlier nodes produced."""
    ctx = rt.ctx
    if ctx.intent is None and s.get("intent"):
        ctx.intent = Intent.model_validate(s["intent"])
        ctx.reference_intent = Intent.model_validate(s.get("reference_intent") or s["intent"])
    if s.get("sections"):
        for k, v in s["sections"].items():
            ctx.sections.setdefault(k, v)
    if ctx.analysis is None and s.get("intent") is not None and "analyze" in (s.get("completed") or []):
        rt.director.analyzer.run(ctx)  # per-clip cache: instant


# ---- nodes -----------------------------------------------------------------------------------------------
@_node("understand")
def understand(s: EditState, rt: Runtime) -> dict[str, Any]:
    from .agents.director import _apply_options

    d, ctx, tracker = rt.director, rt.ctx, rt.tracker
    tracker.stage("understanding prompt", 0.02)
    tracker.agent("director", "running", 0.1, "reading the prompt")
    live.started(tracker, "director")
    intent, dmode = d.understand(ctx)
    intent = _apply_options(ctx, intent)
    rules_intent = parse_intent(ctx.prompt)
    if ctx.options.get("moment"):  # a timeline comment: only that moment changes (cutmind/moment.py)
        from .moment import moment_intent

        intent = rules_intent = moment_intent(ctx.options["moment"])
    if ctx.options.get("skill_calls"):  # structured skill calls (POST /projects/{id}/skills; cutmind/skill_apply.py)
        from .skill_apply import apply as apply_skills

        intent, _notes = apply_skills(ctx.options["skill_calls"], float(ctx.options.get("skill_total") or 600))
        rules_intent = intent
    intent, rules_intent = d._use_memory(ctx, intent, rules_intent)
    ctx.intent = intent
    ctx.reference_intent = rules_intent if not rules_intent.is_empty() else intent
    rt.modes["director"] = dmode
    if intent.is_empty():
        ctx.log("director", "warn", "No specific instruction recognised; making a default clean edit.")
    else:
        ctx.log("director", "info", f"Plan: {', '.join(intent.recognized)}")
        live._emit(tracker, "thought", agent="director", text="Understood: " + ", ".join(intent.recognized)[:280])
    routed = route(intent)
    # the editorial brain must know whether people talk (talking head vs montage), so it always gets the words
    ctx.need_transcript = any(sp.id == "transcriber" for sp in routed) or (
        ctx.settings.editorial and needs_footage_words(ctx.prompt, intent))
    ctx.log("director", "info", f"Router: {len(routed)} specialists selected: {', '.join(sp.name for sp in routed)}")
    _event(rt, "agents_selected", agents=[{"id": sp.id, "name": sp.name, "category": sp.category} for sp in routed])
    return {"intent": intent.model_dump(), "reference_intent": ctx.reference_intent.model_dump(), "director_mode": dmode,
            "active_agents": [sp.id for sp in routed]}


@_node("analyze")
def analyze(s: EditState, rt: Runtime) -> dict[str, Any]:
    from .agents.director import JobError, autopilot

    _restore(s, rt)
    ctx, tracker = rt.ctx, rt.tracker
    tracker.stage("analyzing clips", 0.05)
    tracker.agent("analyzer", "running", 0.1, "measuring clips")
    live.started(tracker, "analyzer")
    try:
        ctx.analysis = None
        rt.director.analyzer.run(ctx)
    except Exception as exc:  # noqa: BLE001
        tracker.agent("analyzer", "failed", 1.0, str(exc)[:200])
        raise JobError(f"Clip analysis failed: {exc}") from exc
    tracker.agent("analyzer", "done", 1.0, "analysis ready")
    live.analysis_done(ctx, tracker)
    out: dict[str, Any] = {}
    # a follow-up ("thoda slow karo") changes only what it says: the remembered edit already has its editorial choices
    if ctx.intent is not None and ctx.settings.editorial and wants_editorial(ctx.prompt, ctx.intent)             and not ctx.options.get("follow_up"):
        # the editorial brain: what kind of video is this, which skills apply, what to infer (with reasons)
        spec = compile_spec(ctx.prompt, ctx.intent, ctx.analysis)
        ctx.intent = apply_spec(ctx.intent, spec)
        ctx.reference_intent = apply_spec(ctx.reference_intent or ctx.intent, spec)
        ctx.spec = spec.to_dict()
        ctx.spec_decisions = [{"decision": f"{d.field} = {d.value}", "where": "whole edit", "reason": d.reason[:300],
                               "skill": d.skill} for d in spec.inferred]
        ctx.log("director", "info", "Edit spec: " + ", ".join(
            [f"type {'+'.join(g['id'] for g in spec.genres) or '?'}", f"platform {spec.platform['id'] if spec.platform else '?'}",
             f"{len(spec.skills)} skills", f"{len(spec.inferred)} inferred"]))
        _event(rt, "spec_compiled", spec=spec.to_dict())
        routed = route(ctx.intent)
        _event(rt, "agents_selected", agents=[{"id": sp.id, "name": sp.name, "category": sp.category} for sp in routed])
        out = {"intent": ctx.intent.model_dump(), "reference_intent": ctx.reference_intent.model_dump()}
    if ctx.intent is not None and ctx.options.get("copy_edit") and ctx.project_id:
        out = _apply_blueprint(ctx, rt) or out
    elif ctx.intent is not None and ctx.intent.use_reference and ctx.project_id:
        out = _apply_reference(ctx, rt) or out
    live.brief(ctx, tracker)
    if ctx.intent is not None and ctx.intent.auto:
        ctx.intent = autopilot(ctx, ctx.intent)
        ctx.reference_intent = autopilot(ctx, ctx.reference_intent or ctx.intent)
        ctx.log("director", "info", f"Auto edit: {', '.join(ctx.intent.recognized)}")
        routed = route(ctx.intent)  # the autopilot added work: route again so the panel shows the real list
        _event(rt, "agents_selected", agents=[{"id": sp.id, "name": sp.name, "category": sp.category} for sp in routed])
        out = {"intent": ctx.intent.model_dump(), "reference_intent": ctx.reference_intent.model_dump()}
    return out


def _apply_reference(ctx: AgentContext, rt: Runtime) -> dict[str, Any] | None:
    """"Is video jaisa edit karo": the measured style of the uploaded reference becomes the plan (what the user
    said explicitly still wins); its soundtrack becomes the music."""
    from .reference import apply_reference, load_recipe

    recipe = load_recipe(ctx.settings.projects_dir / ctx.project_id / "reference" / "recipe.json")  # type: ignore[operator]
    if recipe is None:
        ctx.log("director", "warn", "no reference video uploaded for this project — upload one first")
        return None
    base, default = parse_intent(ctx.prompt), Intent()
    explicit = {k for k in Intent.model_fields if getattr(base, k) != getattr(default, k)}
    assert ctx.intent is not None
    ctx.intent, why = apply_reference(ctx.intent, recipe, explicit)
    ctx.reference_intent, _ = apply_reference(ctx.reference_intent or ctx.intent, recipe, explicit)
    if recipe.song and not ctx.intent.use_my_song and "music_track" not in ctx.options:
        ctx.options["music_track"] = recipe.song
        why.append({"decision": "music = the reference's soundtrack", "where": recipe.song,
                    "reason": "same song as the reference, so the cuts can fall on the same beats", "skill": "reference_style"})
    ctx.spec_decisions = [*ctx.spec_decisions, *why]
    ctx.log("director", "info", f"Reference style ({recipe.name}): " + "; ".join(recipe.summary()))
    _event(rt, "reference_applied", summary=recipe.summary())
    return {"intent": ctx.intent.model_dump(), "reference_intent": ctx.reference_intent.model_dump()}


# hand-made changes that still make sense on a NEW cut (a segment index from the old cut does not)
REPLAYABLE_OPS = {"add_effect", "remove_effect", "set_look", "set_style", "style_captions", "set_audio", "add_text",
                  "update_text", "remove_text", "remove_captions", "set_transition"}


def _replay_tool(ctx: AgentContext, plan: EditPlan, call: dict[str, Any]) -> EditPlan:
    from .music_library import music_dirs
    from .tools.engine import ToolCtx, run

    pdir = ctx.settings.projects_dir / str(ctx.project_id)
    sources = {c.id: c.path for c in ctx.clips}
    sources.update({p.stem: p for p in (pdir / "generated").glob("gen_*.mp4")})
    tctx = ToolCtx(sources=sources, gen_dir=pdir / "generated",
                   clip_ids=[c.id for c in sorted(ctx.clips, key=lambda c: c.position)],
                   music_dirs=music_dirs(ctx.settings, ctx.project_id))
    new, _applied = run(plan, [call], tctx)
    return new


def _with_manual(ctx: AgentContext, plan: EditPlan) -> EditPlan:
    """A chat change keeps what the user did by hand (an effect from the Effects panel, a text they typed): those ops
    are applied again on the agents' new plan. Ops that no longer fit are skipped and said so — never a crash."""
    if not ctx.options.get("follow_up") or ctx.memory is None or not ctx.project_id:
        return plan
    from .manual import ManualEdit, apply_ops

    kept, skipped = 0, []
    for raw in ctx.memory.manual_ops(ctx.project_id):
        kind = raw.get("op", "?")
        if kind == "tool_call":  # a skill edit made between director edits ("captions laga do" by the skills)
            try:
                plan = _replay_tool(ctx, plan, raw["call"])
                kept += 1
            except Exception:  # noqa: BLE001 — a skill change that no longer fits is said, never a crash
                skipped.append(str(raw.get("call", {}).get("id", "skill")))
            continue
        if kind not in REPLAYABLE_OPS:
            skipped.append(kind)
            continue
        try:
            op = ManualEdit.model_validate({"ops": [raw]}).ops
            plan, _notes = apply_ops(plan, op)
            kept += 1
            if kind == "add_effect" and raw.get("type"):  # asked by hand: the Reviewer must not call it "unasked"
                ctx.options.setdefault("manual_effects", []).append(str(raw["type"]))
        except Exception:  # noqa: BLE001 — an old op that no longer fits must not break the edit
            skipped.append(kind)
    if kept:
        ctx.decide("your hand-made changes kept", f"{kept} change(s)", "made in the editor earlier; the new edit keeps "
                   "them", "manual")
    if skipped:
        ctx.decide("hand-made changes not kept", ", ".join(sorted(set(skipped))), "they were made on the old cut "
                   "(a shot that is no longer there) - do them again if you still want them", "manual")
    return plan


def _apply_blueprint(ctx: AgentContext, rt: Runtime) -> dict[str, Any] | None:
    """Copy an Edit: the liked video's shot list, effects, texts and soundtrack become this edit. Anything the user
    asked for in words still wins (e.g. "same edit, but no text")."""
    from .blueprint import load_blueprint

    bp = load_blueprint(ctx.settings.projects_dir / ctx.project_id / "copy_edit" / "blueprint.json")  # type: ignore[operator]
    if bp is None:
        ctx.log("director", "warn", "no liked video analysed for this project — upload one in Copy an Edit first")
        return None
    ctx.blueprint = bp
    base, default = parse_intent(ctx.prompt), Intent()
    # "same edit", "copy karo" read as "auto edit" — but here the liked video decides, never the autopilot
    explicit = {k for k in Intent.model_fields if getattr(base, k) != getattr(default, k)} - {"auto", "use_reference"}
    talking = bool(ctx.analysis is not None and ctx.analysis.any_speech)
    upd: dict[str, Any] = {"aspect_ratio": bp.aspect, "target_duration": round(min(bp.duration, 600.0), 2),
                           "transition": None, "fast_cuts": False, "beat_sync": False, "auto": False, "use_reference": False,
                           "hook_first": False, "ending_peak": False, "kinetic_text": False, "color_pass": False,
                           "flash_accents": 0, "speed_moves": False, "impact_hits": False, "cut_length": None,
                           # only the liked video's effects (+ what the user asked for in words)
                           "effects": list(base.effects), "captions": base.captions, "slow_motion": base.slow_motion,
                           "remove_silence": base.remove_silence, "remove_idle": False}
    if bp.color in ("warm", "cool", "vivid", "bw"):
        upd["color_preset"] = bp.color
    keep_sound = ctx.options.get("keep_sound", True)
    if bp.song and keep_sound and "music_track" not in ctx.options:
        ctx.options["music_track"] = bp.song
        upd["music"] = True
        upd["music_volume"] = 0.5 if talking else 0.95  # the soundtrack carries a montage; under speech it is lower
    why = []

    def fix(it: Intent) -> Intent:
        data = it.model_dump()
        for k, v in upd.items():
            if k not in explicit and k in data:
                data[k] = v
        data["inferred_fields"] = sorted({*it.inferred_fields, *(k for k in upd if k not in explicit)})
        return Intent.model_validate(data)

    assert ctx.intent is not None
    ctx.intent = fix(ctx.intent)
    ctx.reference_intent = fix(ctx.reference_intent or ctx.intent)
    why.append({"decision": "copy the liked video", "where": bp.name,
                "reason": "; ".join(bp.summary())[:300], "skill": "copy_edit"})
    if bp.song and keep_sound:
        why.append({"decision": "music = its soundtrack", "where": bp.song,
                    "reason": "the same sound from the same point, so every cut lands on the same beat", "skill": "copy_edit"})
    ctx.spec_decisions = [*ctx.spec_decisions, *why]
    ctx.log("director", "info", f"Copy an Edit ({bp.name}): " + "; ".join(bp.summary()))
    _event(rt, "copy_edit_applied", summary=bp.summary())
    return {"intent": ctx.intent.model_dump(), "reference_intent": ctx.reference_intent.model_dump()}


def _plan_agent(name: str, progress: float):  # noqa: ANN202
    @_node(name)
    def node(s: EditState, rt: Runtime) -> dict[str, Any]:
        from .agents.director import JobError

        _restore(s, rt)
        rt.tracker.stage(f"{name} agent", progress)
        try:
            rt.director.run_agent(rt.ctx, name, rt.tracker, rt.attempts, rt.modes)
        except ValueError as exc:
            rt.tracker.agent(name, "failed", 1.0, str(exc)[:200])
            raise JobError(f"{name} agent failed: {exc}") from exc
        sec = {name: rt.ctx.sections[name]}
        if name == "cutter":
            sec["clips"] = rt.ctx.sections["clips"]
        return {"sections": sec}
    return node


@_node("effects")
def effects(s: EditState, rt: Runtime) -> dict[str, Any]:
    from .agents.director import JobError

    _restore(s, rt)
    d, ctx, tracker = rt.director, rt.ctx, rt.tracker
    tracker.stage("effects agent", 0.45)
    try:
        d.run_agent(ctx, "effects", tracker, rt.attempts, rt.modes)
    except ValueError as exc:
        tracker.agent("effects", "failed", 1.0, str(exc)[:200])
        raise JobError(f"effects agent failed: {exc}") from exc
    plan = _with_manual(ctx, d._styled(ctx, d.merge(ctx.sections, ctx.spec_decisions + ctx.decisions)))
    intent = ctx.intent
    assert intent is not None
    # conflict resolution: speed ramps / transitions can push the length off target → re-cut once
    if intent.target_duration:
        avail = ctx.sections["cutter"].get("available_duration", 0)
        expected = min(intent.target_duration, avail)
        if abs(plan.total_duration() - expected) > max(0.5, 0.05 * expected):
            ctx.log("director", "info", f"resolving length conflict: {plan.total_duration():.2f}s vs {expected:.2f}s")
            fb = [Feedback("duration", "length drifted after effects", {"expected": expected, "actual": plan.total_duration()})]
            d.run_agent(ctx, "cutter", tracker, rt.attempts, rt.modes, fb)
            d.run_agent(ctx, "effects", tracker, rt.attempts, rt.modes)
            plan = _with_manual(ctx, d._styled(ctx, d.merge(ctx.sections, ctx.spec_decisions + ctx.decisions)))
    tracker.agent("director", "running", 0.5, "plan merged")
    return {"plan": plan.to_json(), "sections": dict(ctx.sections), "round": 0,
            "retries": dict.fromkeys(("cutter", "audio", "color", "effects"), 0), "history": [], "best": None}


@_node("render")
def render_node(s: EditState, rt: Runtime) -> dict[str, Any]:
    from .agents.director import JobError

    _restore(s, rt)
    ctx, tracker = rt.ctx, rt.tracker
    assert ctx.work_dir is not None
    r = s.get("round", 0)
    plan = EditPlan.model_validate(s["plan"])
    out_try = ctx.work_dir / f"render_{r}.mp4"
    tracker.stage("rendering" if r == 0 else f"re-rendering (retry {r})", 0.55 + 0.1 * r)
    live.started(tracker, "render")

    def _progress(p: float, msg: str) -> None:
        tracker.stage(msg if r == 0 else f"retry {r}: {msg}", min(0.85, 0.55 + 0.1 * r + 0.25 * p))
        # the live timeline marks each shot as it is rendered, then the final pass (text, music, encode)
        m = re.match(r"rendering segment (\d+)/(\d+)", msg)
        step = ("segment" if m else "join" if msg.startswith("joining") else "finish" if msg.startswith("adding")
                else "reuse" if msg.startswith("reusing") else "done" if msg.startswith("render complete") else "start")
        _event(rt, "render_step", step=step, done=int(m.group(1)) if m else None, total=int(m.group(2)) if m else None,
               text=msg, round=r)

    # ≤720p output: decode the light proxies (much faster); 1080p: the originals, for full quality
    sources = ({c.id: c.media for c in ctx.clips} if plan.canvas.resolution <= PROXY_SHORT_SIDE and not plan.export.is_master
               else {c.id: c.path for c in ctx.clips})
    try:
        render(plan, sources, ctx.work_dir / f"r{r}", out_try, music_dirs(ctx.settings, ctx.project_id), _progress,
               cache_dir=ctx.work_dir.parent.parent / "cache")
    except Exception as exc:  # noqa: BLE001
        raise JobError(f"Rendering failed: {exc}") from exc
    _event(rt, "render_completed", round=r, path=out_try.name)
    return {"output": str(out_try)}


@_node("review")
def review_node(s: EditState, rt: Runtime) -> dict[str, Any]:
    from .agents.director import RETRYABLE

    _restore(s, rt)
    d, ctx, tracker = rt.director, rt.ctx, rt.tracker
    st = ctx.settings
    r = s.get("round", 0)
    plan = EditPlan.model_validate(s["plan"])
    out_try = Path(s["output"])
    tracker.stage("reviewing", 0.88)
    tracker.agent("reviewer", "running", 0.5, "checking the render")
    sources = {c.id: c.path for c in ctx.clips}
    positions = {c.id: c.position for c in ctx.clips}
    dmode = s.get("director_mode", "rules")
    review = d.reviewer.review(plan, out_try, ctx.reference_intent, ctx.analysis, sources, positions,
                               ctx.sections["cutter"].get("available_duration"), ctx.options,
                               ctx.intent_disagreements if dmode == "llm" else None)
    scores = review.agent_scores
    tracker.agent("reviewer", "done", 1.0, f"match {review.match_percent}%")
    live.reviewed(tracker, review)
    for agent, score in scores.items():
        if agent in d.team or agent in ("director", "analyzer"):
            tracker.agent(agent, "done", 1.0, score=score, attempts=rt.attempts.get(agent, 1))
    ctx.log("reviewer", "info", f"round {r}: match {review.match_percent}% scores={scores}")
    for c in review.checks:
        ctx.log("reviewer", "info" if c.passed else "warn", f"{'PASS' if c.passed else 'FAIL'} {c.name} [{c.owner}]: {c.detail}")
    d.record(ctx, review, r + 1)
    _event(rt, "review_completed", round=r, match_percent=review.match_percent, agent_scores=scores,
           failed=[c.name for c in review.checks if not c.passed])
    history = [*s.get("history", []), {"round": r, **review.to_dict(), "duration": plan.total_duration()}]
    best = s.get("best")
    if best is None or review.match_percent > best["match_percent"]:
        best = {"match_percent": review.match_percent, "plan": s["plan"], "review": review.to_dict(), "output": str(out_try)}
    retries = dict(s.get("retries") or {})
    failing = [a for a in RETRYABLE if scores.get(a, 100) < st.score_threshold and retries.get(a, 0) < st.max_agent_retries
               and review.fixable_failures(a)]
    skipped = [a for a in RETRYABLE if scores.get(a, 100) < st.score_threshold and not review.fixable_failures(a)]
    if skipped:
        ctx.log("director", "info", f"not retrying {skipped}: what failed can't be fixed by re-editing (see the review)")
    prev = s.get("history") or []
    if failing and prev:
        before = {c["name"] for c in prev[-1]["checks"] if not c["passed"]}
        now = {c.name for c in review.checks if not c.passed}
        if now == before and review.match_percent <= prev[-1]["match_percent"]:
            ctx.log("director", "warn", f"the retry fixed nothing ({sorted(now)} still fail): stopping instead of "
                                        "rendering again; lessons were recorded")
            failing = []
    if r >= st.max_agent_retries:
        failing = []
    return {"review": review.to_dict(), "history": history, "best": best, "failing": failing}


@_node("fix")
def fix(s: EditState, rt: Runtime) -> dict[str, Any]:
    from .agents.director import DEPENDENTS, JobError

    _restore(s, rt)
    d, ctx = rt.director, rt.ctx
    review = Review.from_dict(s["review"])
    scores = review.agent_scores
    failing = s.get("failing") or []
    retries = dict(s.get("retries") or {})
    to_run: list[str] = []
    for a in failing:
        to_run.append(a)
        to_run += [x for x in DEPENDENTS.get(a, []) if x not in failing]
    for name in [n for n in PLAN_AGENTS if n in to_run]:
        fb = [Feedback(c.name, c.detail, c.data) for c in review.failed_for(name)] if name in failing else None
        if name in failing:
            retries[name] = retries.get(name, 0) + 1
            ctx.log("director", "info", f"score {scores[name]} < {ctx.settings.score_threshold}: re-running {name} with reviewer feedback")
        try:
            d.run_agent(ctx, name, rt.tracker, rt.attempts, rt.modes, fb)
        except ValueError as exc:
            ctx.log(name, "error", f"retry failed: {exc}")
    try:
        plan = _with_manual(ctx, d._styled(ctx, d.merge(ctx.sections, ctx.spec_decisions + ctx.decisions)))
    except JobError as exc:
        ctx.log("director", "error", f"retry produced an invalid plan ({exc}); keeping the best result")
        return {"failing": [], "retries": retries, "round": s.get("round", 0)}
    return {"plan": plan.to_json(), "sections": dict(ctx.sections), "retries": retries, "round": s.get("round", 0) + 1}


def _after_review(s: EditState) -> str:
    return "fix" if s.get("failing") else "finalize"


def _after_fix(s: EditState) -> str:
    return "render" if s.get("failing") and s["plan"] else "finalize"


@_node("finalize")
def finalize(s: EditState, rt: Runtime) -> dict[str, Any]:
    _restore(s, rt)
    d, ctx, tracker = rt.director, rt.ctx, rt.tracker
    best = s["best"]
    assert best is not None and ctx.intent is not None
    plan = EditPlan.model_validate(best["plan"])
    review = Review.from_dict(best["review"])
    out_best = Path(best["output"])
    output = rt.output
    output.parent.mkdir(parents=True, exist_ok=True)
    variations: list[dict[str, Any]] = []
    if ctx.intent.variations > 1:
        sources = {c.id: c.path for c in ctx.clips}
        positions = {c.id: c.position for c in ctx.clips}
        variations, plan, review, out_best = d._variations(ctx, plan, ctx.intent, sources, positions, output, tracker,
                                                           s.get("director_mode", "rules"))
    shutil.copyfile(out_best, output)
    for kind in ("gif", "mp3"):  # extra deliverables live next to the chosen render
        if extra_path(out_best, kind).exists():
            shutil.copyfile(extra_path(out_best, kind), extra_path(output, kind))
    tracker.agent("director", "done", 1.0, f"final match {review.match_percent}%", score=review.agent_scores["director"])
    if ctx.db is not None:
        for agent, score in review.agent_scores.items():
            ctx.db.add_score(ctx.job_id, agent, 0, "_final_score", int(round(score)), "final score of the job")
    _event(rt, "final_ready", match_percent=review.match_percent)
    return {"best": {**best, "plan": plan.to_json(), "review": review.to_dict(), "output": str(out_best)},
            "variations": variations}


# ---- graph -------------------------------------------------------------------------------------------------
def build_graph() -> StateGraph:
    g = StateGraph(EditState)
    g.add_node("understand", understand)
    g.add_node("analyze", analyze)
    g.add_node("audio", _plan_agent("audio", 0.30))
    g.add_node("cutter", _plan_agent("cutter", 0.35))
    g.add_node("color", _plan_agent("color", 0.40))
    g.add_node("effects", effects)
    g.add_node("render", render_node)
    g.add_node("review", review_node)
    g.add_node("fix", fix)
    g.add_node("finalize", finalize)
    g.add_edge(START, "understand")
    g.add_edge("understand", "analyze")
    g.add_edge("analyze", "audio")      # music beats feed beat-synced cutting
    g.add_edge("audio", "cutter")
    g.add_edge("analyze", "color")      # independent of the cut: runs in parallel
    g.add_edge(["cutter", "color"], "effects")
    g.add_edge("effects", "render")
    g.add_edge("render", "review")
    g.add_conditional_edges("review", _after_review, {"fix": "fix", "finalize": "finalize"})
    g.add_conditional_edges("fix", _after_fix, {"render": "render", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g


_saver_lock = threading.Lock()
_savers: dict[str, SqliteSaver] = {}


def checkpointer(path: Path) -> SqliteSaver:
    with _saver_lock:
        key = str(path)
        if key not in _savers:
            path.parent.mkdir(parents=True, exist_ok=True)
            _savers[key] = SqliteSaver(sqlite3.connect(key, check_same_thread=False))
        return _savers[key]


def has_checkpoint(path: Path, job_id: str) -> bool:
    if not path.exists():
        return False
    return checkpointer(path).get_tuple({"configurable": {"thread_id": job_id}}) is not None


def run(director: DirectorAgent, ctx: AgentContext, output: Path, tracker: Tracker, resume: bool = False) -> JobResult:
    from .agents.director import JobResult

    rt = Runtime(director, ctx, tracker, output)
    _RUNTIME[ctx.job_id] = rt
    saver = checkpointer(ctx.settings.data_dir / "checkpoints.sqlite")
    graph = build_graph().compile(checkpointer=saver)
    config = {"configurable": {"thread_id": ctx.job_id}, "recursion_limit": 50}
    try:
        final = graph.invoke(None if resume else {"job_id": ctx.job_id, "completed": []}, config)
    finally:
        _RUNTIME.pop(ctx.job_id, None)
    saver.delete_thread(ctx.job_id)  # finished: checkpoints are only needed to resume an unfinished job
    best = final["best"]
    assert ctx.intent is not None
    return JobResult(EditPlan.model_validate(best["plan"]), Review.from_dict(best["review"]), output, ctx.intent,
                     rt.attempts, final.get("history", []), rt.modes, final.get("variations", []))


def graph_mermaid() -> str:
    """The workflow as a Mermaid diagram (shown in developer mode / docs)."""
    return build_graph().compile().get_graph().draw_mermaid()
