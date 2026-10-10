"""End-to-end: "mast sa edit kar do" (auto edit) and "arrange the clips" on messy uploads. Real API, real renders.

The three generated clips are uploaded in the WRONG order: their phone-style file names say clip B was filmed
first, then C, then A.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import download_output, media_facts, wait_job

from cutmind.api import create_app
from cutmind.plan import EditPlan

pytestmark = pytest.mark.integration
NAMES = {"a": "IMG_20260930_120000.mp4", "b": "IMG_20260930_100000.mp4", "c": "IMG_20260930_110000.mp4"}


@pytest.fixture(scope="module")
def env(tmp_path_factory, media, music_dir):
    data = tmp_path_factory.mktemp("auto_data")
    with TestClient(create_app(make_settings(data, music_dir))) as client:
        pid = client.post("/projects", json={"name": "messy upload"}).json()["id"]
        files = [("files", (NAMES[k], media[k].read_bytes(), "video/mp4")) for k in ("a", "b", "c")]
        r = client.post(f"/projects/{pid}/clips", files=files)
        assert r.status_code == 201, r.text
        ids = {c["filename"]: c["id"] for c in r.json()["clips"]}
        yield {"client": client, "pid": pid, "work": data, "id": {k: ids[n] for k, n in NAMES.items()}}


def run(env, prompt: str) -> tuple[dict, EditPlan, dict, float]:
    client, pid = env["client"], env["pid"]
    t0 = time.monotonic()
    r = client.post(f"/projects/{pid}/edit", json={"prompt": prompt})
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["job_id"])
    took = time.monotonic() - t0
    assert job["status"] == "done", job["error"]
    plan = EditPlan.model_validate(client.get(f"/projects/{pid}/plan").json())
    out = download_output(client, pid, Path(env["work"]) / f"{abs(hash(prompt))}.mp4")
    facts = media_facts(out)
    assert facts["plays"] and facts["has_audio"]
    assert abs(facts["duration"] - plan.total_duration()) <= 0.35
    return job, plan, facts, took


def test_arrange_puts_messy_clips_in_filming_order(env):
    job, plan, _facts, _took = run(env, "ulti sidhi footage hai, arrange kar do")
    by_id = {v: k for k, v in env["id"].items()}
    seen = list(dict.fromkeys(by_id[s.source] for s in plan.ordered_clips()))
    assert seen == ["b", "c", "a"]  # filmed 10:00, 11:00, 12:00 — uploaded a, b, c
    order_check = next(c for c in job["review"]["checks"] if c["name"] == "clip_order")
    assert order_check["passed"], order_check


def test_auto_edit_builds_a_complete_edit_by_itself(env):
    job, plan, facts, took = run(env, "mast sa edit kar do")
    logs = "\n".join(x["msg"] for x in job["logs"])
    assert "Auto edit:" in logs
    caps = [t for t in plan.text if t.kind == "caption"]
    assert caps, "the talking clip must get captions of what is said"
    assert any("mountains" in t.text.lower() for t in caps)
    assert all(t.style.animation == "pop" for t in caps)
    assert plan.audio.music and plan.color.preset in ("vivid", "warm")  # editorial skill or autopilot look
    assert any(e.type == "zoom" for e in plan.effects)
    # hook: the edit opens with a moment nobody speaks in, moved from later in the edit
    assert "hook:" in logs
    first = plan.ordered_clips()[0]
    assert first.source != env["id"]["b"] or first.in_ > 0.1  # not simply "the first clip from its start"
    # pauses and "Um" removed from the talking clip: the edit is shorter than the raw material
    assert facts["duration"] < 14.0 + 8.0 + 12.0 - 3.0
    assert job["match_percent"] >= 90, [c for c in job["review"]["checks"] if not c["passed"]]
    print(f"auto edit took {took:.1f}s for {facts['duration']:.1f}s of output")
    assert took < 180
