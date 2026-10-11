"""test200 runner — the user and the judge. Real API (FastAPI app in-process, real job queue, real FFmpeg) on an
ISOLATED data dir per case (tools/test200/work/<case>), never the real projects.

python tools/test200/run.py --wave 1            # the cases tagged wave 1
python tools/test200/run.py --case S001          # one case
python tools/test200/run.py --cat M              # a category
python tools/test200/run.py --failed             # only cases whose last result was not a pass
python tools/test200/run.py --record U01 pass "evidence..."   # a UI case run by hand in the browser pane

Resumable: tools/test200/state.json keeps every finished case; a crash / restart continues with the next one.
A failing case is rerun twice before it is called FAIL (a pass on a rerun = FLAKY).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(HERE))
os.environ.setdefault("CUTMIND_TRANSLATOR", "off")
os.environ.setdefault("LLM_PROVIDER", "rules")
os.environ.setdefault("RATE_LIMIT_PER_MIN", "0")

import yaml  # noqa: E402

import judge as J  # noqa: E402
import measure as M  # noqa: E402

WORK = HERE / "work"
STATE = HERE / "state.json"
RESULTS = HERE / "results.jsonl"
CSV = HERE / "results.csv"
PROGRESS = HERE / "progress.md"
CASES = HERE / "cases.yaml"
LOCK = HERE / "cases.lock.json"
JOB_TIMEOUT = 600


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class App:
    """One isolated CutMind (its own data dir) driven through its HTTP API."""

    def __init__(self, data: Path) -> None:
        from fastapi.testclient import TestClient

        from cutmind.api import create_app
        from cutmind.config import Settings

        s = Settings()
        s.planner_mode = "mock"
        s.data_dir = data
        s.music_dir = ROOT / "backend" / "assets" / "music"
        s.enable_transcription = True
        self.tc = TestClient(create_app(s))
        self.tc.__enter__()

    def close(self) -> None:
        self.tc.__exit__(None, None, None)

    def req(self, method: str, path: str, **kw: Any) -> tuple[int, Any]:
        r = self.tc.request(method, path, **kw)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.content

    def wait(self, job_id: str) -> dict:
        end = time.monotonic() + JOB_TIMEOUT
        while time.monotonic() < end:
            _, j = self.req("GET", f"/jobs/{job_id}")
            if j.get("status") in ("done", "failed"):
                return j
            time.sleep(0.7)
        return {"status": "timeout", "id": job_id, "error": f"no result in {JOB_TIMEOUT}s"}

    def versions(self, pid: str) -> int:
        s, v = self.req("GET", f"/projects/{pid}/versions")
        return len(v.get("versions", v) if isinstance(v, dict) else v) if s == 200 else 0

    def plan(self, pid: str) -> dict | None:
        s, p = self.req("GET", f"/projects/{pid}/plan")
        return p if s == 200 else None

    def output(self, pid: str, dest: Path) -> str | None:
        r = self.tc.get(f"/projects/{pid}/output")
        if r.status_code != 200:
            return None
        dest.write_bytes(r.content)
        return str(dest)


def do_turn(app: App, pid: str, turn: dict, last_job: dict | None) -> dict:
    """One user action through the user's entry point; returns {say, status, body, job}."""
    say = turn.get("say", "")
    if "choose" in turn:
        jid = (last_job or {}).get("id", "")
        s, b = app.req("POST", f"/jobs/{jid}/choose", json={"variant": turn["choose"]})
        return {"say": f"[Use this #{turn['choose']}]", "status": s, "body": b, "job": None}
    if turn.get("undo") or turn.get("redo"):
        op = "undo" if turn.get("undo") else "redo"
        s, b = app.req("POST", f"/projects/{pid}/{op}")
        return {"say": f"[{op}]", "status": s, "body": b, "job": None}
    if "chip" in turn:  # the user taps a chip the app offered (resolver choice / alternative): /tools with its calls
        prev = turn.get("_prev_body") or {}
        chips = ((prev.get("error") or {}).get("details") or {}).get("choices") or prev.get("alternatives") or []
        if not chips:
            return {"say": "[tap chip]", "status": 0, "body": {"error": "no chip was offered"}, "job": None}
        ch = chips[min(turn["chip"], len(chips) - 1)]
        s, b = app.req("POST", f"/projects/{pid}/tools", json={"calls": ch["calls"], "prompt": ch.get("label", "")})
        job = app.wait(b["job_id"]) if s == 202 else None
        return {"say": f"[tap chip {ch.get('label')}]", "status": s, "body": b, "job": job}
    if "tools" in turn:  # a one-tap button that sends fixed skill calls (e.g. the "Sab jod do" chip)
        s, b = app.req("POST", f"/projects/{pid}/tools", json={"calls": turn["tools"], "prompt": say})
        job = app.wait(b["job_id"]) if s == 202 else None
        return {"say": say or "[tap]", "status": s, "body": b, "job": job}
    if "manual" in turn:  # an Effects / Text panel button
        s, b = app.req("POST", f"/projects/{pid}/manual", json={"ops": turn["manual"]})
        job = app.wait(b["job_id"]) if s == 202 else None
        return {"say": say or "[panel]", "status": s, "body": b, "job": job}
    body = {"prompt": say}
    for k in ("at", "playhead", "variations", "style", "aspect_ratio"):
        if k in turn:
            body[k] = turn[k]
    s, b = app.req("POST", f"/projects/{pid}/edit", json=body)
    job = app.wait(b["job_id"]) if s == 202 and isinstance(b, dict) and b.get("job_id") else None
    return {"say": say, "status": s, "body": b, "job": job}


def final_state(c: J.Ctx, exp: dict) -> tuple[str, str]:
    """APPLIED / NOT_NEEDED / COULD_NOT / NOT_UNDERSTOOD / FAILED for one expected instruction."""
    t = c.last
    b = t.get("body") or {}
    code = (b.get("error") or {}).get("code") if isinstance(b, dict) and isinstance(b.get("error"), dict) else None
    allowed = exp.get("states", ["APPLIED"])
    if code in ("not_understood", "choose") and t.get("status") == 422:
        chips = ((b.get("error") or {}).get("details") or {}).get("choices") or []
        st = "NOT_UNDERSTOOD"
        return (st if st in allowed and (chips or not exp.get("need_chips", True)) else "FAILED",
                f"422 {code}, {len(chips)} chips: {(b.get('error') or {}).get('message', '')[:90]}")
    if code == "non_edit":
        return ("NO_EDIT" if "NO_EDIT" in allowed else "FAILED"), "answered without an edit"
    job = t.get("job") or {}
    if job.get("status") in ("failed", "timeout"):
        return ("COULD_NOT" if "COULD_NOT" in allowed and job.get("error") else "FAILED"), f"job {job.get('status')}: {job.get('error')}"
    results = [(a, *J.run_assert(c, a)) for a in exp.get("any", [])]
    if any(ok for _a, ok, _d in results):
        a, _ok, d = next(r for r in results if r[1])
        return "APPLIED", f"{a['kind']}: {d}"
    detail = " | ".join(f"{a['kind']}: {d}" for a, _ok, d in results)
    if "NOT_NEEDED" in allowed:
        ex = job.get("explain") or {}
        said = " ".join(map(str, [ex.get("summary"), *(ex.get("warnings") or []), *(ex.get("changed") or [])])).lower()
        if any(w in said for w in ("not needed", "nothing to", "already", "no silence", "no speech", "nothing changed")):
            return "NOT_NEEDED", detail + " (the app said why)"
    return "FAILED", detail or "no assertion"


def run_case(case: dict, man: dict) -> dict:
    t0 = time.perf_counter()
    work = WORK / case["id"]
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    fx = {**man[case["fixture"]], "_extra_paths": [str(ROOT / man[e]["path"]) for e in case.get("extra_fixtures", [])]}
    src = str(ROOT / fx["path"])
    src_hash = sha(Path(src))
    app = App(work / "data")
    out: dict[str, Any] = {"id": case["id"], "cat": case["cat"], "fixture": case["fixture"]}
    try:
        _, p = app.req("POST", "/projects", json={"name": case["id"]})
        pid = p["id"]
        files = [("files", (Path(src).name, Path(src).read_bytes(), "video/mp4"))]
        for extra in case.get("extra_fixtures", []):  # more clips (transitions, reorder, picture-in-picture …)
            e = ROOT / man[extra]["path"]
            files.append(("files", (e.name, e.read_bytes(), "video/mp4")))
        s, up = app.req("POST", f"/projects/{pid}/clips", files=files)
        out["upload"] = s
        turns: list[dict] = []
        if case.get("upload_expect"):
            ok = s in case["upload_expect"]
            out.update(passed=ok, states=[{"instr": "upload", "state": "OK" if ok else "FAILED", "detail": str(up)[:200]}],
                       seconds=round(time.perf_counter() - t0, 1))
            return out
        if s != 201:
            raise RuntimeError(f"upload failed {s}: {str(up)[:200]}")
        last_job = None
        if case.get("base") == "chip":
            r = do_turn(app, pid, {"tools": [{"id": "merge_clips"}], "say": "Sab jod do"}, None)
            if (r["job"] or {}).get("status") != "done":
                raise RuntimeError(f"base version failed: {(r['job'] or {}).get('error')}")
            last_job = r["job"]
        prev_out, prev_plan = None, None
        cur_out = app.output(pid, work / "v_base.mp4")
        cur_plan = app.plan(pid)
        v_before = app.versions(pid)
        prev_body = None
        for i, turn in enumerate(case["turns"]):
            prev_out, prev_plan = cur_out, cur_plan
            v_before = app.versions(pid)
            turn = {**turn, "_prev_body": prev_body}
            r = do_turn(app, pid, turn, last_job)
            if r.get("job") and r["job"].get("status") == "done":
                last_job = r["job"]
            cur_out = app.output(pid, work / f"v{i + 1}.mp4") or cur_out
            cur_plan = app.plan(pid)
            if prev_out and cur_out and prev_out != cur_out:
                try:
                    r["measured_change"] = M.frame_diff(M.frame(prev_out, 1.0), M.frame(cur_out, 1.0))
                except Exception:  # noqa: BLE001
                    r["measured_change"] = 0.0
            prev_body = r["body"] if isinstance(r["body"], dict) else None
            turns.append({k: v for k, v in r.items() if k != "_prev_body"})
        first_out = str(work / "v_base.mp4") if (work / "v_base.mp4").exists() else None
        ctx = J.Ctx(src=src, out=cur_out, prev=(prev_out if case.get("compare", "prev") == "prev" else first_out),
                    plan=cur_plan, prev_plan=prev_plan, fx=fx, turns=turns, versions_before=v_before,
                    versions_after=app.versions(pid))
        if case.get("compare") == "source":
            ctx.prev = src
        states = []
        for exp in case.get("expect", []):
            st, detail = final_state(ctx, exp)
            states.append({"instr": exp["instr"], "state": st, "detail": detail[:300]})
        generic = []
        if cur_out and case.get("decodes", True) and ctx.turns and (ctx.last.get("job") or {}).get("status") == "done":
            ok, err = M.decodes(cur_out)
            if not ok:
                generic.append(f"output does not decode: {err}")
            i = M.info(cur_out)
            if i.get("has_audio") and i.get("audio_duration") and abs(i["audio_duration"] - i["video_duration"]) > 0.3:
                generic.append(f"audio {i['audio_duration']:.2f}s vs video {i['video_duration']:.2f}s")
        for u in case.get("must", []):  # extra must-hold checks (e.g. unchanged length, no new version)
            ok, d = J.run_assert(ctx, u)
            if not ok:
                generic.append(f"{u['kind']}: {d}")
        generic += J.honesty(ctx)
        if sha(Path(src)) != src_hash:
            generic.append("the original fixture file changed")
        passed = all(s_["state"] != "FAILED" for s_ in states) and not generic
        out.update(passed=passed, states=states, generic=generic,
                   turns=[{"say": t["say"], "status": t["status"],
                           "decision": (t["body"] or {}).get("decision") if isinstance(t["body"], dict) else None,
                           "error": ((t["body"] or {}).get("error") or {}).get("message", "")[:160]
                           if isinstance(t["body"], dict) and isinstance((t["body"] or {}).get("error"), dict) else "",
                           "job": (t["job"] or {}).get("status") if t.get("job") else None,
                           "job_error": (t["job"] or {}).get("error") if t.get("job") else None,
                           "explain": ((t["job"] or {}).get("explain") or {}).get("summary") if t.get("job") else None,
                           "warnings": ((t["job"] or {}).get("explain") or {}).get("warnings") if t.get("job") else None}
                          for t in turns])
    except Exception as exc:  # noqa: BLE001 — the runner never stops on one case
        out.update(passed=False, crash=f"{type(exc).__name__}: {exc}", trace=traceback.format_exc()[-1500:])
    finally:
        try:
            app.close()
        except Exception:  # noqa: BLE001
            pass
    out["seconds"] = round(time.perf_counter() - t0, 1)
    return out


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"done": {}}


def save_state(st: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE)


def write_reports(st: dict, cases: list[dict]) -> None:
    rows = [st["done"][c["id"]] for c in cases if c["id"] in st["done"]]
    with CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "cat", "fixture", "result", "seconds", "states", "problems"])
        for r in rows:
            w.writerow([r["id"], r["cat"], r["fixture"], r.get("result"), r.get("seconds"),
                        "; ".join(f"{s['instr']}={s['state']}" for s in r.get("states", [])),
                        "; ".join(r.get("generic", []) + ([r["crash"]] if r.get("crash") else []))[:400]])
    by: dict[str, list[int]] = {}
    for r in rows:
        by.setdefault(r["cat"], [0, 0])
        by[r["cat"]][0] += r.get("result") in ("PASS", "FLAKY")
        by[r["cat"]][1] += 1
    lines = [f"# test200 progress ({time.strftime('%Y-%m-%d %H:%M')})", "",
             f"done {len(rows)} / {len(cases)} · pass {sum(v[0] for v in by.values())}", "",
             "| cat | pass / run |", "|---|---|"] + [f"| {k} | {v[0]} / {v[1]} |" for k, v in sorted(by.items())]
    fails = [r for r in rows if r.get("result") not in ("PASS", "FLAKY")]
    if fails:
        lines += ["", "## not passing", ""] + [
            f"- **{r['id']}** ({r['fixture']}): " + "; ".join(
                [f"{s['instr']}={s['state']} ({s['detail'][:120]})" for s in r.get("states", []) if s["state"] == "FAILED"]
                + r.get("generic", []) + ([r["crash"][:160]] if r.get("crash") else [])) for r in fails]
    PROGRESS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles are cp1252
    except AttributeError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--case")
    ap.add_argument("--cat")
    ap.add_argument("--wave", type=int)
    ap.add_argument("--failed", action="store_true")
    ap.add_argument("--again", action="store_true", help="rerun even if already done")
    ap.add_argument("--no-retry", action="store_true")
    ap.add_argument("--record", nargs=3, metavar=("ID", "RESULT", "EVIDENCE"))
    a = ap.parse_args()
    if LOCK.exists() and json.loads(LOCK.read_text())["sha256"] != sha(CASES):
        print("cases.yaml changed after it was frozen — log the change in docs/test200/ORACLE_CHANGES.md and refreeze")
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))["cases"]
    man = json.loads((HERE / "fixtures" / "manifest.json").read_text(encoding="utf-8"))
    st = load_state()
    if a.record:
        cid, res, ev = a.record
        case = next(c for c in cases if c["id"] == cid)
        st["done"][cid] = {"id": cid, "cat": case["cat"], "fixture": case["fixture"], "result": res.upper(),
                           "states": [{"instr": "ui", "state": "APPLIED" if res.lower() == "pass" else "FAILED",
                                       "detail": ev}], "generic": [], "seconds": 0, "by_hand": True}
        save_state(st)
        write_reports(st, cases)
        return
    pick = [c for c in cases if (not a.case or c["id"] == a.case) and (not a.cat or c["cat"] == a.cat)
            and (not a.wave or c.get("wave") == a.wave) and c.get("driver", "api") == "api"]
    if a.failed:
        pick = [c for c in pick if st["done"].get(c["id"], {}).get("result") not in ("PASS", "FLAKY")]
    elif not a.again and not a.case:
        pick = [c for c in pick if c["id"] not in st["done"]]
    for n, case in enumerate(pick, 1):
        print(f"[{n}/{len(pick)}] {case['id']} {case['cat']} {case['fixture']}: {case['turns'][0].get('say', '')[:60]}",
              flush=True)
        r = run_case(case, man)
        tries = 1
        while not r.get("passed") and not a.no_retry and tries < 3 and not r.get("deterministic_fail"):
            r2 = run_case(case, man)
            tries += 1
            if r2.get("passed"):
                r = {**r2, "flaky_after": tries}
                break
            r = r2
        r["result"] = "PASS" if r.get("passed") and tries == 1 else "FLAKY" if r.get("passed") else "FAIL"
        r["tries"] = tries
        with RESULTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({**r, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False) + "\n")
        st["done"][case["id"]] = r
        save_state(st)
        write_reports(st, cases)
        print(f"    → {r['result']} in {r['seconds']}s "
              + "; ".join(f"{s['instr']}={s['state']}" for s in r.get("states", [])) + (" CRASH " + r["crash"] if r.get("crash") else "")
              + (" | " + "; ".join(r.get("generic", [])) if r.get("generic") else ""), flush=True)
        if not os.environ.get("TEST200_KEEP"):
            shutil.rmtree(WORK / case["id"], ignore_errors=True)


if __name__ == "__main__":
    main()
