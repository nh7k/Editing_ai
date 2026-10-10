"""The agents learn the user's taste from what happens after an edit (reinforcement learning, bandit style).

Some editing choices have no single right answer: how fast to cut, how hard the beat punches hit, how much black &
white, how calm or punchy the text moves, how many impact hits. For each such KNOB there are three options. Every
edit picks one option per knob with Thompson sampling: sample each option's Beta(successes, failures) and take the
best sample — so options that worked are used more, and others are still tried now and then (exploration).

Rewards come from the user, per video type + song feel (a fan edit on a slow song is a different context from a
vlog):
* 👍 / 👎 on the edit                                  → 1 / 0 for every knob that edit used
* "same as before", "perfect", "mast hai" next prompt  → 1
* "thoda slow kar", "zoom kam", "black & white kam"   → 0 for the knob it complains about
* removing an effect / changing text by hand            → 0 for that knob

Everything is stored in SQLite (`learn_arms`, `learn_choices`). CPU only, instant. The same records are the
preference data for fine-tuning a language model later (see docs/LEARNING.md).
"""

from __future__ import annotations

import random
import re
from typing import Any

from .db import Database, now_iso

KNOBS: dict[str, dict[str, float]] = {
    "pace": {"slower": 1.3, "as_is": 1.0, "faster": 0.75},       # × seconds per cut
    "punch": {"soft": 0.65, "normal": 1.0, "hard": 1.35},        # × beat punch strength
    "bw_rate": {"few": 4.0, "some": 3.0, "many": 2.0},           # colour pass: every Nth shot
    "text_mood": {"calm": -1.0, "match": 0.0, "punchy": 1.0},    # shift of the animation set vs the song energy
    "hits": {"few": 0.6, "normal": 1.0, "more": 1.5},            # × number of impact hits
}
DEFAULT = {"pace": "as_is", "punch": "normal", "bw_rate": "some", "text_mood": "match", "hits": "normal"}

# what a complaint in the next prompt is about → the knob that gets reward 0
COMPLAINTS: list[tuple[str, str]] = [
    (r"(thoda |zyada |bahut |too |very )?(slow|dheere|dheema)\s*(kar|karo|rakh|hai|ho gaya)|too fast|(bahut|zyada) (tez|fast)"
     r"|less (fast|quick)|cuts? (kam|slow)", "pace"),
    (r"(thoda |aur |more )?(fast|tez|quick)\s*(kar|karo|rakh)|too slow|(bahut|zyada) slow|boring", "pace"),
    (r"(zoom|punch|jhatka|shake)\s*(kam|halka|less|mat)|less (zoom|punch)|too much (zoom|punch)|(zoom|punch) (zyada|aur)", "punch"),
    (r"(black (and|&) white|b ?& ?w|colou?r pass)\s*(kam|less|zyada|more|aur)|too much (black|b&w)", "bw_rate"),
    (r"(animation|text)\s*(kam|halka|slow|tez|fast|zyada)|text (bahut|too) (fast|slow|much)", "text_mood"),
    (r"(flash|glitch|hit|blur hit|impact)\w*\s*(kam|less|zyada|more|mat)|too many (flash|hit)", "hits"),
]
PRAISE = r"\b(same as before|perfect|mast hai|bahut (accha|badhiya|mast)|love (it|this)|nice edit|great edit|exactly)\b"
# by-hand changes that tell which knob missed
MANUAL_KNOB = {"pulse": "punch", "punch": "punch", "impact": "hits", "flash": "hits", "film_bw": "bw_rate",
               "mono": "bw_rate", "silhouette": "bw_rate", "invert_mono": "bw_rate"}


class Learner:
    def __init__(self, db: Database, rng: random.Random | None = None) -> None:
        self.db = db
        self.rng = rng or random.Random()
        db.execute("CREATE TABLE IF NOT EXISTS learn_arms (context TEXT, knob TEXT, option TEXT, wins REAL, losses REAL, "
                   "PRIMARY KEY (context, knob, option))")
        db.execute("CREATE TABLE IF NOT EXISTS learn_choices (job_id TEXT, project_id TEXT, context TEXT, knob TEXT, "
                   "option TEXT, rewarded INTEGER DEFAULT 0, created_at TEXT, PRIMARY KEY (job_id, knob))")

    # ---- choosing ------------------------------------------------------------------------------------
    def _arm(self, context: str, knob: str, option: str) -> tuple[float, float]:
        row = self.db.one("SELECT wins, losses FROM learn_arms WHERE context=? AND knob=? AND option=?", (context, knob, option))
        if row:
            return row["wins"], row["losses"]
        return (3.0, 2.0) if option == DEFAULT[knob] else (2.0, 2.0)  # prior: the default starts a little ahead

    def choose(self, context: str, knobs: list[str]) -> dict[str, str]:
        """One option per knob (Thompson sampling: the best random draw from each option's Beta)."""
        out: dict[str, str] = {}
        for k in knobs:
            draws = {o: self.rng.betavariate(*self._arm(context, k, o)) for o in KNOBS[k]}
            out[k] = max(draws, key=draws.get)  # type: ignore[arg-type]
        return out

    def last_choice(self, project_id: str | None) -> dict[str, str]:
        """What the previous edit of this project used (a follow-up keeps it, so only the asked change differs)."""
        if not project_id:
            return {}
        row = self.db.one("SELECT job_id FROM learn_choices WHERE project_id=? ORDER BY created_at DESC LIMIT 1",
                          (project_id,))
        if not row:
            return {}
        rows = self.db.all("SELECT knob, option FROM learn_choices WHERE job_id=?", (row["job_id"],))
        return {r["knob"]: r["option"] for r in rows}

    def record(self, job_id: str, project_id: str | None, context: str, choice: dict[str, str]) -> None:
        for k, o in choice.items():
            self.db.execute("INSERT OR REPLACE INTO learn_choices(job_id, project_id, context, knob, option, rewarded, "
                            "created_at) VALUES (?,?,?,?,?,0,?)", (job_id, project_id, context, k, o, now_iso()))

    # ---- rewards -------------------------------------------------------------------------------------
    def reward(self, job_id: str, value: float, knob: str | None = None) -> int:
        """value 1 = good, 0 = bad. Each choice is rewarded once per signal kind. Returns how many arms moved."""
        rows = self.db.all("SELECT context, knob, option FROM learn_choices WHERE job_id=?" +
                           (" AND knob=?" if knob else ""), (job_id, knob) if knob else (job_id,))
        for r in rows:
            w, lo = self._arm(r["context"], r["knob"], r["option"])
            self.db.execute("INSERT OR REPLACE INTO learn_arms(context, knob, option, wins, losses) VALUES (?,?,?,?,?)",
                            (r["context"], r["knob"], r["option"], w + value, lo + (1 - value)))
            self.db.execute("UPDATE learn_choices SET rewarded = rewarded + 1 WHERE job_id=? AND knob=?", (job_id, r["knob"]))
        return len(rows)

    def from_prompt(self, previous_job: str | None, prompt: str) -> list[str]:
        """The next prompt on the same project says how the last edit landed."""
        if not previous_job:
            return []
        p = prompt.lower()
        notes = []
        if re.search(PRAISE, p):
            self.reward(previous_job, 1.0)
            notes.append("praise")
        for pat, knob in COMPLAINTS:
            if re.search(pat, p) and self.reward(previous_job, 0.0, knob):
                notes.append(f"{knob} missed")
        return notes

    def from_manual(self, previous_job: str | None, ops: list[Any]) -> list[str]:
        notes = []
        for op in ops:
            kind = getattr(op, "op", "")
            knob = MANUAL_KNOB.get(getattr(op, "type", "") or "") if kind == "remove_effect" else \
                "text_mood" if kind == "update_text" and getattr(op, "animation", None) else None
            if previous_job and knob and self.reward(previous_job, 0.0, knob):
                notes.append(f"{knob} changed by hand")
        return notes

    # ---- what was learned (shown in the app) ---------------------------------------------------------
    def summary(self) -> list[dict[str, Any]]:
        rows = self.db.all("SELECT context, knob, option, wins, losses FROM learn_arms ORDER BY context, knob, option")
        return [{**r, "score": round(r["wins"] / (r["wins"] + r["losses"]), 2), "trials": round(r["wins"] + r["losses"] - 4, 1)}
                for r in rows]


def ensure_choice(ctx: Any) -> dict[str, float]:
    """The learned option per knob for this edit (chosen once per job, recorded for the rewards later)."""
    if ctx.learned is None:
        ctx.learned = {}
        if ctx.db is not None and ctx.intent is not None:
            learner = Learner(ctx.db)
            context = context_key(ctx.intent, ctx.song)
            knobs = knobs_for(ctx.intent)
            ctx.learned = learner.choose(context, knobs)
            if ctx.options.get("follow_up"):  # "thoda slow karo": the same edit with ONE change, not a new experiment
                prev = learner.last_choice(ctx.project_id)
                ctx.learned.update({k: o for k, o in prev.items() if k in knobs and o in KNOBS[k]})
            learner.record(ctx.job_id, ctx.project_id, context, ctx.learned)
            for k, o in ctx.learned.items():
                if o != DEFAULT[k]:
                    ctx.decide(f"learned: {k} = {o}", context, "picked from how you reacted to earlier edits like this "
                               "(the agents keep trying alternatives now and then)", "learning")
    return {k: KNOBS[k][o] for k, o in ctx.learned.items()}


def context_key(intent: Any, song: Any) -> str:
    genre = (intent.genres or ["general"])[0] if intent is not None else "general"
    return f"{genre}|{song.feel if song is not None else 'no_song'}"


def knobs_for(intent: Any) -> list[str]:
    """Only knobs that matter for this edit, and never one the user set by hand in the prompt."""
    k = []
    if intent.fast_cuts and "cut_length" not in _explicit(intent):
        k.append("pace")
    if "pulse" in intent.effects or intent.beat_sync:
        k.append("punch")
    if intent.color_pass:
        k.append("bw_rate")
    if intent.kinetic_text:
        k.append("text_mood")
    if intent.impact_hits:
        k.append("hits")
    return k


def _explicit(intent: Any) -> set[str]:
    return {"cut_length"} if intent.cut_length is not None and "cut_length" not in intent.inferred_fields else set()
