"""Director (CEO) agent: understands the prompt, runs the team, merges the plan, reviews, retries, learns."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from .. import live
from ..evidence import has_evidence
from ..ffmpeg_utils import probe
from ..intent import NO_MUSIC, Intent, parse_intent, validate_prompt
from ..llm import LLMError, chat_json
from ..memory import is_follow_up, merge_with_last, wants_my_style, wants_repeat
from ..music_library import music_dirs
from ..plan import Decision, EditPlan
from ..proxy import PROXY_SHORT_SIDE
from ..renderer import extra_path, render
from ..styles import DEFAULT_ORDER, STYLES, apply_style
from ..versions import variant_plan_path
from .analyzer import AnalyzerAgent
from .audio import AUDIO_DECISIONS, AudioAgent
from .base import AgentContext, BaseAgent, Feedback
from .color import ColorAgent
from .cutter import CutterAgent
from .effects import EffectsAgent
from .reviewer import Review, ReviewerAgent

RETRYABLE = ("cutter", "audio", "color", "effects")
DEPENDENTS = {"cutter": ["effects"]}  # effects' caption timing depends on the cut

LESSON_HINTS = {
    "timed_effects": "Put a 'first 3 seconds' effect only on the segments in that time window.",
    "bass_boost": "Bass requests need the low-end boost AND a zoom punch on the music beats.",
    "duration": "Hit the requested length; budget for transition overlaps and speed changes.",
    "silence_removed": "Remove every pause longer than ~0.8s when silence removal is requested.",
    "no_mid_word_cuts": "Snap every cut point to a gap between words.",
    "clip_order": "Respect the requested clip order.",
    "all_clips_used": "Use material from every clip unless the target length is too short.",
    "captions_present": "Captions must be visible on screen whenever there is speech.",
    "title_present": "Add the requested on-screen title.",
    "transitions_present": "Add the requested transition type between segments.",
    "aspect_ratio": "Output must use exactly the requested aspect ratio and size.",
    "resolution": "Output must use the requested resolution.",
    "audio_levels": "Keep loudness near the target LUFS and avoid clipping.",
    "music_present": "Add background music when the user asks for it.",
    "audio_stream": "The output must always contain an audio stream.",
    "color_applied": "Make the requested grade clearly visible (measurable vs the source).",
    "intent_understood": "Ask for or infer a concrete edit when the prompt is vague.",
    "llm_intent_correct": "Read every explicit instruction in the prompt (length, aspect, resolution, look, transitions).",
    "speech_detected": "Transcribe speech so captions can be made.",
    "file_plays": "The final file must decode without errors.",
    "no_unrequested_effects": "Do not add transitions, effects, titles or captions the user did not ask for.",
    "no_unrequested_music": "Do not add music unless the user asks for it.",
    "orientation": "Rotate / mirror exactly as asked.",
    "reverse_playback": "Every segment must play backwards when reverse playback is asked.",
    "frame_rate": "Export at the requested frame rate.",
    "muted": "Mute means no original sound in the output.",
    "audio_fade": "Fade the audio in and out when asked.",
    "watermark_present": "Add the requested watermark text.",
    "idle_removed": "Cut frozen / static stretches when asked.",
    "extras_exported": "Produce the requested GIF / MP3 files.",
    "no_unrequested_trim": "Never invent a target length: '9:16' and '1:1' are aspect ratios, not seconds.",
    "render_matches_plan": "The render must match the planned duration.",
}


_SCALAR_FIELDS = ("target_duration", "aspect_ratio", "resolution", "color_preset", "transition", "title", "music_mood",
                  "rotate", "flip", "fps", "gamma", "loudness", "watermark", "style", "text_animation", "variations")
_FLAG_FIELDS = ("captions", "remove_silence", "remove_fillers", "fast_cuts", "slow_motion", "music", "beat_sync",
                "voice_cleanup", "reverse_playback", "mute", "audio_fade", "remove_idle", "export_gif", "export_mp3", "auto", "bass_boost")


def reconcile(llm: Intent, rules: Intent, prompt: str = "") -> tuple[Intent, list[str]]:
    """Explicit keywords found by the deterministic parser win over the LLM (they are high precision), and
    anything the LLM adds on its own must be supported by some word in the prompt (evidence gate).

    Returns the merged intent and a list of what the LLM got wrong.
    """
    data = llm.model_dump()
    wrong: list[str] = []
    if prompt:
        defaults = Intent().model_dump()
        for f, lv in llm.model_dump().items():
            if f in ("recognized", "brightness") or lv == defaults[f] or getattr(rules, f) != defaults[f]:
                continue
            if not has_evidence(f, lv, prompt):
                wrong.append(f"{f}: LLM added {lv!r} without any hint in the prompt (removed)")
                data[f] = defaults[f]
        llm = Intent.model_validate(data)
    scalar_defaults = Intent().model_dump()
    for f in _SCALAR_FIELDS:
        rv, lv = getattr(rules, f), getattr(llm, f)
        if rv != scalar_defaults[f] and rv != lv:
            wrong.append(f"{f}: prompt says {rv!r}, LLM said {lv!r}")
            data[f] = rv
    for f in _FLAG_FIELDS:
        if getattr(rules, f) and not getattr(llm, f):
            wrong.append(f"{f}: requested but LLM missed it")
            data[f] = True
    if rules.brightness and rules.brightness != llm.brightness:
        data["brightness"] = rules.brightness
    if rules.order != "original" and rules.order != llm.order:
        wrong.append(f"order: prompt says {rules.order!r}, LLM said {llm.order!r}")
        data["order"] = rules.order
    if rules.timed_effects and rules.timed_effects != llm.timed_effects:
        wrong.append("timed effects: taken from the prompt's exact times")
        data["timed_effects"] = [t.model_dump() for t in rules.timed_effects]
    missing = sorted(set(rules.effects) - set(llm.effects))
    if missing:
        wrong.append(f"effects missed: {missing}")
        data["effects"] = sorted(set(llm.effects) | set(rules.effects))
    defaults = Intent().model_dump()
    llm_only = [f"{k}={v}" for k, v in data.items()
                if k not in ("recognized", "brightness") and v != defaults[k] and getattr(rules, k) == defaults[k]]
    data["recognized"] = list(rules.recognized) + [f"(llm) {x}" for x in llm_only]
    return Intent.model_validate(data), wrong


ACTION_WORDS = (r"\b(josh|fan ?edit|sports?|football|cricket|match|goal|gym|workout|dance|party|hype|action|fast|tez|"
                r"velocity|phonk|beat|race|bike|car|skate|fight)\b")


def _is_action(ctx: AgentContext, total: float) -> bool:
    """Footage (or words) that call for fast cuts: already-cut highlights (many scene changes), or the user asked."""
    assert ctx.analysis is not None
    if re.search(ACTION_WORDS, ctx.prompt.lower()):
        return True
    scenes = sum(len(c.scenes) for c in ctx.analysis.clips.values())
    # a highlight / fan clip changes scene every few seconds; drone & travel shots run on without a cut
    return scenes / max(total, 1.0) > 0.25


def autopilot(ctx: AgentContext, it: Intent) -> Intent:
    """"Mast sa edit kar do": choose a complete edit from what the clips contain. Anything the user did say wins.

    Talking videos keep every sentence (jump cuts, captions, soft ducked music); videos without speech become a
    beat-synced montage. Kept cheap on purpose: one motion effect, no transitions on talking videos (dozens of
    cross-fades would slow the render and blur the jump cuts).
    """
    assert ctx.analysis is not None
    speech = ctx.analysis.any_speech
    total = sum(c.duration for c in ctx.analysis.clips.values())
    d = Intent().model_dump()
    upd: dict[str, Any] = {}
    notes: list[str] = []

    def pick(name: str, value: Any, note: str) -> None:
        if getattr(it, name) == d[name]:
            upd[name] = value
            notes.append(note)

    pick("order", "smart", "clips in the order they were filmed, best moment first")
    pick("remove_idle", True, "frozen parts cut")
    if not it.effects and not it.timed_effects:  # "starting ke 3 sec zoom" means ONLY there
        upd["effects"] = ["zoom"]
        notes.append("slow zoom")
    if not it.restore_color:  # "color wapas lao" = the footage's own colours, not the autopilot's vivid
        pick("color_preset", "vivid", "vivid colour")
    if not it.mute and not re.search("|".join(NO_MUSIC), ctx.prompt.lower()):
        pick("music", True, "background music")
        pick("music_mood", "calm" if speech else "upbeat", "")
    if speech:
        pick("remove_silence", True, "pauses removed")
        pick("remove_fillers", True, "um/uh removed")
        if ctx.analysis.any_words:  # people talk but no word could be read: captions would only fail
            pick("captions", True, "captions of what you say")
            pick("text_animation", "pop", "pop-in captions")
        if total > 90:
            pick("target_duration", 60.0, "cut to 60 s")
    elif total > 15 and not _is_action(ctx, total) and not it.use_reference:
        # (with a reference video its measured rhythm is the instruction — the calm-footage defaults must not win)
        # scenic footage (drone, travel, nature, pets): a pro lets each shot breathe ~2.5 s and keeps the shots of
        # one place together — cutting a slow drone shot every 0.5 s and ping-ponging between places looked
        # chaotic on the user's trip footage (tested as a noob user, 2026-10-08)
        guessed = set(it.inferred_fields)  # what the genre guess ("a reel = fast cuts") filled in, not the user
        # hook-first / peak-last reorder pieces of ONE shot (the drone flew backwards, a 0.5 s scrap ended the reel);
        # calm footage gets calm music
        for fld, val in (("fast_cuts", False), ("cut_length", 2.5), ("hook_first", False), ("ending_peak", False),
                         ("music_mood", "calm")):
            if fld in guessed or getattr(it, fld) == d[fld] or (fld == "music_mood" and "music_mood" in upd):
                upd[fld] = val
        notes.append("shots of ~2.5 s (calm footage: drone / travel / nature)")
        upd["inferred_fields"] = sorted({*it.inferred_fields, "cut_length"} - {"fast_cuts"})
        if it.order in ("original", "smart"):  # "smart" was this autopilot's own default above
            upd["order"] = "original"
            notes.append("each place kept together, in filming order")
        if total > 25:
            pick("target_duration", 20.0, "a 20 s reel")
    elif total > 15:
        # action / already-cut footage: hard cuts on the beat. (Cross-fading dozens of 1 s cuts looks mushy and
        # made a 37-cut edit take minutes to join, measured on the user's footage.)
        pick("fast_cuts", True, "fast cuts")
        pick("beat_sync", True, "cuts on the music beat")
        if total > 30:
            pick("target_duration", 30.0, "cut to 30 s")
    else:
        pick("transition", "crossfade", "smooth transitions")  # a few short clips: soft joins
    upd["recognized"] = [*it.recognized, *(f"auto: {n}" for n in notes if n)]
    return it.model_copy(update=upd)


def _apply_options(ctx: AgentContext, intent: Intent) -> Intent:
    """API overrides from the studio UI: number of styled versions / a named look."""
    if ctx.options.get("variations"):
        intent.variations = int(ctx.options["variations"])
    if ctx.options.get("style"):
        intent.style = ctx.options["style"]
    return intent


class Tracker(Protocol):
    def stage(self, name: str, progress: float) -> None: ...
    def agent(self, name: str, status: str, progress: float = 0.0, message: str = "",
              score: float | None = None, attempts: int | None = None) -> None: ...


class NullTracker:
    def stage(self, name: str, progress: float) -> None:
        pass

    def agent(self, name: str, status: str, progress: float = 0.0, message: str = "",
              score: float | None = None, attempts: int | None = None) -> None:
        pass


class JobError(RuntimeError):
    """A user-facing failure with a clear message."""


@dataclass
class JobResult:
    plan: EditPlan
    review: Review
    output: Path
    intent: Intent
    attempts: dict[str, int]
    history: list[dict[str, Any]] = field(default_factory=list)
    modes: dict[str, str] = field(default_factory=dict)
    variations: list[dict[str, Any]] = field(default_factory=list)


class DirectorAgent(BaseAgent):
    name = "director"
    system_prompt = (
        "You turn a video-editing request into JSON. Include ONLY the keys the user asked for and omit all others. "
        "Keys: target_duration (seconds), aspect_ratio (\"9:16\" reel/short/vertical, \"1:1\" square, \"16:9\" "
        "landscape), resolution (360|480|720|1080), color_preset (warm|cool|cinematic|vintage|bw|vivid), captions, "
        "remove_silence, remove_fillers, fast_cuts, slow_motion, music, beat_sync, music_mood (upbeat|calm), "
        "transition (fade|crossfade|zoom|wipe), effects (list of zoom|speed_ramp|blur_background|shake), title, "
        "voice_cleanup, order (reverse|best), rotate (90|180|270), flip (h|v), reverse_playback, fps (24|25|30|50|60), "
        "gamma, mute, loudness (louder|quieter), audio_fade, watermark (text), remove_idle, export_gif, export_mp3.\n"
        "Example: \"trim to 20 seconds with captions\" -> {\"target_duration\": 20, \"captions\": true}\n"
        "Example: \"vertical reel, cool tones, crossfades, 1080p\" -> {\"aspect_ratio\": \"9:16\", \"color_preset\": "
        "\"cool\", \"transition\": \"crossfade\", \"resolution\": 1080}"
    )

    def __init__(self) -> None:
        self.analyzer = AnalyzerAgent()
        self.team: dict[str, BaseAgent] = {
            "audio": AudioAgent(), "cutter": CutterAgent(), "color": ColorAgent(), "effects": EffectsAgent(),
        }
        self.reviewer = ReviewerAgent()

    # ---- intent ------------------------------------------------------------------------------------
    def understand(self, ctx: AgentContext) -> tuple[Intent, str]:
        prompt = validate_prompt(ctx.prompt)
        lessons = self.lessons(ctx)
        user = f"User request: {prompt}"
        if ctx.memory is not None and ctx.project_id:
            user += f"\nWhat you remember about this user: {ctx.memory.summary(ctx.project_id)}"
        if lessons:
            user += "\nLessons from past mistakes:\n" + "\n".join(f"- {lsn}" for lsn in lessons)
        mode = "rules"
        if ctx.settings.llm_enabled_for(self.name) and ctx.llm is not None:
            try:
                intent, tries = chat_json(ctx.llm, self.system_prompt, user, Intent, lenient=True)
                if not intent.recognized:
                    intent.recognized = [f"{k}={v}" for k, v in intent.model_dump(exclude_defaults=True).items()]
                mode = "llm"
                ctx.log(self.name, "info", f"LLM intent in {tries} attempt(s)")
                intent, wrong = reconcile(intent, parse_intent(prompt), prompt)
                ctx.intent_disagreements = wrong
                for w in wrong:
                    ctx.log(self.name, "warn", f"LLM misread the prompt, corrected by keyword guard: {w}")
            except LLMError as exc:
                ctx.log(self.name, "warn", f"LLM intent failed ({str(exc)[:120]}); using rule parser")
                intent, mode = parse_intent(prompt), "llm_fallback"
        else:
            intent = parse_intent(prompt)
        if ctx.db is not None:
            ctx.db.record_run(ctx.job_id, self.name, 1, user, intent.model_dump(), mode)
        return intent, mode

    # ---- plan assembly -------------------------------------------------------------------------------
    @staticmethod
    def merge(sections: dict[str, Any], decisions: list[dict[str, str]] | None = None) -> EditPlan:
        seen: set[tuple[str, str]] = set()
        uniq = []
        for d in decisions or []:
            key = (d["decision"], d["where"])
            if key not in seen:
                seen.add(key)
                uniq.append(d)
        try:
            plan = EditPlan.model_validate({
                "decisions": uniq[:400],
                "canvas": sections["effects"]["canvas"],
                "clips": sections["cutter"]["clips"],
                # the cutter may start the song later so its drop lands inside the edit
                "audio": {**sections["audio"], **({"music_start": sections["cutter"]["music_start"]}
                                                  if sections["cutter"].get("music_start") else {})},
                "color": sections["color"],
                "text": sections["effects"]["text"],
                "transitions": sections["effects"]["transitions"],
                "effects": sections["effects"]["effects"],
                "export": sections["effects"].get("export", {}),
                "focus": sections["effects"].get("focus"),
                "stickers": sections["effects"].get("stickers", []),
            })
        except ValidationError as exc:
            raise JobError(f"agents produced an invalid edit plan: {exc.errors()[0].get('msg', exc)}") from exc
        # one deterministic effect order + merged duplicates + resolved conflicts (engines/stack.py)
        from ..engines.stack import resolve

        plan, notes = resolve(plan)
        if notes:
            extra = [Decision(decision="effect stack", where="", reason=n[:300], skill="stack") for n in notes
                     if not n.startswith("effects ordered")]
            plan = plan.model_copy(update={"decisions": (plan.decisions + extra)[:400]})
        return plan

    def run_agent(self, ctx: AgentContext, name: str, tracker: Tracker, attempts: dict[str, int],
                  modes: dict[str, str], feedback: list[Feedback] | None = None) -> None:
        agent = self.team[name]
        attempts[name] = attempts.get(name, 0) + 1
        if name == "cutter":  # a new cut: earlier per-segment decisions no longer apply (the song's ones still do)
            ctx.decisions = [d for d in ctx.decisions if d["decision"] in AUDIO_DECISIONS or d["skill"] == "learning"]
        tracker.agent(name, "retrying" if feedback else "running", 0.1, "working", attempts=attempts[name])
        live.started(tracker, name)
        result = agent.run(ctx, feedback, attempts[name])
        ctx.sections[name] = result.output
        if name == "cutter":
            ctx.sections["clips"] = result.output["clips"]
        modes[name] = result.mode
        for note in result.notes:
            ctx.log(name, "info", note)
        tracker.agent(name, "done", 1.0, f"done ({result.mode})", attempts=attempts[name])
        live.finished(ctx, tracker, name)  # the app draws this agent's part of the timeline

    # ---- main loop -----------------------------------------------------------------------------------------
    def run_job(self, ctx: AgentContext, output: Path, tracker: Tracker | None = None, resume: bool = False) -> JobResult:
        """Run the edit as a LangGraph workflow (see cutmind/workflow.py): checkpointed, with parallel planning."""
        from ..workflow import run

        if not ctx.clips:
            raise JobError("This project has no clips. Upload at least one video clip first.")
        assert ctx.work_dir is not None
        ctx.work_dir.mkdir(parents=True, exist_ok=True)
        return run(self, ctx, output, tracker or NullTracker(), resume=resume)

    # ---- looks & variations ------------------------------------------------------------------------------
    @staticmethod
    def _bring_sound_back(ctx: AgentContext, intent: Intent, rules: Intent) -> tuple[Intent, Intent]:
        """"Audio nahi aa raha, pehle jaisa la do": if the clips have no sound of their own, the sound the user heard
        before was the SONG of an earlier edit — that song comes back (a caption tweak had made a new edit without it)."""
        from ..ffmpeg_utils import FFmpegError, measure_loudness

        def audible(c: Any) -> bool:
            try:
                return measure_loudness(c.media).get("max_volume", -99.0) > -50
            except (FFmpegError, OSError):
                return False

        if any(audible(c) for c in ctx.clips) or ctx.db is None or not ctx.project_id:
            return intent, rules  # their own sound exists: unmuting it (audio agent) is the fix
        song = None
        for row in ctx.db.all("SELECT plan FROM jobs WHERE project_id=? AND status='done' AND plan IS NOT NULL "
                              "ORDER BY created_at DESC LIMIT 30", (ctx.project_id,)):
            try:
                song = (json.loads(row["plan"]) or {}).get("audio", {}).get("music")
            except (TypeError, ValueError):
                continue
            if song:
                break
        if not song:
            ctx.log("director", "warn", "the clips have no sound and no earlier edit had music: adding a song instead")
        else:
            ctx.options.setdefault("music_track", song)
            ctx.decide("sound back", song, "your clips have no sound of their own — what you heard before was this "
                       "song from an earlier edit, so it is back", "audio_mix")
        upd = {"music": True, "music_volume": 0.9, "recognized": [*intent.recognized, "the earlier song back"]}
        return intent.model_copy(update=upd), rules.model_copy(update={"music": True, "music_volume": 0.9})

    @staticmethod
    def _use_memory(ctx: AgentContext, intent: Intent, rules: Intent) -> tuple[Intent, Intent]:
        """Long-term memory: repeat the previous edit on request, apply the user's favourite look."""
        mem = ctx.memory
        if mem is None or not ctx.project_id or ctx.options.get("copy_edit"):
            return intent, rules  # Copy an Edit copies the liked video, not the last edit
        ctx.log("director", "info", f"Memory: {mem.summary(ctx.project_id)}")
        defaults = Intent().model_dump()
        rows = mem.history(ctx.project_id, 1)  # only THIS project's last edit is "the current edit"
        last = rows[0]["intent"] if rows else None
        repeat = wants_repeat(ctx.prompt)
        if last and (repeat or intent.remove or intent.from_comment or is_follow_up(ctx.prompt, rules)):
            merged: list[Intent] = []
            for it in (intent, rules):
                merged.append(merge_with_last(it, last, defaults, repeat))
            intent, rules = merged
            ctx.options["follow_up"] = True
            ctx.log("director", "info", ("Repeating the previous edit" if repeat else "Changing the current edit")
                    + " from memory, with this message's changes on top.")
        if intent.restore_audio:
            intent, rules = DirectorAgent._bring_sound_back(ctx, intent, rules)
        if wants_my_style(ctx.prompt) and not intent.style:
            fav = mem.preferences().get("favourite_style")
            if fav:
                intent = intent.model_copy(update={"style": fav, "recognized": [*intent.recognized, f"your favourite look: {fav}"]})
                rules = rules.model_copy(update={"style": fav, "recognized": [*rules.recognized, f"favourite look {fav}"]})
                ctx.log("director", "info", f"Using your favourite look from memory: {fav}")
        return intent, rules

    @staticmethod
    def _styled(ctx: AgentContext, plan: EditPlan) -> EditPlan:
        """Single requested look: applied to every merged plan (also after retries)."""
        it = ctx.intent
        if it and it.style and it.variations == 1:
            return apply_style(plan, it.style, keep_color=it.color_preset is not None)
        return plan

    def _variations(self, ctx: AgentContext, base: EditPlan, intent: Intent, sources: dict[str, Path],
                    positions: dict[str, int], output: Path, tracker: Tracker, dmode: str
                    ) -> tuple[list[dict[str, Any]], EditPlan, Review, Path]:
        """Render the same cut in N looks, review each, rank best first. The best becomes the main output."""
        assert ctx.work_dir is not None
        order = [intent.style] if intent.style else []
        prefs = ctx.memory.preferences() if ctx.memory is not None else {}
        if not order and prefs.get("favourite_style"):
            order = [prefs["favourite_style"]]  # the look this user keeps choosing is rendered (and ranked) first
        order += [sid for sid in DEFAULT_ORDER if sid not in order]
        results = []
        for i, sid in enumerate(order[: intent.variations]):
            style = STYLES[sid]
            tracker.stage(f"rendering version {i + 1}/{intent.variations}: {style.name}", min(0.97, 0.88 + 0.03 * i))
            ctx.log("director", "info", f"version {i + 1}: {style.name} — {style.description}")
            vplan = apply_style(base, sid, keep_color=intent.color_preset is not None)
            live.variation(ctx, tracker, i + 1, intent.variations, style.name, style.description, vplan)
            out_v = ctx.work_dir / f"var_{i}.mp4"
            render_sources = ({c.id: c.media for c in ctx.clips} if vplan.canvas.resolution <= PROXY_SHORT_SIDE
                              else sources)
            try:
                render(vplan, render_sources, ctx.work_dir / f"v{i}", out_v, music_dirs(ctx.settings, ctx.project_id),
                       cache_dir=ctx.work_dir.parent.parent / "cache")
            except Exception as exc:  # noqa: BLE001 — one failed look must not sink the others
                ctx.log("director", "error", f"version {style.name} failed to render: {exc}")
                continue
            rev = self.reviewer.review(vplan, out_v, ctx.reference_intent, ctx.analysis, sources, positions,
                                       ctx.sections["cutter"].get("available_duration"), ctx.options,
                                       ctx.intent_disagreements if dmode == "llm" else None)
            results.append((rev.match_percent, -i, sid, vplan, rev, out_v))
        if not results:
            raise JobError("None of the styled versions could be rendered.")
        disliked = set(prefs.get("disliked_styles") or [])
        # the look the user ASKED for is the edit (rank 0) whatever it scores — it shipped Midnight Drift for a
        # "violet" ask before; the other looks are ranked best match first (a tie: the favourite wins, disliked last)
        asked = intent.style
        results.sort(key=lambda r: (r[2] == asked, r[0] - (5 if r[2] in disliked else 0), r[1]), reverse=True)
        variations: list[dict[str, Any]] = []
        for rank, (match, _neg, sid, vplan, _rev, out_v) in enumerate(results):
            dest = output.with_name(f"{output.stem}_v{rank}.mp4")
            shutil.copyfile(out_v, dest)
            # the plan goes with its video: "Use this" makes THIS plan the current edit (timeline, next edit, undo)
            variant_plan_path(dest).write_text(json.dumps(vplan.to_json()), encoding="utf-8")
            for kind in ("gif", "mp3"):
                if extra_path(out_v, kind).exists():
                    shutil.copyfile(extra_path(out_v, kind), extra_path(dest, kind))
            info = probe(dest)
            variations.append({"index": rank, "style": sid, "name": STYLES[sid].name,
                               "description": STYLES[sid].description, "match_percent": match,
                               "duration": round(info.duration, 3), "width": info.width, "height": info.height,
                               "chosen": rank == 0})
        ctx.log("director", "info", "Created %d versions, ranked best first: %s" % (
            len(variations), ", ".join(f"{v['name']} ({v['match_percent']}%)" for v in variations)))
        _m, _n, _sid, best_plan, best_review, best_out = results[0]
        return variations, best_plan, best_review, best_out

    def record(self, ctx: AgentContext, review: Review, attempt: int) -> None:
        """Persist +/- points per check and turn every failure into a lesson."""
        if ctx.db is None:
            return
        for c in review.checks:
            ctx.db.add_score(ctx.job_id, c.owner, attempt, c.name, c.points, c.detail[:300])
            # a limit of the footage (e.g. nobody speaks) is not an agent mistake: no lesson, it would mislead
            if not c.passed and c.data.get("fixable", True):
                hint = LESSON_HINTS.get(c.name, "Follow the user's instruction exactly.")
                text = f"{c.name}: {hint} (last time: {c.detail[:120]})"
                ctx.db.add_lesson(c.owner, c.name, text, ctx.job_id)
