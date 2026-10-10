"""Shared agent plumbing: context, results, lessons injection, LLM-or-rules execution."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from ..config import Settings
from ..db import Database
from ..intent import Intent
from ..llm import LLMClient, LLMError, chat_json

LogFn = Callable[[str, str, str], None]  # (agent, level, message)


@dataclass
class ClipRef:
    id: str
    path: Path               # original upload
    filename: str
    position: int
    proxy: Path | None = None  # light H.264 copy (see cutmind/proxy.py)

    @property
    def media(self) -> Path:
        """File to decode for analysis / ≤720p renders."""
        return self.proxy if self.proxy is not None and self.proxy.exists() else self.path


@dataclass
class Feedback:
    """Reviewer feedback for one agent (failed checks), passed back on retry."""

    check: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentContext:
    job_id: str
    prompt: str
    clips: list[ClipRef]
    settings: Settings
    db: Database | None = None
    llm: LLMClient | None = None
    log: LogFn = lambda agent, level, msg: None
    work_dir: Path | None = None
    intent: Intent | None = None
    analysis: Any = None                   # ProjectAnalysis
    sections: dict[str, Any] = field(default_factory=dict)  # plan sections written so far
    music_beats: list[float] = field(default_factory=list)
    song: Any = None  # cutmind.song.SongProfile of the chosen music (tempo, energy, feel, drop)
    song_base: Any = None  # the whole song when `song` was shifted to a later start
    lyrics: list[Any] = field(default_factory=list)  # sung words of the song (song time), when known
    music_start: float = 0.0  # seconds into the song where the edit's music starts
    learned: dict[str, str] | None = None  # learned option per taste knob (cutmind/learning.py), chosen once per job
    options: dict[str, Any] = field(default_factory=dict)  # API overrides (aspect_ratio, resolution)
    project_id: str | None = None
    memory: Any = None  # cutmind.memory.Memory — long-term memory of past edits and preferences
    # Independent, keyword-based reading of the prompt. The Reviewer grades against this (not against the
    # LLM's own interpretation, which would let an LLM misunderstanding grade itself as correct).
    reference_intent: Intent | None = None
    intent_disagreements: list[str] = field(default_factory=list)
    need_transcript: bool = True  # the AgentRouter turns speech-to-text off for edits that don't use words
    decisions: list[dict[str, str]] = field(default_factory=list)  # every editorial choice, with its reason
    spec_decisions: list[dict[str, str]] = field(default_factory=list)  # from the edit spec (whole-edit choices)
    spec: dict[str, Any] | None = None
    blueprint: Any = None  # Copy an Edit: the liked video's shot list (cutmind/blueprint.py)

    def decide(self, decision: str, where: str, reason: str, skill: str = "") -> None:
        """Record WHY an edit was made (shown in the app, stored in the plan)."""
        self.decisions.append({"decision": decision, "where": where, "reason": reason, "skill": skill})


@dataclass
class AgentResult:
    agent: str
    output: dict[str, Any]
    mode: str                 # rules | llm | llm_fallback
    prompt: str
    notes: list[str] = field(default_factory=list)


# Which request makes a lesson from a given Reviewer check relevant. Checks not listed always apply.
_LESSON_NEEDS: dict[str, Callable[[Intent], bool]] = {
    "duration": lambda i: bool(i.target_duration),
    "no_unrequested_trim": lambda i: not i.target_duration,
    "silence_removed": lambda i: i.remove_silence,
    "captions_present": lambda i: i.captions,
    "speech_detected": lambda i: i.captions,
    "title_present": lambda i: bool(i.title),
    "transitions_present": lambda i: bool(i.transition),
    "aspect_ratio": lambda i: bool(i.aspect_ratio),
    "resolution": lambda i: bool(i.resolution),
    "music_present": lambda i: i.music,
    "no_unrequested_music": lambda i: not i.music,
    "color_applied": lambda i: bool(i.color_preset) or bool(i.brightness),
    "clip_order": lambda i: i.order != "original",
    "orientation": lambda i: bool(i.rotate) or i.flip != "none",
    "reverse_playback": lambda i: i.reverse_playback,
    "frame_rate": lambda i: bool(i.fps),
    "muted": lambda i: i.mute,
    "audio_fade": lambda i: i.audio_fade,
    "watermark_present": lambda i: bool(i.watermark),
    "idle_removed": lambda i: i.remove_idle,
    "extras_exported": lambda i: i.export_gif or i.export_mp3,
    "timed_effects": lambda i: bool(i.timed_effects),
    "bass_boost": lambda i: i.bass_boost,
}


def lesson_applies(check_name: str, intent: Intent) -> bool:
    need = _LESSON_NEEDS.get(check_name)
    return need is None or need(intent)


class BaseAgent:
    name = "base"
    system_prompt = "You are a helpful video editing agent. Reply with JSON only."
    decision_model: type[BaseModel] | None = None  # what the LLM is asked to produce (local LLM mode)

    # ---- prompt building (lessons are always injected) ------------------------------------------
    def lessons(self, ctx: AgentContext, limit: int = 5) -> list[str]:
        """This agent's lessons that matter for THIS request (a duration lesson only when a length is asked, …)."""
        if ctx.db is None:
            return []
        rows = ctx.db.recent_lessons(self.name, 50)
        it = ctx.intent
        if it is not None:
            rows = [r for r in rows if lesson_applies(r["check_name"], it)]
        return [row["text"] for row in rows[:limit]]

    def task_payload(self, ctx: AgentContext) -> dict[str, Any]:
        """Facts the agent needs; subclasses extend."""
        return {"prompt": ctx.prompt, "intent": ctx.intent.model_dump() if ctx.intent else None}

    def build_prompt(self, ctx: AgentContext, feedback: list[Feedback] | None = None) -> str:
        parts = [f"TASK for the {self.name} agent.", "INPUT:", json.dumps(self.task_payload(ctx), default=str)[:6000]]
        lessons = self.lessons(ctx)
        if lessons:
            parts.append("LESSONS FROM PAST MISTAKES (follow them):")
            parts += [f"- {lsn}" for lsn in lessons]
        if feedback:
            parts.append("REVIEWER FEEDBACK ON YOUR LAST ATTEMPT (fix these):")
            parts += [f"- [{f.check}] {f.detail}" for f in feedback]
        parts.append("Reply with ONLY a JSON object matching the schema.")
        return "\n".join(parts)

    # ---- execution --------------------------------------------------------------------------------
    def rules(self, ctx: AgentContext, feedback: list[Feedback] | None) -> dict[str, Any]:
        raise NotImplementedError

    def from_decision(self, ctx: AgentContext, decision: BaseModel, feedback: list[Feedback] | None) -> dict[str, Any]:
        """Turn the LLM decision into a plan section (deterministic code does the exact maths)."""
        raise NotImplementedError

    def run(self, ctx: AgentContext, feedback: list[Feedback] | None = None, attempt: int = 1) -> AgentResult:
        prompt = self.build_prompt(ctx, feedback)
        notes: list[str] = []
        mode = "rules"
        output: dict[str, Any]
        if ctx.settings.llm_enabled_for(self.name) and self.decision_model is not None and ctx.llm is not None:
            try:
                decision, tries = chat_json(ctx.llm, self.system_prompt, prompt, self.decision_model)
                output = self.from_decision(ctx, decision, feedback)
                mode = "llm"
                notes.append(f"LLM decision in {tries} attempt(s): {decision.model_dump_json()[:300]}")
            except (LLMError, ValueError) as exc:
                ctx.log(self.name, "warn", f"LLM failed ({str(exc)[:160]}); using rule-based fallback")
                output = self.rules(ctx, feedback)
                mode = "llm_fallback"
                notes.append(f"llm_fallback: {str(exc)[:200]}")
        else:
            output = self.rules(ctx, feedback)
        if ctx.db is not None:
            ctx.db.record_run(ctx.job_id, self.name, attempt, prompt, output, mode)
        return AgentResult(self.name, output, mode, prompt, notes)
