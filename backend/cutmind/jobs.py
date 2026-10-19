"""Background job execution with live per-agent progress and logs."""

from __future__ import annotations

import json
import shutil
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agents.analyzer import AnalyzerAgent
from .agents.base import AgentContext, ClipRef
from .agents.director import DirectorAgent, JobError
from .agents.effects import EffectsAgent, caption_items
from .config import Settings
from .db import Database, now_iso
from .ffmpeg_utils import decode_check, probe
from .intent import Intent, PromptError
from .learning import Learner
from .local_llm import LocalLLMClient
from .manual import ManualEdit, ManualError, apply_ops, describe
from .memory import Memory
from .music_library import music_dirs, resolve
from .plan import EditPlan, TextItem
from .proxy import PROXY_SHORT_SIDE, ensure_proxy, existing_proxy
from .renderer import extra_path, render

AGENT_ORDER = ["director", "analyzer", "audio", "cutter", "color", "effects", "reviewer"]
MAX_LOGS = 400
MAX_EVENTS = 1500


class JobState:
    """Mutable, thread-safe view of a running job (what GET /jobs/{id} returns)."""

    def __init__(self, job_id: str, project_id: str, prompt: str, db: Database) -> None:
        self.lock = threading.Lock()
        self.db = db
        self.data: dict[str, Any] = {
            "id": job_id, "project_id": project_id, "prompt": prompt, "status": "queued", "progress": 0.0,
            "stage": "queued", "error": None, "match_percent": None, "queue_position": 0,
            "created_at": now_iso(), "started_at": None, "finished_at": None,
            "agents": [{"name": n, "status": "pending", "progress": 0.0, "score": None, "attempts": 0, "message": ""}
                       for n in AGENT_ORDER],
            "logs": [], "review": None, "output": None, "history": [], "modes": {}, "variations": [],
            "events": [], "timeline": {}, "thoughts": [],
        }
        self._last_persist = 0.0
        self._seq = 0
        self._t0 = time.monotonic()

    # Live events (streamed to the app over SSE) ----------------------------------------------------------
    def event(self, kind: str, **data: Any) -> None:
        """Record a real step. Every line in the app's live activity panel comes from one of these."""
        with self.lock:
            self._seq += 1
            t = round(time.monotonic() - self._t0, 2)
            self.data["events"].append({"seq": self._seq, "t": t, "type": kind, **data})
            # the live editing view also works from polling: the latest state of every track + the thoughts
            if kind == "timeline":
                self.data.setdefault("timeline", {})[data.get("track", "video")] = data.get("items", [])
            elif kind == "render_step":
                self.data["render_step"] = {k: data.get(k) for k in ("step", "done", "total", "text")}
            elif kind == "thought":
                th = self.data.setdefault("thoughts", [])
                th.append({"t": t, "agent": data.get("agent"), "text": data.get("text")})
                del th[:-200]
            if len(self.data["events"]) > MAX_EVENTS:
                self.data["events"] = self.data["events"][-MAX_EVENTS:]

    def events_after(self, seq: int) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(e) for e in self.data["events"] if e["seq"] > seq]

    # Tracker protocol -----------------------------------------------------------------------------
    def stage(self, name: str, progress: float) -> None:
        with self.lock:
            changed = self.data["stage"] != name
            self.data["stage"] = name
            self.data["progress"] = round(max(self.data["progress"], progress * 100), 1)
            pct = self.data["progress"]
        if changed:
            self.event("progress", stage=name, progress=pct)
        self.persist()

    def agent(self, name: str, status: str, progress: float = 0.0, message: str = "",
              score: float | None = None, attempts: int | None = None) -> None:
        with self.lock:
            before = next((a["status"] for a in self.data["agents"] if a["name"] == name), None)
        if status != before:
            kind = {"running": "agent_started", "retrying": "agent_started", "done": "agent_completed",
                    "failed": "agent_failed"}.get(status, "agent_status")
            self.event(kind, agent=name, status=status, message=message, score=score)
        elif score is not None:
            self.event("agent_scored", agent=name, score=score)
        with self.lock:
            for a in self.data["agents"]:
                if a["name"] == name:
                    a["status"] = status
                    a["progress"] = round(progress * 100, 1)
                    if message:
                        a["message"] = message
                    if score is not None:
                        a["score"] = score
                    if attempts is not None:
                        a["attempts"] = attempts
                    elif status in ("running", "retrying") and a["attempts"] == 0:
                        a["attempts"] = 1
        self.persist()

    def log(self, agent: str, level: str, msg: str) -> None:
        with self.lock:
            self.data["logs"].append({"t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                      "agent": agent, "level": level, "msg": msg})
            if len(self.data["logs"]) > MAX_LOGS:
                self.data["logs"] = self.data["logs"][-MAX_LOGS:]
        self.event("log", agent=agent, level=level, msg=msg[:400])

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.data, default=str))

    def persist(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_persist < 1.0:
            return
        self._last_persist = now
        snap = self.snapshot()
        self.db.update_job(snap["id"], status=snap["status"], state=snap, error=snap["error"],
                           match_percent=snap["match_percent"], finished_at=snap["finished_at"])


class JobManager:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cutmind-job")
        # clip preparation (proxy + analysis) runs right after upload, beside the edit queue
        self.prep_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cutmind-prep")
        self.states: dict[str, JobState] = {}
        self.memory = Memory(db)

    def _previous_job(self, project_id: str) -> str | None:
        row = self.db.last_job(project_id, "done")
        return row["id"] if row else None

    def submit(self, project_id: str, prompt: str, options: dict[str, Any]) -> str:
        learner = Learner(self.db)
        if options.get("manual"):
            ops = ManualEdit.model_validate({"ops": options["manual"]}).ops
            learner.from_manual(self._previous_job(project_id), ops)
        else:  # the next words on a project say how the last edit landed ("thoda slow kar", "perfect")
            learner.from_prompt(self._previous_job(project_id), prompt)
        job_id = self.db.create_job(project_id, prompt, options)
        state = JobState(job_id, project_id, prompt, self.db)
        self.states[job_id] = state
        state.persist(force=True)
        self.pool.submit(self._run, job_id, project_id, prompt, options)
        return job_id

    def restart(self, job_id: str, project_id: str, prompt: str, options: dict[str, Any]) -> None:
        """After a server restart: continue an interrupted job from its last checkpoint (or rerun a queued one)."""
        from .workflow import has_checkpoint

        resume = has_checkpoint(self.settings.data_dir / "checkpoints.sqlite", job_id)
        state = JobState(job_id, project_id, prompt, self.db)
        self.states[job_id] = state
        state.log("director", "info", "Server restarted: " + ("resuming from the last finished step" if resume
                                                                else "starting the queued edit again"))
        state.event("job_resumed" if resume else "job_requeued")
        state.persist(force=True)
        self.pool.submit(self._run, job_id, project_id, prompt, options, resume)

    def get(self, job_id: str) -> dict[str, Any] | None:
        if job_id in self.states:
            snap = self.states[job_id].snapshot()
            if snap["status"] == "queued":
                # one worker: every unfinished job created before this one runs first
                snap["queue_position"] = sum(
                    1 for jid, st in self.states.items()
                    if jid != job_id and st.data["status"] in ("queued", "running") and st.data["created_at"] <= snap["created_at"]
                    and list(self.states).index(jid) < list(self.states).index(job_id)
                )
                snap["stage"] = (f"waiting — {snap['queue_position']} edit(s) ahead" if snap["queue_position"]
                                 else "starting")
            return snap
        row = self.db.get_job(job_id)
        if not row:
            return None
        if row.get("state"):
            return json.loads(row["state"])
        return {"id": row["id"], "project_id": row["project_id"], "prompt": row["prompt"], "status": row["status"],
                "progress": 0, "stage": row["status"], "error": row["error"], "match_percent": row["match_percent"],
                "created_at": row["created_at"], "finished_at": row["finished_at"], "agents": [], "logs": [],
                "review": None, "output": None}

    def project_dir(self, project_id: str) -> Path:
        return self.settings.projects_dir / project_id

    def prepare(self, project_id: str, clip_id: str) -> None:
        """Queue proxy creation + analysis for a freshly uploaded clip (so the first edit doesn't wait)."""
        self.prep_pool.submit(self._prepare, project_id, clip_id)

    def _prepare(self, project_id: str, clip_id: str) -> None:
        row = self.db.get_clip(clip_id)
        if not row:
            return
        work = self.project_dir(project_id) / "work" / f"prep_{clip_id}"
        try:
            source = Path(row["path"])
            clip = ClipRef(row["id"], source, row["filename"], row["position"], ensure_proxy(source))
            ctx = AgentContext(job_id=f"prep_{clip_id}", prompt="prepare", clips=[clip], settings=self.settings,
                               work_dir=work)
            AnalyzerAgent().rules(ctx, None)
        except Exception:  # noqa: BLE001 — preparation is an optimisation; the job redoes whatever is missing
            traceback.print_exc()
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def clip_refs(self, project_id: str, log: Any = None) -> list[ClipRef]:
        refs = []
        for c in self.db.list_clips(project_id):
            source = Path(c["path"])
            proxy = existing_proxy(source)
            if proxy is None:
                proxy = ensure_proxy(source)  # no-op (None) for sources that are already light
                if proxy is not None and log:
                    log("analyzer", "info", f"{c['filename']}: made a light edit proxy (one time)")
            refs.append(ClipRef(c["id"], source, c["filename"], c["position"], proxy))
        return refs

    def _run(self, job_id: str, project_id: str, prompt: str, options: dict[str, Any], resume: bool = False) -> None:
        state = self.states[job_id]
        work = self.project_dir(project_id) / "work" / job_id
        with state.lock:
            state.data["status"] = "running"
            state.data["started_at"] = now_iso()
            state.data["stage"] = "starting"
        state.event("job_started", prompt=prompt)
        state.persist(force=True)
        if options.get("manual"):
            self._run_manual(state, job_id, project_id, options, work)
            return
        if options.get("tools"):
            self._run_tools(state, job_id, project_id, options, work)
            return
        try:
            state.stage("preparing clips", 0.01)
            clips = self.clip_refs(project_id, state.log)
            ctx = AgentContext(
                job_id=job_id, prompt=prompt, clips=clips, settings=self.settings, db=self.db,
                llm=self._llm(),
                log=state.log, work_dir=work, options=options, project_id=project_id, memory=self.memory,
            )
            output = self.project_dir(project_id) / "output" / f"{job_id}.mp4"
            result = DirectorAgent().run_job(ctx, output, state, resume=resume)
            info = probe(output)
            explained = self._explain(project_id, result.plan, result.intent.model_dump(exclude_defaults=True), prompt)
            self.db.update_job(job_id, plan=result.plan.to_json(), output_path=str(output))
            plan = result.plan
            if not ctx.options.get("follow_up"):
                self.memory.forget_manual(project_id)  # a new edit from scratch: old hand-made changes don't apply
            self.memory.remember_edit(project_id, job_id, prompt, result.intent.model_dump(exclude_defaults=True), {
                "style": plan.style, "aspect_ratio": plan.canvas.aspect_ratio, "color_preset": plan.color.preset,
                "duration": round(plan.total_duration(), 2), "effects": [e.type for e in plan.effects],
                "transition": plan.transitions[0].type if plan.transitions else None,
                "captions": any(t.kind == "caption" for t in plan.text)})
            with state.lock:
                state.data.update({
                    "status": "done", "progress": 100.0, "stage": "done",
                    "match_percent": result.review.match_percent, "review": result.review.to_dict(),
                    "history": result.history, "modes": result.modes, "finished_at": now_iso(),
                    "variations": result.variations, "explain": explained,
                    "output": {"duration": round(info.duration, 3), "width": info.width, "height": info.height,
                               "has_audio": info.has_audio, "size_bytes": info.size_bytes,
                               "extras": [x for x in ("gif", "mp3") if extra_path(output, x).exists()]},
                })
            state.event("job_done", match_percent=result.review.match_percent, duration=round(info.duration, 2))
        except (JobError, PromptError) as exc:
            self._fail(state, str(exc))
        except Exception as exc:  # noqa: BLE001 — unexpected: keep the message, log the trace
            state.log("director", "error", traceback.format_exc()[-1500:])
            self._fail(state, f"Unexpected error: {exc}")
        finally:
            state.persist(force=True)
            if not self.settings.keep_work_dirs:
                shutil.rmtree(work, ignore_errors=True)

    def cached_analysis(self, project_id: str) -> Any:
        """The project's clip analysis if every clip is already analysed (never starts a slow analysis)."""
        try:
            clips = [c for c in self.clip_refs(project_id) if c.path.exists()]
            if not clips:
                return None
            ctx = AgentContext(job_id="peek", prompt="peek", clips=clips, settings=self.settings,
                               work_dir=self.project_dir(project_id) / "work" / "peek")
            an = AnalyzerAgent()
            if not all((an._cache_path(ctx, c) or Path("-")).exists() or (an._cache_path(ctx, c, False) or Path("-")).exists()
                       for c in clips):
                return None
            an.run(ctx)
            return ctx.analysis
        except Exception:  # noqa: BLE001 — a peek must never break /understand
            return None

    # ---- manual edits (no AI) -------------------------------------------------------------------------
    def _llm(self) -> Any:
        """The planner LLM: in-process (local) or none (rules only)."""
        return LocalLLMClient(settings=self.settings) if self.settings.planner_mode == "local" else None

    def _explain(self, project_id: str, plan: EditPlan, intent: dict[str, Any] | None,
                 prompt: str = "") -> dict[str, Any]:
        """What this edit changed compared with the current version (explain-back + the duration invariant)."""
        from .versions import explain

        try:
            before = self.base_plan(project_id)
        except ManualError:
            before = None
        except Exception:  # noqa: BLE001 — an old plan from an earlier schema: no comparison
            before = None
        return explain(before, plan, intent, prompt)

    def base_plan(self, project_id: str) -> EditPlan:
        row = self.db.last_job(project_id, "done")
        if not row or not row.get("plan"):
            raise ManualError("Make a first edit (or press Auto edit) — manual changes are applied on top of it.")
        return EditPlan.model_validate(json.loads(row["plan"]))

    def _song_exists(self, project_id: str) -> Any:
        dirs = music_dirs(self.settings, project_id)
        return lambda name: resolve(name, dirs) is not None

    def submit_manual(self, project_id: str, ops: list[Any]) -> str:
        """Validate now (clear 422 errors), then render in the queue like any job."""
        apply_ops(self.base_plan(project_id), ops, tracked_text=lambda item, _t: item,
                  song_exists=self._song_exists(project_id))  # dry run
        summary = "; ".join(describe(o) for o in ops)[:300]
        return self.submit(project_id, f"Manual: {summary}", {"manual": [o.model_dump() for o in ops]})

    # ---- Tier 1 tools: deterministic skill calls on the last version (cutmind/tools) --------------------------
    def tool_ctx(self, project_id: str, clips: list[ClipRef], log: Any = None) -> Any:
        from .tools.engine import ToolCtx

        pdir = self.project_dir(project_id)
        analysis_cache: dict[str, Any] = {}

        def analysis() -> Any:
            if "a" not in analysis_cache:
                ctx = AgentContext(job_id="tools", prompt="tools", clips=clips, settings=self.settings,
                                   work_dir=pdir / "work" / "tools_analysis", log=log or (lambda *a, **k: None))
                ctx.need_transcript = True
                AnalyzerAgent().run(ctx)
                analysis_cache["a"] = ctx.analysis
            return analysis_cache["a"]

        logo = next((pdir / n for n in ("logo.png", "logo.webp", "logo.jpg") if (pdir / n).exists()), None)
        sources = {c.id: c.path for c in clips}
        # clips made by earlier edits (a white screen, an intro card) are part of the current version: without them
        # the next edit failed with "unknown clip gen_card_…" (found by tests/integration/test_understanding_e2e.py)
        sources.update({p.stem: p for p in (pdir / "generated").glob("gen_*.mp4")})
        return ToolCtx(sources=sources, gen_dir=pdir / "generated",
                       clip_ids=[c.id for c in sorted(clips, key=lambda c: c.position)], analysis=analysis,
                       music_dirs=music_dirs(self.settings, project_id), logo=logo)

    def tool_base(self, project_id: str, clips: list[ClipRef]) -> EditPlan:
        """The last version's plan, or (no edit yet) every clip whole in upload order (merge_clips)."""
        from .tools.engine import first_plan

        row = self.db.last_job(project_id, "done")
        if row and row.get("plan"):
            return EditPlan.model_validate(json.loads(row["plan"]))
        if not clips:
            raise JobError("This project has no clips. Upload at least one video clip first.")
        ordered = sorted(clips, key=lambda c: c.position)
        infos = {c.id: probe(c.path) for c in ordered}
        # the first clip's shape decides the canvas (a phone talking-head stays vertical; it came out 16:9 before)
        first = infos[ordered[0].id]
        ratio = first.width / max(1, first.height)
        aspect = "9:16" if ratio < 0.8 else "1:1" if ratio < 1.2 else "16:9"
        return first_plan([c.id for c in ordered], {k: v.duration for k, v in infos.items()}, aspect, 720)

    def submit_tools(self, project_id: str, calls: list[dict[str, Any]], prompt: str = "") -> str:
        """Check the calls now (clear 422 errors before queuing), then render in the queue like any job."""
        from .tools import spec

        specs = spec.load()
        bad = [c.get("id") for c in calls if c.get("id") not in specs]
        if bad:
            raise ManualError(f"unknown skill(s): {', '.join(map(str, bad))}")
        summary = prompt or "Tools: " + ", ".join(c["id"] for c in calls)
        return self.submit(project_id, summary[:300], {"tools": calls})

    def _run_tools(self, state: JobState, job_id: str, project_id: str, options: dict[str, Any], work: Path) -> None:
        from .tools import engine
        from .tools.generated import resolve_sources
        from .tools.timeline import ToolError

        t0 = time.perf_counter()
        try:
            clips = self.clip_refs(project_id, state.log)
            prev = self.db.last_job(project_id, "done")  # the version this edit changes (its video is the "before")
            base = self.tool_base(project_id, clips)
            ctx = self.tool_ctx(project_id, clips, state.log)
            state.event("node_started", node="tools")
            state.agent("director", "running", 0.2, "applying the skills")
            plan, applied = engine.run(base, list(options["tools"]), ctx)
            for a in applied:
                state.log("director", "info", f"tool {a.skill}: {a.where}; {'; '.join(a.notes)[:300]}")
            state.event("node_completed", node="tools", ms=round((time.perf_counter() - t0) * 1000))
            sources = {**ctx.sources, **resolve_sources({c.source for c in plan.clips}, ctx.gen_dir)}
            output = self.project_dir(project_id) / "output" / f"{job_id}.mp4"
            t1 = time.perf_counter()
            state.event("node_started", node="render")
            render(plan, sources, work / "r0", output, music_dirs(self.settings, project_id),
                   lambda p, m: state.stage(m, 0.1 + 0.8 * p), cache_dir=self.project_dir(project_id) / "cache")
            state.event("node_completed", node="render", ms=round((time.perf_counter() - t1) * 1000))
            # quality gate (the invariants of a finished file): decodes, has sound, sound as long as the picture
            info = probe(output)
            ok, err = decode_check(output, timeout=300)
            if not ok or abs(info.duration - plan.total_duration()) > 0.5 or not info.has_audio:
                raise JobError(f"the render failed the quality gate ({err or 'duration / audio mismatch'})")
            # the verifier: every skill MEASURED on the new video against the version before (same moment)
            from .verify import summary as verify_summary
            from .verify import verify

            prev_video = Path(prev["output_path"]) if prev and prev.get("output_path") else None
            checks = verify(base, prev_video, plan, output, [a.to_dict() for a in applied])
            lines, warns = verify_summary(checks)
            for c in checks:
                state.log("reviewer", "warn" if c.status == "failed" else "info",
                          f"verify {c.skill}: {c.status} — {c.detail}")
            # the plan diff in plain words (like a director edit's answer), then the measured checks
            from .versions import diff as plan_diff

            d = plan_diff(base, plan)
            with state.lock:
                state.data["explain"] = {"tools": [a.to_dict() for a in applied],
                                         # one string (the app shows it as text; a list ran together before)
                                         # the same shape as a director edit's answer ("Changed: …. Length …")
                                         "summary": (f"Changed: {'; '.join(d['changed']) or 'nothing visible'}. "
                                                     f"Length {d['duration_after']:.1f}s. ("
                                                     + "; ".join(f"{a.name}: {a.where}" for a in applied) + ")"),
                                         "changed": d["changed"] + lines, "kept": d["kept"], "warnings": warns,
                                         "suggestions": [], "duration_before": d["duration_before"],
                                         "duration_after": d["duration_after"],
                                         "verify": [c.to_dict() for c in checks]}
            self.db.update_job(job_id, plan=plan.to_json(), output_path=str(output))
            self._remember_tools(project_id, job_id, state.data.get("prompt", ""), list(options["tools"]))
            with state.lock:
                state.data.update({
                    "status": "done", "progress": 100.0, "stage": "done", "finished_at": now_iso(),
                    "review": None, "match_percent": None, "variations": [],
                    "output": {"duration": round(info.duration, 3), "width": info.width, "height": info.height,
                               "has_audio": info.has_audio, "size_bytes": info.size_bytes, "extras": []},
                })
            state.event("job_done", duration=round(info.duration, 2), seconds=round(time.perf_counter() - t0, 1))
        except (ToolError, ManualError, JobError) as exc:
            self._fail(state, str(exc))  # the previous version stays as it was (rollback = nothing written)
        except Exception as exc:  # noqa: BLE001
            state.log("director", "error", traceback.format_exc()[-1500:])
            self._fail(state, f"Unexpected error: {exc}")
        finally:
            state.persist(force=True)
            if not self.settings.keep_work_dirs:
                shutil.rmtree(work, ignore_errors=True)

    # what a "normal karo" takes out of the remembered edit, per family (restore_normal's `what`)
    RESTORE_RESETS = {
        "color": {"color_preset": None, "brightness": 0.0, "gamma": 1.0, "style": None},
        "motion": {"effects": [], "timed_effects": []},
        "style": {"effects": [], "timed_effects": []},
        "overlays": {"moment_stickers": [], "style": None},
    }

    def _remember_tools(self, project_id: str, job_id: str, prompt: str, calls: list[dict[str, Any]]) -> None:
        """A skill edit is part of the current edit: a later DIRECTOR message re-plans from memory, so the skill calls
        are replayed on its new plan (like hand-made changes) — before, they were lost and the stale remembered intent
        came back (a comment after "sab effect hata do" re-added the old look). A restore instead clears what it took
        off from the remembered intent and drops the earlier skill changes."""
        restore = [c for c in calls if c.get("id") == "restore_normal"]
        if restore:
            what = str((restore[0].get("params") or {}).get("what") or "all")
            if what == "all":
                self.memory.forget_manual(project_id)
            else:
                self.memory.forget_tool_calls(project_id)
            rows = self.memory.history(project_id, 1)
            if rows:
                intent = dict(rows[0]["intent"])
                resets = {k: v for fam, r in self.RESTORE_RESETS.items() if what in ("all", fam) for k, v in r.items()}
                intent.update(resets)
                delivered = {**(rows[0].get("delivered") or {}), **({"style": None} if "style" in resets else {})}
                self.memory.remember_edit(project_id, job_id, prompt, intent, delivered)
            return
        self.memory.remember_manual(project_id, job_id, [{"op": "tool_call", "call": c} for c in calls])

    def _run_manual(self, state: JobState, job_id: str, project_id: str, options: dict[str, Any], work: Path) -> None:
        t0 = time.perf_counter()
        try:
            ops = ManualEdit.model_validate({"ops": options["manual"]}).ops
            base = self.base_plan(project_id)
            clips = self.clip_refs(project_id, state.log)
            state.event("node_started", node="apply")
            state.agent("director", "running", 0.2, "applying your changes")

            def tracked(item: TextItem, target: str) -> TextItem:
                ctx = AgentContext(job_id=job_id, prompt="manual", clips=clips, settings=self.settings, work_dir=work,
                                   log=state.log)
                AnalyzerAgent().run(ctx)  # per-clip cache: instant
                ctx.intent = Intent(tracked_text=item.text, track_target=target)  # type: ignore[arg-type]
                agent = EffectsAgent()
                timeline = base.timeline()
                _effs, seg_points = agent._subjects(ctx, list(base.effects), timeline)
                lab = agent._tracked_text(ctx, item.text, timeline, seg_points, list(base.effects), base.canvas,
                                          base.canvas.reframe, base.total_duration())
                return item.model_copy(update={"track": lab.track if lab else []})

            def retime(p: EditPlan) -> list[TextItem]:
                ctx = AgentContext(job_id=job_id, prompt="manual", clips=clips, settings=self.settings, work_dir=work)
                AnalyzerAgent().run(ctx)
                words = {cid: ca.words for cid, ca in ctx.analysis.clips.items()} if ctx.analysis else {}
                first = next((t for t in base.text if t.kind == "caption"), None)
                pos = first.style.position if first else "bottom"
                size = first.style.size if first else 50
                return caption_items(p.timeline(), words, pos, size)

            plan, notes = apply_ops(base, ops, tracked, retime, song_exists=self._song_exists(project_id))
            for n in notes:
                state.log("director", "info", f"manual: {n}")
            state.event("node_completed", node="apply", ms=round((time.perf_counter() - t0) * 1000))
            state.agent("director", "done", 1.0, "changes applied")
            output = self.project_dir(project_id) / "output" / f"{job_id}.mp4"
            sources = ({c.id: c.media for c in clips} if plan.canvas.resolution <= PROXY_SHORT_SIDE and not plan.export.is_master
                       else {c.id: c.path for c in clips})
            t1 = time.perf_counter()
            state.event("node_started", node="render")
            render(plan, sources, work / "r0", output, music_dirs(self.settings, project_id),
                   lambda p, m: state.stage(m, 0.1 + 0.8 * p), cache_dir=self.project_dir(project_id) / "cache")
            state.event("node_completed", node="render", ms=round((time.perf_counter() - t1) * 1000))
            # quality gate: the file must decode and match the plan
            state.event("node_started", node="review")
            info = probe(output)
            ok, err = decode_check(output, timeout=300)
            if not ok or abs(info.duration - plan.total_duration()) > 0.5:
                raise JobError(f"the render failed the quality gate ({err or 'duration mismatch'})")
            state.event("node_completed", node="review", ms=0)
            with state.lock:
                state.data["explain"] = self._explain(project_id, plan, None)
            self.db.update_job(job_id, plan=plan.to_json(), output_path=str(output))
            self.memory.remember_manual(project_id, job_id, list(options["manual"]))
            with state.lock:
                state.data.update({
                    "status": "done", "progress": 100.0, "stage": "done", "finished_at": now_iso(),
                    "review": None, "match_percent": None, "variations": [],
                    "output": {"duration": round(info.duration, 3), "width": info.width, "height": info.height,
                               "has_audio": info.has_audio, "size_bytes": info.size_bytes, "extras": []},
                })
            state.event("job_done", duration=round(info.duration, 2), seconds=round(time.perf_counter() - t0, 1))
        except (ManualError, JobError) as exc:
            self._fail(state, str(exc))
        except Exception as exc:  # noqa: BLE001
            state.log("director", "error", traceback.format_exc()[-1500:])
            self._fail(state, f"Unexpected error: {exc}")
        finally:
            state.persist(force=True)
            if not self.settings.keep_work_dirs:
                shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def _fail(state: JobState, message: str) -> None:
        state.log("director", "error", message)
        state.event("job_failed", error=message)
        with state.lock:
            state.data.update({"status": "failed", "error": message, "stage": "failed", "finished_at": now_iso()})
            for a in state.data["agents"]:
                if a["status"] in ("running", "retrying"):
                    a["status"] = "failed"

    def choose(self, job_id: str, variant: int) -> dict[str, Any]:
        """User picked another styled version ("Use this"): it becomes a NEW current version with that version's
        plan and video (timeline, next edit and undo follow it), and the choice is remembered."""
        from .versions import use_variant

        snap = self.get(job_id)
        if not snap:
            raise KeyError(f"Job {job_id} does not exist.")
        if snap["status"] != "done":
            raise ValueError("Versions can only be chosen on a finished edit.")
        if not any(v["index"] == variant for v in snap.get("variations") or []):
            raise KeyError(f"Job {job_id} has no version {variant}.")
        row = self.db.get_job(job_id)
        assert row is not None and row["output_path"]
        var = next(v for v in snap["variations"] if v["index"] == variant)
        made = use_variant(self.db, self.project_dir(row["project_id"]), row["project_id"], job_id, variant,
                           var.get("style"), self.memory, f"Use this: {var.get('name') or var.get('style')}")
        if made is None:
            # an edit made before versions kept their plans: only the video can be swapped (old behaviour)
            _swap_in_variant(Path(row["output_path"]), variant)
        self.memory.remember_choice(job_id, var.get("style"))
        for v in snap["variations"]:
            v["chosen"] = v["index"] == variant
        if job_id in self.states:
            with self.states[job_id].lock:
                self.states[job_id].data["variations"] = snap["variations"]
            self.states[job_id].persist(force=True)
        else:
            self.db.update_job(job_id, state=snap)
        return {"chosen": variant, "job_id": made["job_id"] if made else None,
                "version": made["version"] if made else None}

    def wait(self, job_id: str, timeout: float = 900) -> dict[str, Any]:
        """Block until a job finishes (tests / CLI)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            snap = self.get(job_id)
            if snap and snap["status"] in ("done", "failed"):
                return snap
            time.sleep(0.5)
        raise TimeoutError(f"job {job_id} did not finish in {timeout}s")

    def shutdown(self) -> None:
        self.prep_pool.shutdown(wait=True, cancel_futures=True)
        self.pool.shutdown(wait=True, cancel_futures=True)


def _swap_in_variant(output: Path, variant: int) -> None:
    """Make version `variant` the project's main output (MP4 + any GIF/MP3)."""
    src = output.with_name(f"{output.stem}_v{variant}.mp4")
    shutil.copyfile(src, output)
    for kind in ("gif", "mp3"):
        if extra_path(src, kind).exists():
            shutil.copyfile(extra_path(src, kind), extra_path(output, kind))
