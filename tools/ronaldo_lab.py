"""Ronaldo lab: many different prompts on a COPY of the user's 'ronaldo' clip + song, THROUGH cutmind-mcp test mode
(run_prompt only, like typing in the app). Each step: what the app said, and the judge's own measurements of the
rendered file. Writes ~/CutMind/ronaldo_lab/results.jsonl. Never touches the real project.

    backend/.venv/Scripts/python.exe tools/ronaldo_lab.py [--only 3,5] [--fresh]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "test200"))
LAB = Path.home() / "CutMind" / "ronaldo_lab"
FIX = Path.home() / "CutMind" / "test_fixtures" / "ronaldo"
os.environ["CUTMIND_FIXTURES_DIR"] = str(FIX.parent)
os.environ.setdefault("CUTMIND_TRANSLATOR", "off")
os.environ.setdefault("LLM_PROVIDER", "rules")
os.environ.setdefault("RATE_LIMIT_PER_MIN", "0")

import logging  # noqa: E402

logging.getLogger("httpx").setLevel(logging.WARNING)

import measure as M  # noqa: E402
from run import McpApp  # noqa: E402

REAL = ROOT / "data" / "projects" / "prj_7c02987dd04b"

# (id, what the user types, chain: "base" = start from a fresh project / "keep" = continue the same project)
PROMPTS: list[tuple[str, str, str]] = [
    ("R01", "mast sa edit kar do", "base"),
    ("R02", "beat pe edit karo", "keep"),
    ("R03", "thoda warm karo", "keep"),
    ("R04", "2 se 4 second black and white karo", "keep"),
    ("R05", "black and white hata do", "keep"),
    ("R06", "end me fade to black karo", "keep"),
    ("R07", "shuru me title daalo 'GOAT'", "keep"),
    ("R08", "undo", "keep"),
    ("R09", "gaana thoda dheere karo", "keep"),
    ("R10", "slow motion lagao 5 se 7 second", "keep"),
    ("R11", "sab effects hata do normal kar do", "keep"),
    ("R12", "video ko 10 second ka karo", "keep"),
    ("R13", "vintage look do", "keep"),
    ("R14", "asdfgh qwerty", "keep"),
    ("R15", "captions laga do", "keep"),
    ("R16", "isko 16:9 kar do", "keep"),
    ("R17", "make it brighter", "keep"),
    ("R18", "thoda zom karo", "keep"),
    ("R19", "black and white mat karna, bas contrast badhao", "base"),
    ("R20", "make it look like a pro football edit with flash on beats", "base"),
    ("R21", "glitch effect daalo beat pe aur end me fade", "base"),
    ("R22", "colour ko cinematic teal orange karo aur vignette lagao", "base"),
    ("R23", "pehle 3 sec zoom karo", "base"),
    ("R24", "velocity edit bana do song pe", "base"),
    ("R25", "shake hatao lekin colour rehne do", "keep"),
]


def measure(out: str, src: str) -> dict:
    i = M.info(out)
    if not i.get("ok"):
        return {"ok": False}
    d = i["duration"]
    ts = [d * k for k in (0.1, 0.3, 0.5, 0.7, 0.9)]
    fr = []
    for t in ts:
        try:
            fr.append(M.stats(M.frame(out, t)))
        except Exception:  # noqa: BLE001
            pass
    avg = {k: round(sum(f[k] for f in fr) / max(1, len(fr)), 1) for k in ("warmth", "luma", "contrast", "sat")}
    sat_t = [round(f["sat"], 1) for f in fr]
    try:
        end_luma = round(M.stats(M.frame(out, max(0.0, d - 0.08)))["luma"], 1)
    except Exception:  # noqa: BLE001
        end_luma = None
    return {"ok": True, "dur": round(d, 2), "w": i["width"], "h": i["height"], "audio": i["has_audio"],
            "cuts": len(M.cuts(out)), "lufs": round(M.lufs(out), 1) if i["has_audio"] else None,
            **avg, "sat_t": sat_t, "end_luma": end_luma}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()
    FIX.mkdir(parents=True, exist_ok=True)
    src = FIX / "ronaldo.mp4"
    song = FIX / "montagem.m4a"
    if not src.exists():
        shutil.copy2(REAL / "clips" / "src_e36f6248a02d.mp4", src)
        shutil.copy2(REAL / "music" / "montagem.m4a", song)
    if a.fresh and LAB.exists():
        shutil.rmtree(LAB)
    LAB.mkdir(parents=True, exist_ok=True)
    only = set(a.only.split(",")) if a.only else None
    app = McpApp(LAB / "data")
    res_f = LAB / "results.jsonl"
    pid = None
    base = {"src": M.stats(M.frame(str(src), 8.0))}
    print("source", base, flush=True)
    try:
        for cid, text, chain in PROMPTS:
            if only and cid not in only:
                continue
            if chain == "base" or pid is None or only:
                ok, p = app.tool("create_project", {"name": f"ronaldo lab {cid}"})
                pid = p["project_id"]
                app.tool("import_clip", {"project_id": pid, "path": str(src)})
                app.tool("import_clip", {"project_id": pid, "path": str(song)})
            t0 = time.time()
            if text == "undo":
                ok, d = app.tool("undo", {"project_id": pid})
                r = {"undo": d}
            else:
                ok, d = app.tool("run_prompt", {"project_id": pid, "text": text})
                r = d if ok else {"tool_error": d}
            dt = round(time.time() - t0, 1)
            out = app.output(pid, LAB / f"{cid}.mp4")
            plan = app.plan(pid) or {}
            m = measure(out, str(src)) if out else {"ok": False}
            job = (r.get("job") or {}) if isinstance(r, dict) else {}
            rec = {"id": cid, "say": text, "secs": dt, "http": r.get("http") if isinstance(r, dict) else None,
                   "route": job.get("route"), "status": job.get("status"), "error": job.get("error"),
                   "message": (job.get("message") or {}), "skills": job.get("skills"),
                   "app_msg": r.get("message") if isinstance(r, dict) else None,
                   "chips": r.get("chips") if isinstance(r, dict) else None,
                   "said": r.get("said") if isinstance(r, dict) else None,
                   "failed_checks": job.get("failed_checks"),
                   "effects": [e.get("name") or e.get("type") for e in (plan.get("effects") or [])][:12],
                   "look": plan.get("look") or plan.get("color"), "measure": m, "raw": r if not job else None}
            with res_f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            msg = rec["message"].get("summary") if rec["message"] else rec["app_msg"]
            print(f"{cid} [{dt}s] {text!r} -> route={rec['route']} st={rec['status']} msg={str(msg)[:160]!r}\n"
                  f"     measure={m}", flush=True)
    finally:
        app.close()


if __name__ == "__main__":
    main()
