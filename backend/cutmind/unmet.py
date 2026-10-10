"""Requests the agent was not sure about, kept locally so they can be learned from (docs/INTENT_FAILURE_REVIEW.md G).

Every prompt that did not resolve with confidence is stored with its context, the choices shown and the one the
user tapped. A tapped choice becomes this install's own memory (the same words next time rank that skill
higher). Nothing here is ever added to the shared synonym registry automatically: `eval/review_failed_prompts.py`
writes a review file for a human (Hindi / Hinglish additions need a native speaker's yes).

Local only. A server upload, if ever added, must be opt-in and anonymised (no project ids, no file names).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .tools.fuzzy import FILLER, canonical_words


def key(prompt: str) -> str:
    """The prompt's meaning words in order — the same request typed slightly differently gets the same key."""
    return " ".join(w for w in canonical_words(prompt) if w not in FILLER)[:200]


class UnmetLog:
    def __init__(self, db: Any) -> None:
        self.db = db
        db.execute("CREATE TABLE IF NOT EXISTS ambiguous_requests (id TEXT PRIMARY KEY, created_at TEXT, project_id "
                   "TEXT, prompt TEXT, key TEXT, context TEXT, decision TEXT, choices TEXT, picked TEXT)")

    def log(self, project_id: str | None, prompt: str, context: dict[str, Any], decision: str,
            choices: list[dict[str, Any]]) -> str:
        rid = "amb_" + uuid.uuid4().hex[:12]
        ctx = {k: v for k, v in context.items() if not k.startswith("_")}
        self.db.execute(
            "INSERT INTO ambiguous_requests(id, created_at, project_id, prompt, key, context, decision, choices, picked)"
            " VALUES (?,?,?,?,?,?,?,?,NULL)",
            (rid, datetime.now(timezone.utc).isoformat(timespec="seconds"), project_id, prompt[:500], key(prompt),
             json.dumps(ctx)[:4000], decision, json.dumps([c["id"] for c in choices])))
        return rid

    def pick(self, rid: str, choice_id: str) -> bool:
        row = self.db.one("SELECT id FROM ambiguous_requests WHERE id=?", (rid,))
        if row is None:
            return False
        self.db.execute("UPDATE ambiguous_requests SET picked=? WHERE id=?", (choice_id[:60], rid))
        return True

    def learned(self, prompt: str) -> dict[str, int]:
        """Skill → how often the user picked it for these same words."""
        rows = self.db.all("SELECT picked FROM ambiguous_requests WHERE key=? AND picked IS NOT NULL", (key(prompt),))
        out: dict[str, int] = {}
        for r in rows:
            out[r["picked"]] = out.get(r["picked"], 0) + 1
        return out

    def recent(self, limit: int = 500) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.all(
            "SELECT * FROM ambiguous_requests ORDER BY created_at DESC LIMIT ?", (limit,))]
