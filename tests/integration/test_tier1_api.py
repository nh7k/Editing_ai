"""Tier 1 through the API: prompt → tool calls → a new version; refusals; rollback; undo; 30 edits in a row keep
the video whole (no shrinking, no corruption, sound in sync)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import wait_job

from cutmind.api import create_app
from cutmind.ffmpeg_utils import decode_check, probe, run_ffmpeg
from cutmind.plan import EditPlan

pytestmark = pytest.mark.integration
RESULTS = Path(__file__).resolve().parents[2] / "tests" / "results" / "tier1_stability.json"


@pytest.fixture(scope="module")
def env(tmp_path_factory, music_dir):
    d = tmp_path_factory.mktemp("t1api")
    clips = []
    for i, (src, hz) in enumerate((("testsrc2", 440), ("smptehdbars", 660), ("testsrc", 880))):
        f = d / f"c{i}.mp4"
        run_ffmpeg(["-f", "lavfi", "-i", f"{src}=s=640x360:r=30:d=6", "-f", "lavfi", "-i",
                    f"sine=frequency={hz}:sample_rate=48000:duration=6", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(f)])
        clips.append(f)
    with TestClient(create_app(make_settings(d / "data", music_dir))) as c:
        pid = c.post("/projects", json={"name": "t1"}).json()["id"]
        files = [("files", (f.name, f.read_bytes(), "video/mp4")) for f in clips]
        assert c.post(f"/projects/{pid}/clips", files=files).status_code == 201
        yield c, pid


def run_tools(c, pid, prompt=None, calls=None):
    body = {"prompt": prompt} if prompt else {"calls": calls}
    r = c.post(f"/projects/{pid}/tools", json=body)
    if r.status_code != 202:
        return r, None, None
    job = wait_job(c, r.json()["job_id"])
    plan = EditPlan.model_validate(c.get(f"/projects/{pid}/plan").json()) if job["status"] == "done" else None
    return r, job, plan


def test_parse_endpoint_and_refusal(env):
    c, pid = env
    r = c.post("/tools/parse", json={"prompt": "beech beech me black and white, zoom mat lagao"}).json()
    assert [x["id"] for x in r["calls"]] == ["grayscale"] and "zoom_in" in r["negated"]
    bad = c.post(f"/projects/{pid}/tools", json={"prompt": "4k upscale kar do"})
    assert bad.status_code == 422 and "not available yet" in bad.text and "Closest" in bad.text
    assert len(c.get("/tools").json()["tools"]) == 108


def test_prompt_makes_a_version_and_undo_restores(env):
    c, pid = env
    r, job, plan = run_tools(c, pid, "sab jod do aur warm karo")
    assert job["status"] == "done", job.get("error")
    assert len(plan.clips) == 3 and any(e.type == "grade" for e in plan.effects)
    explain = job.get("explain") or {}
    assert [t["skill"] for t in explain.get("tools", [])] == ["merge_clips", "warm"]
    r2, job2, plan2 = run_tools(c, pid, "black and white kar do")
    assert job2["status"] == "done"
    undo = c.post(f"/projects/{pid}/undo")
    assert undo.status_code == 200, undo.text
    back = EditPlan.model_validate(c.get(f"/projects/{pid}/plan").json())
    assert back.to_json() == plan.to_json()
    c.post(f"/projects/{pid}/redo")


def test_a_failing_call_leaves_the_last_version(env):
    c, pid = env
    before = c.get(f"/projects/{pid}/plan").json()
    versions = len(c.get(f"/projects/{pid}/versions").json()["versions"])
    r, job, _ = run_tools(c, pid, calls=[{"id": "grayscale"}, {"id": "trim", "params": {"start": 90, "end": 95}}])
    assert job is not None and job["status"] == "failed"
    assert c.get(f"/projects/{pid}/plan").json() == before
    assert len([v for v in c.get(f"/projects/{pid}/versions").json()["versions"]]) <= versions + 1  # the failed job is listed, not done


SEQUENCE = [  # 30 edits in a row; (prompt, changes the length?)
    ("vertical banao blur sides ke saath", False), ("thoda bright karo", False), ("contrast badhao", False),
    ("crossfade lagao", True), ("zoom in karo 2 se 4 sec", False), ("vignette lagao", False),
    ("upbeat music lagao", False), ("music volume down 6 dB", False), ("text 'Goa Trip' upar likho", False),
    ("progress bar lagao", False), ("film grain daalo", False), ("teal orange look", False),
    ("shake karo 1 se 2 sec", False), ("whoosh sound on every cut", False), ("pan right karo", False),
    ("rgb split 3 se 4 sec", False), ("kali patti lagao", False), ("fade in and fade out", False),
    ("sepia karo", False), ("saturation kam karo", False), ("glitch 5 se 6 sec", False),
    ("text ka color neon pink karo", False), ("light leak lagao", False), ("audio fade in and out", False),
    ("echo daalo halka", False), ("square bana do", False), ("countdown from 3", False),
    ("lower third 'Anmol' lagao", False), ("sticker 🔥 lagao", False), ("export for instagram reels", False),
]


def test_thirty_edits_in_a_row_stay_whole(env):
    c, pid = env
    run_tools(c, pid, "sab jod do")
    rows = []
    prev = EditPlan.model_validate(c.get(f"/projects/{pid}/plan").json())
    for k, (prompt, changes) in enumerate(SEQUENCE, 1):
        t0 = time.monotonic()
        r, job, plan = run_tools(c, pid, prompt)
        row = {"step": k, "prompt": prompt, "http": r.status_code}
        if job is None or job["status"] != "done":
            row.update(status=job["status"] if job else "rejected", error=(job or {}).get("error") or r.text[:200])
            rows.append(row)
            continue
        resp = c.get(f"/projects/{pid}/output")
        tmp = Path(str(RESULTS.parent / f"step_{k}.mp4"))
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(resp.content)
        info = probe(tmp)
        ok, err = decode_check(tmp)
        a_v = abs(info.duration - plan.total_duration())
        row.update(status="done", seconds=round(time.monotonic() - t0, 1), duration=round(info.duration, 2),
                   plan_duration=round(plan.total_duration(), 2), prev_duration=round(prev.total_duration(), 2),
                   size=f"{info.width}x{info.height}", audio=info.has_audio, decodes=ok,
                   tools=[t["skill"] for t in (job.get("explain") or {}).get("tools", [])])
        row["ok"] = bool(ok and info.has_audio and a_v < 0.2 and
                         (changes or abs(plan.total_duration() - prev.total_duration()) < 0.06))
        rows.append(row)
        tmp.unlink(missing_ok=True)
        prev = plan
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    failed = [r for r in rows if not r.get("ok")]
    assert not failed, failed
