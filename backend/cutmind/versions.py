"""Version history of a project's edit: every finished job is a version (its plan + its own output file, kept).
Restore / undo / redo never re-render: they make a NEW version that copies an old one's plan and output, so "the
newest finished job is the current edit" stays true everywhere (base plan for hand edits, memory, the app).

Also: what changed between two versions in plain words (explain-back after every edit, and compare v3 vs v7), and the
duration invariant (an edit that did not ask for another length must not change it by more than 2 %).
"""

from __future__ import annotations

import re

import json
import shutil
from pathlib import Path
from typing import Any

from .db import Database, new_id, now_iso
from .plan import EditPlan

# intent fields that legitimately change the length of the edit
# decisions that explain why an ask could not be done on this footage (shown when nothing changed)
# (only the ones about THIS message: an old sticker ask must not explain why a zoom comment changed nothing)
CANT_SKILLS = {"word_stickers_none": r"sticker|emoji|animation|icon", "captions_none": r"caption|subtitle|likh"}

LENGTH_FIELDS = ("target_duration", "length_change", "pace_change", "slow_motion", "slow_end", "speed_moves",
                 "remove_silence", "remove_fillers", "remove_idle", "drop_clips", "transition", "fast_cuts",
                 "reverse_playback", "cut_length", "auto")


def versions(db: Database, project_id: str) -> list[dict[str, Any]]:
    rows = db.all("SELECT id, prompt, status, created_at, match_percent, plan, options FROM jobs WHERE project_id=? "
                  "AND status='done' AND plan IS NOT NULL ORDER BY created_at, rowid", (project_id,))
    out = []
    for n, r in enumerate(rows, 1):
        opts = json.loads(r["options"] or "{}") if r.get("options") else {}
        try:
            dur = round(EditPlan.model_validate(json.loads(r["plan"])).total_duration(), 2)
        except Exception:  # noqa: BLE001 — an old plan from an earlier schema still lists
            dur = None
        kind = "restore" if opts.get("restored_from") else "manual" if opts.get("manual") else "ai"
        out.append({"n": n, "job_id": r["id"], "prompt": r["prompt"], "created_at": r["created_at"],
                    "duration": dur, "match_percent": r["match_percent"], "kind": kind,
                    "restored_from": opts.get("restored_from"), "replaced": opts.get("replaced")})
    if out:
        out[-1]["current"] = True
    return out


def restore(db: Database, project_dir: Path, project_id: str, job_id: str, memory: Any, label: str = "") -> dict[str, Any]:
    """A new version equal to `job_id` (plan + output file copied; its memory and hand-made changes become current)."""
    src = db.one("SELECT * FROM jobs WHERE id=? AND project_id=? AND status='done'", (job_id, project_id))
    if not src or not src.get("plan"):
        raise ValueError("That version does not exist (or did not finish).")
    cur = versions(db, project_id)
    replaced = cur[-1]["job_id"] if cur else None
    new = new_id("job")
    out_dir = project_dir / "output"
    old_file = Path(src["output_path"]) if src.get("output_path") else out_dir / f"{job_id}.mp4"
    new_file = out_dir / f"{new}.mp4"
    if old_file.exists():
        shutil.copyfile(old_file, new_file)
    n_old = next((v["n"] for v in cur if v["job_id"] == job_id), "?")
    prompt = label or f"Restore v{n_old}"
    state = json.loads(src["state"] or "{}") if src.get("state") else {}
    state.update({"id": new, "prompt": prompt, "status": "done", "events": [], "thoughts": [], "timeline": {},
                  "finished_at": now_iso(), "explain": {"summary": f"Back to v{n_old} ({src['prompt'][:60]})."}})
    options = {"restored_from": job_id, "replaced": replaced}
    db.execute("INSERT INTO jobs(id, project_id, prompt, options, status, created_at, plan, output_path, state, "
               "match_percent, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               (new, project_id, prompt, json.dumps(options), "done", now_iso(), src["plan"], str(new_file),
                json.dumps(state), src.get("match_percent"), now_iso()))
    if memory is not None:
        row = db.one("SELECT intent, delivered FROM edit_memory WHERE job_id=?", (job_id,))
        if row:  # follow-up messages continue from the restored edit
            memory.remember_edit(project_id, new, prompt, json.loads(row["intent"]), json.loads(row["delivered"]))
        # hand-made changes: those made up to the restored version
        memory.forget_manual(project_id)
        for m in db.all("SELECT id, options FROM jobs WHERE project_id=? AND status='done' AND created_at<=? "
                        "ORDER BY created_at", (project_id, src["created_at"])):
            ops = (json.loads(m["options"] or "{}") or {}).get("manual")
            if ops:
                memory.remember_manual(project_id, m["id"], ops)
    return {"job_id": new, "restored": job_id, "version": len(cur) + 1, "replaced": replaced}


def undo(db: Database, project_dir: Path, project_id: str, memory: Any) -> dict[str, Any]:
    cur = versions(db, project_id)
    if len(cur) < 2:
        raise ValueError("Nothing to undo yet.")
    # undoing an undo-restore goes one step further back, not forth
    target = cur[-2]
    last = cur[-1]
    if last["kind"] == "restore" and last.get("restored_from"):
        idx = next((i for i, v in enumerate(cur) if v["job_id"] == last["restored_from"]), None)
        if idx is not None and idx > 0:
            target = cur[idx - 1]
    return restore(db, project_dir, project_id, target["job_id"], memory, f"Undo (back to v{target['n']})")


def redo(db: Database, project_dir: Path, project_id: str, memory: Any) -> dict[str, Any]:
    cur = versions(db, project_id)
    last = cur[-1] if cur else None
    if not last or last["kind"] != "restore" or not last.get("replaced"):
        raise ValueError("Nothing to redo.")
    n = next((v["n"] for v in cur if v["job_id"] == last["replaced"]), "?")
    return restore(db, project_dir, project_id, last["replaced"], memory, f"Redo (v{n})")


# ---- what changed --------------------------------------------------------------------------------------------
def _effects(p: EditPlan) -> list[str]:
    return sorted({e.type for e in p.effects})


def _fx_spots(p: EditPlan) -> list[tuple[str, int, float]]:
    return sorted((e.type, e.target, round(e.strength, 2)) for e in p.effects)


def _texts(p: EditPlan) -> list[str]:
    return [t.text for t in p.text if t.kind in ("title", "text", "watermark")][:6]


def diff(a: EditPlan, b: EditPlan) -> dict[str, Any]:
    """Plain-language differences between two plans (a = before, b = after)."""
    changed, kept = [], []

    def item(name: str, before: Any, after: Any, fmt: Any = str) -> None:
        if before != after:
            changed.append(f"{name}: {fmt(before)} → {fmt(after)}")
        else:
            kept.append(name)

    def opt(x: Any) -> str:
        return "none" if x in (None, "", [], "none") else (", ".join(x) if isinstance(x, list) else str(x))

    cut_a = [(c.source, round(c.in_, 2), round(c.out, 2), c.speed) for c in a.ordered_clips()]
    cut_b = [(c.source, round(c.in_, 2), round(c.out, 2), c.speed) for c in b.ordered_clips()]
    if cut_a != cut_b:
        changed.append(f"cut: {len(cut_a)} → {len(cut_b)} shots")
    else:
        kept.append(f"cut ({len(cut_b)} shots)")
    item("colour", a.color.preset, b.color.preset, opt)
    item("music", a.audio.music, b.audio.music, opt)
    if a.audio.music and b.audio.music and a.audio.music == b.audio.music and a.audio.music_volume != b.audio.music_volume:
        changed.append(f"music level: {a.audio.music_volume:.2f} → {b.audio.music_volume:.2f}")
    item("video's own sound", a.audio.mute, b.audio.mute, lambda x: "muted" if x else "on")
    item("stickers", len(a.stickers), len(b.stickers))
    if _effects(a) == _effects(b) and _fx_spots(a) != _fx_spots(b):  # same kinds, now also at another moment
        changed.append("effects: " + ", ".join(sorted({t for t, *_ in set(_fx_spots(b)) - set(_fx_spots(a))}) or
                                                ["moved"]) + " at a moment")
    else:
        item("effects", _effects(a), _effects(b), opt)
    item("text", _texts(a), _texts(b), opt)
    caps_a, caps_b = sum(t.kind == "caption" for t in a.text), sum(t.kind == "caption" for t in b.text)
    item("captions", caps_a > 0, caps_b > 0, lambda x: "on" if x else "off")
    item("transitions", sorted({t.type for t in a.transitions}), sorted({t.type for t in b.transitions}), opt)
    item("shape", a.canvas.aspect_ratio, b.canvas.aspect_ratio)
    da, db_ = round(a.total_duration(), 2), round(b.total_duration(), 2)
    return {"changed": changed, "kept": kept, "duration_before": da, "duration_after": db_}


def next_suggestions(plan: EditPlan) -> list[str]:
    """2-3 tweaks a pro would offer next, from what this edit does not have yet (tap = send)."""
    s = []
    if not any(t.kind == "caption" for t in plan.text):
        s.append("captions laga do")
    if not plan.audio.music:
        s.append("upbeat music lagao")
    if plan.color.preset in (None, "none"):
        s.append("warm color karo")
    s += ["thoda fast karo", "best part pehle", "text bada karo"]
    return s[:3]


def _already(prompt: str) -> str:
    """Nothing changed and nothing was impossible: what was asked is already in the edit ("captions laga do" twice)."""
    from .intent import parse_intent

    asked = [r for r in parse_intent(prompt).recognized if not r.startswith(("auto edit", "travel/vlog"))] if prompt else []
    if asked:
        return "Already in your edit: " + ", ".join(asked[:4]) + " — so there was nothing to change."
    return "This ask did not change anything in this video."


def explain(before: EditPlan | None, after: EditPlan, intent: dict[str, Any] | None,
            prompt: str = "") -> dict[str, Any]:
    """After every edit: what changed, what stayed, the new length — and a warning when the length moved although
    the message did not ask for a different length (the duration invariant, ±2 %)."""
    if before is None:
        return {"summary": f"New edit, {after.total_duration():.1f}s.", "changed": [], "kept": [],
                "duration_before": None, "duration_after": round(after.total_duration(), 2), "warnings": [],
                "suggestions": next_suggestions(after)}
    d = diff(before, after)
    warnings = []
    asked_length = any((intent or {}).get(f) not in (None, False, [], 0) for f in LENGTH_FIELDS) or bool(
        (intent or {}).get("from_comment") and ((intent or {}).get("exclude_ranges") or any(
            t.get("effect") == "speed_ramp" for t in (intent or {}).get("timed_effects") or [])))
    if not asked_length and d["duration_before"] and abs(d["duration_after"] - d["duration_before"]) > \
            max(0.25, 0.02 * d["duration_before"]):
        warnings.append(f"length changed {d['duration_before']:.1f}s → {d['duration_after']:.1f}s although you "
                        "didn't ask for a different length")
    if not d["changed"]:
        # the message asked for something, but nothing could change: say WHY (never a silent "done")
        why = [f"{x.decision}: {x.reason}" for x in after.decisions
               if x.skill in CANT_SKILLS and re.search(CANT_SKILLS[x.skill], prompt, re.I)]
        warnings.append("Nothing changed. " + (" ".join(dict.fromkeys(why)) if why else
                                              _already(prompt)))
    ch = "; ".join(d["changed"]) if d["changed"] else "nothing visible"
    same = ", ".join(d["kept"][:5])
    summary = f"Changed: {ch}. Same as before: {same}. Length {d['duration_after']:.1f}s."
    return {"summary": summary, **d, "warnings": warnings, "suggestions": next_suggestions(after)}
