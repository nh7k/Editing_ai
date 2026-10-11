"""What the user did with the agent's readings, kept locally to learn from (docs/UNDERSTANDING_REVIEW.md, Phase 5).

Every message the skill resolver handled is stored with its context, its decision, what ran and the alternatives
shown, and then the user's reaction:
  picked      a chip was tapped (the reading the user wanted)            → positive for that skill
  kept        the applied reading stayed (no undo, no rephrase)          → positive (implicit)
  undone      ↶ Undo right after it                                       → negative for what ran
  rephrased   a new message within 30 s of it                            → negative for what ran
`learned()` turns these into a per-skill boost for the SAME words (half-life 30 days). Nothing is ever added to
the shared synonym registry automatically: `eval/review_failed_prompts.py` writes a review file for a human.

Local only (this server's database). `forget()` deletes it all ("reset my data"). A server upload, if ever added,
must be opt-in and anonymised (no project ids, no file names).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .tools.fuzzy import FILLER, canonical_words

HALF_LIFE_DAYS = 30.0
REPHRASE_S = 30.0
WEIGHT = {"picked": 1.0, "kept": 0.3, "undone": -1.0, "rephrased": -0.5}
CORRECTION = {"nahi", "nhi", "galat", "wrong", "not", "no", "mat", "ulta", "dusra", "doosra"}


def key(prompt: str) -> str:
    """The prompt's meaning words in order — the same request typed slightly differently gets the same key."""
    return " ".join(w for w in canonical_words(prompt) if w not in FILLER)[:200]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UnmetLog:
    def __init__(self, db: Any) -> None:
        self.db = db
        db.execute("CREATE TABLE IF NOT EXISTS ambiguous_requests (id TEXT PRIMARY KEY, created_at TEXT, project_id "
                   "TEXT, prompt TEXT, key TEXT, context TEXT, decision TEXT, choices TEXT, picked TEXT)")
        have = {r["name"] for r in db.all("PRAGMA table_info(ambiguous_requests)")}
        for col in ("applied", "job_id", "reaction"):  # added for the learning loop (older rows: NULL)
            if col not in have:
                db.execute(f"ALTER TABLE ambiguous_requests ADD COLUMN {col} TEXT")

    def log(self, project_id: str | None, prompt: str, context: dict[str, Any], decision: str,
            choices: list[dict[str, Any]], applied: list[str] | None = None, job_id: str | None = None) -> str:
        if project_id:
            self._rephrased(project_id, prompt)
        rid = "amb_" + uuid.uuid4().hex[:12]
        ctx = {k: v for k, v in context.items() if not k.startswith("_") and k != "learned"}
        self.db.execute(
            "INSERT INTO ambiguous_requests(id, created_at, project_id, prompt, key, context, decision, choices, picked,"
            " applied, job_id, reaction) VALUES (?,?,?,?,?,?,?,?,NULL,?,?,NULL)",
            (rid, _now().isoformat(timespec="seconds"), project_id, prompt[:500], key(prompt), json.dumps(ctx)[:4000],
             decision, json.dumps([c["id"] for c in choices]), json.dumps(applied or []), job_id))
        return rid

    def _rephrased(self, project_id: str, prompt: str) -> None:
        """The SAME request said again soon after an applied reading (or a correction: "nahi", "galat"): that reading
        probably missed. A different request is not a rephrase — "black and white karo" then "yaha normal karo"
        marked black and white as a miss (found by tests/integration/test_understanding_e2e.py)."""
        row = self.db.one("SELECT id, created_at, reaction, picked, applied, key FROM ambiguous_requests WHERE "
                          "project_id=? ORDER BY created_at DESC LIMIT 1", (project_id,))
        if row is None or row["reaction"] or row["picked"] or row["applied"] in (None, "[]"):
            return
        a, b = set((row["key"] or "").split()), set(key(prompt).split())
        alike = bool(a and b) and len(a & b) / len(a | b) >= 0.5
        correcting = bool(CORRECTION & set(canonical_words(prompt)))
        if not (alike or correcting):
            return
        age = (_now() - datetime.fromisoformat(row["created_at"])).total_seconds()
        if age <= REPHRASE_S:
            self.db.execute("UPDATE ambiguous_requests SET reaction='rephrased' WHERE id=?", (row["id"],))

    def pick(self, rid: str, choice_id: str) -> bool:
        row = self.db.one("SELECT id FROM ambiguous_requests WHERE id=?", (rid,))
        if row is None:
            return False
        self.db.execute("UPDATE ambiguous_requests SET picked=?, reaction='picked' WHERE id=?", (choice_id[:60], rid))
        return True

    def undone(self, job_id: str) -> None:
        """↶ Undo of the version this request made."""
        self.db.execute("UPDATE ambiguous_requests SET reaction='undone' WHERE job_id=? AND (reaction IS NULL OR "
                        "reaction='kept')", (job_id,))

    def learned(self, prompt: str) -> dict[str, float]:
        """Skill → signed, time-decayed evidence from this user's reactions to these same words."""
        rows = self.db.all("SELECT created_at, picked, applied, reaction FROM ambiguous_requests WHERE key=?",
                           (key(prompt),))
        out: dict[str, float] = {}
        for r in rows:
            age_days = (_now() - datetime.fromisoformat(r["created_at"])).total_seconds() / 86400
            decay = 0.5 ** (age_days / HALF_LIFE_DAYS)
            reaction = r["reaction"] or ("kept" if r["applied"] not in (None, "[]") else None)
            if reaction is None:
                continue
            targets = [r["picked"]] if reaction == "picked" and r["picked"] else json.loads(r["applied"] or "[]")
            for sid in targets[:3]:
                out[sid] = out.get(sid, 0.0) + WEIGHT[reaction] * decay
        return {k: round(v, 3) for k, v in out.items() if abs(v) > 0.05}

    def recent(self, limit: int = 500) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.all(
            "SELECT * FROM ambiguous_requests ORDER BY created_at DESC LIMIT ?", (limit,))]

    def forget(self) -> int:
        """Reset my data: every stored request and reaction is deleted."""
        n = self.db.one("SELECT COUNT(*) AS n FROM ambiguous_requests")["n"]
        self.db.execute("DELETE FROM ambiguous_requests")
        return int(n)
