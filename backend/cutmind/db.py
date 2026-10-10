"""SQLite persistence: projects, clips, jobs, agents, runs, scores, lessons, feedback."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename TEXT NOT NULL, path TEXT NOT NULL, duration REAL, width INTEGER, height INTEGER,
    fps REAL, has_audio INTEGER, size_bytes INTEGER, position INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    prompt TEXT NOT NULL, options TEXT, status TEXT NOT NULL, state TEXT, plan TEXT,
    output_path TEXT, error TEXT, match_percent REAL, created_at TEXT NOT NULL, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS agents (
    name TEXT PRIMARY KEY, role TEXT NOT NULL, total_points INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, agent TEXT NOT NULL,
    attempt INTEGER NOT NULL, prompt TEXT, output TEXT, mode TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, agent TEXT NOT NULL,
    attempt INTEGER NOT NULL, check_name TEXT NOT NULL, points INTEGER NOT NULL, reason TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT NOT NULL, check_name TEXT NOT NULL,
    text TEXT NOT NULL, job_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, rating TEXT NOT NULL,
    comment TEXT, agent TEXT, points INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scores_agent ON scores(agent);
CREATE INDEX IF NOT EXISTS idx_lessons_agent ON lessons(agent, created_at);
"""

AGENT_ROLES = {
    "director": "CEO: understands the prompt, plans, merges and retries",
    "analyzer": "Measures clips: metadata, scenes, silence, speech, loudness, beats",
    "cutter": "Selects, trims and orders clips; removes silence; fits duration",
    "audio": "Music, levels, ducking and voice cleanup",
    "color": "Color grade and consistent look",
    "effects": "Captions, titles, transitions, motion effects, reframing",
    "reviewer": "Checks the render against the prompt and scores agents",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Database:
    """Small thread-safe wrapper; one connection per call keeps it simple and safe."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self.conn() as c:
            c.executescript(SCHEMA)
            for name, role in AGENT_ROLES.items():
                c.execute("INSERT OR IGNORE INTO agents(name, role) VALUES (?, ?)", (name, role))

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            c = sqlite3.connect(self.path, timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON")
            try:
                yield c
                c.commit()
            finally:
                c.close()

    # ---- generic helpers ----------------------------------------------------------------------
    def one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self.conn() as c:
            row = c.execute(sql, params).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def execute(self, sql: str, params: tuple = ()) -> int:
        with self.conn() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid or 0

    # ---- projects & clips -----------------------------------------------------------------------
    def create_project(self, name: str) -> dict[str, Any]:
        pid = new_id("prj")
        self.execute("INSERT INTO projects(id, name, created_at) VALUES (?, ?, ?)", (pid, name, now_iso()))
        return self.one("SELECT * FROM projects WHERE id=?", (pid,)) or {}

    def get_project(self, pid: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM projects WHERE id=?", (pid,))

    def list_projects(self) -> list[dict[str, Any]]:
        return self.all("SELECT * FROM projects ORDER BY created_at DESC")

    def delete_project(self, pid: str) -> None:
        self.execute("DELETE FROM projects WHERE id=?", (pid,))

    def add_clip(self, project_id: str, filename: str, path: str, meta: dict[str, Any]) -> dict[str, Any]:
        cid = new_id("clp")
        pos = (self.one("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM clips WHERE project_id=?", (project_id,)) or {"p": 0})["p"]
        self.execute(
            "INSERT INTO clips(id, project_id, filename, path, duration, width, height, fps, has_audio, size_bytes, position, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, project_id, filename, path, meta["duration"], meta["width"], meta["height"], meta["fps"],
             int(meta["has_audio"]), meta["size_bytes"], pos, now_iso()),
        )
        return self.one("SELECT * FROM clips WHERE id=?", (cid,)) or {}

    def list_clips(self, project_id: str) -> list[dict[str, Any]]:
        return self.all("SELECT * FROM clips WHERE project_id=? ORDER BY position", (project_id,))

    def get_clip(self, clip_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM clips WHERE id=?", (clip_id,))

    def delete_clip(self, clip_id: str) -> None:
        self.execute("DELETE FROM clips WHERE id=?", (clip_id,))

    # ---- jobs -----------------------------------------------------------------------------------
    def create_job(self, project_id: str, prompt: str, options: dict[str, Any]) -> str:
        jid = new_id("job")
        self.execute(
            "INSERT INTO jobs(id, project_id, prompt, options, status, created_at) VALUES (?,?,?,?,?,?)",
            (jid, project_id, prompt, json.dumps(options), "queued", now_iso()),
        )
        return jid

    def update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        vals = tuple(json.dumps(v) if isinstance(v, (dict, list)) else v for v in fields.values())
        self.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*vals, job_id))

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM jobs WHERE id=?", (job_id,))

    def last_job(self, project_id: str, status: str | None = None) -> dict[str, Any] | None:
        if status:
            return self.one("SELECT * FROM jobs WHERE project_id=? AND status=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (project_id, status))
        return self.one("SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (project_id,))

    # ---- agents, runs, scores, lessons --------------------------------------------------------
    def record_run(self, job_id: str, agent: str, attempt: int, prompt: str, output: Any, mode: str) -> None:
        self.execute(
            "INSERT INTO runs(job_id, agent, attempt, prompt, output, mode, created_at) VALUES (?,?,?,?,?,?,?)",
            (job_id, agent, attempt, prompt, json.dumps(output, default=str)[:20000], mode, now_iso()),
        )

    def add_score(self, job_id: str, agent: str, attempt: int, check: str, points: int, reason: str) -> None:
        self.execute(
            "INSERT INTO scores(job_id, agent, attempt, check_name, points, reason, created_at) VALUES (?,?,?,?,?,?,?)",
            (job_id, agent, attempt, check, points, reason, now_iso()),
        )
        if not check.startswith("_"):  # internal rows (e.g. _final_score) don't change the leaderboard
            self.execute("UPDATE agents SET total_points = total_points + ? WHERE name=?", (points, agent))

    def add_lesson(self, agent: str, check: str, text: str, job_id: str | None) -> None:
        self.execute(
            "INSERT INTO lessons(agent, check_name, text, job_id, created_at) VALUES (?,?,?,?,?)",
            (agent, check, text, job_id, now_iso()),
        )

    def recent_lessons(self, agent: str, limit: int = 5) -> list[dict[str, Any]]:
        """Most recent lesson per check (deduplicated), newest first."""
        return self.all(
            "SELECT l.text, l.check_name, l.created_at FROM lessons l JOIN ("
            "  SELECT check_name, MAX(id) AS mid FROM lessons WHERE agent=? GROUP BY check_name"
            ") x ON l.id = x.mid ORDER BY l.id DESC LIMIT ?",
            (agent, limit),
        )

    def add_feedback(self, job_id: str, rating: str, comment: str | None, agent: str | None, points: int) -> None:
        self.execute(
            "INSERT INTO feedback(job_id, rating, comment, agent, points, created_at) VALUES (?,?,?,?,?,?)",
            (job_id, rating, comment, agent, points, now_iso()),
        )

    def scoreboard(self) -> list[dict[str, Any]]:
        agents = self.all("SELECT name, role, total_points FROM agents")
        out = []
        for a in agents:
            stats = self.one(
                "SELECT COUNT(DISTINCT job_id) AS runs FROM scores WHERE agent=?", (a["name"],)
            ) or {"runs": 0}
            # avg_score = average per-job final percentage (stored as check '_final_score')
            avg = self.one(
                "SELECT AVG(points) AS avg FROM scores WHERE agent=? AND check_name='_final_score'", (a["name"],)
            )
            last_job = self.one(
                "SELECT job_id FROM scores WHERE agent=? AND check_name != '_final_score' ORDER BY id DESC LIMIT 1", (a["name"],)
            )
            last_delta = 0
            if last_job:
                row = self.one(
                    "SELECT COALESCE(SUM(points),0) AS d FROM scores WHERE agent=? AND job_id=? AND check_name != '_final_score'",
                    (a["name"], last_job["job_id"]),
                )
                last_delta = int(row["d"]) if row else 0
            out.append({
                "name": a["name"], "role": a["role"], "total_points": int(a["total_points"]),
                "runs": int(stats["runs"]), "avg_score": round(avg["avg"], 1) if avg and avg["avg"] is not None else None,
                "last_delta": last_delta,
                "recent_lessons": [{"text": lsn["text"], "created_at": lsn["created_at"]} for lsn in self.recent_lessons(a["name"], 3)],
            })
        out.sort(key=lambda r: r["total_points"], reverse=True)
        return out
