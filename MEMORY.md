# Memory

All local (SQLite in `data/cutmind.sqlite3`), no vector database, no cloud.

| Memory | Where | Used for |
|---|---|---|
| Edit history per project | `edit_memory` (cutmind/memory.py) | "same as before / pichli baar jaisa" repeats the last edit; summary shown to the Director |
| Preferences | derived from history + choices + ratings | "in my style / mera style" → favourite look; preferred aspect; disliked looks ranked last |
| Lessons | `lessons` table | every avoidable failed Reviewer check → a lesson for the owning agent |
| Scores | `scores`, `agents` tables | per-check points, per-agent totals (Scoreboard screen) |
| Caches | `data/projects/<id>/analysis/*.json`, `data/cache/beats_*.json`, proxies | never redo analysis / beat tracking |
| Checkpoints | `data/checkpoints.sqlite` | resume an interrupted job (LangGraph) |

**Relevant lessons only**: each agent receives at most 5 of its own lessons (newest per check), filtered to the checks that matter for this request (`lesson_applies`), not the whole
table. Footage limits (e.g. "nobody speaks in these clips") are not lessons — they would teach the agents the
wrong thing (`fixable: false` checks).

`GET /projects/{id}/memory` shows what is remembered; the studio's "CutMind remembers" card displays it.
