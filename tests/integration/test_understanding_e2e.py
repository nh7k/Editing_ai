"""30 prompts end to end through the real API and FFmpeg (docs/UNDERSTANDING_REVIEW.md, Phase 7).

One project, one message after another, as a user would type them (chat and timeline comments). After each one the
rendered output is measured (ffprobe length, frame colour / brightness / warmth, audio level) and compared with
the output before it. Results go to tests/results/understanding_e2e.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import wait_job

from cutmind.api import create_app
from cutmind.ffmpeg_utils import extract_frame, probe, run_ffmpeg

pytestmark = pytest.mark.integration
RESULTS = Path(__file__).resolve().parents[2] / "tests" / "results" / "understanding_e2e.json"


def sat(f) -> float:  # noqa: ANN001
    f = f.astype(float)
    return float((f.max(axis=2) - f.min(axis=2)).mean())


def luma(f) -> float:  # noqa: ANN001
    return float(f.astype(float).mean())


def rb(f) -> float:  # noqa: ANN001
    f = f.astype(float)
    return float((f[..., 0] - f[..., 2]).mean())


def rms_db(path: Path) -> float:
    import subprocess

    from cutmind.ffmpeg_utils import ffmpeg_bin

    raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True, timeout=60, check=False).stdout
    a = np.frombuffer(raw, np.int16).astype(float) / 32768.0
    return 20 * np.log10(max(1e-6, float(np.sqrt(np.mean(a ** 2))))) if a.size else -120.0


class Session:
    def __init__(self, c, pid, d: Path) -> None:  # noqa: ANN001
        self.c, self.pid, self.d, self.n, self.log = c, pid, d, 0, []
        self.prev: dict | None = None

    def versions(self) -> int:
        return len(self.c.get(f"/projects/{self.pid}/versions").json()["versions"])

    def measure(self) -> dict:
        self.n += 1
        out = self.c.get(f"/projects/{self.pid}/output")
        assert out.status_code == 200, out.text
        p = self.d / f"o{self.n}.mp4"
        p.write_bytes(out.content)
        info = probe(p)
        t = min(2.0, info.duration / 2)
        f = extract_frame(p, t)
        return {"path": p, "dur": info.duration, "sat": sat(f), "luma": luma(f), "rb": rb(f), "db": rms_db(p),
                "frame": f}

    def say(self, prompt: str, at: float | None = None, playhead: float | None = None,
            may_refuse: bool = False) -> tuple[dict, dict]:
        body = {"prompt": prompt, **({"at": at} if at is not None else {}), **({"playhead": playhead} if playhead else {})}
        r = self.c.post(f"/projects/{self.pid}/edit", json=body)
        res = r.json()
        if r.status_code == 202 and res.get("job_id") and res.get("decision") != "undo":
            job = wait_job(self.c, res["job_id"], timeout=600)
            res["job_error"] = job.get("error")
            # may_refuse: a footage limit ("no speech found") must be a clear message, never a crash or a wrong edit
            assert job["status"] == "done" or (may_refuse and job.get("error")), (prompt, job.get("error"))
        m = self.measure()
        self.log.append({"prompt": prompt, "at": at, "status": r.status_code, "decision": res.get("decision")
                         or (res.get("error") or {}).get("code"), "did": res.get("did") or (res.get("error") or {}).get("message", "")[:120],
                         "dur": round(m["dur"], 2), "sat": round(m["sat"], 1), "luma": round(m["luma"], 1),
                         "rb": round(m["rb"], 1), "db": round(m["db"], 1)})
        before, self.prev = self.prev, m
        return res, before or m


@pytest.fixture(scope="module")
def s(tmp_path_factory, music_dir):
    d = tmp_path_factory.mktemp("u2e")
    clips = []
    for i, (src, hz) in enumerate((("testsrc2", 330), ("smptehdbars", 550))):
        f = d / f"c{i}.mp4"
        run_ffmpeg(["-f", "lavfi", "-i", f"{src}=s=640x360:r=30:d=5", "-f", "lavfi", "-i",
                    f"sine=frequency={hz}:sample_rate=48000:duration=5", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(f)])
        clips.append(f)
    with TestClient(create_app(make_settings(d / "data", music_dir))) as c:
        pid = c.post("/projects", json={"name": "u2e"}).json()["id"]
        files = [("files", (f.name, f.read_bytes(), "video/mp4")) for f in clips]
        assert c.post(f"/projects/{pid}/clips", files=files).status_code == 201
        r = c.post(f"/projects/{pid}/tools", json={"calls": [{"id": "merge_clips"}]})
        assert wait_job(c, r.json()["job_id"])["status"] == "done"
        sess = Session(c, pid, d)
        sess.prev = sess.measure()
        yield sess
        RESULTS.parent.mkdir(parents=True, exist_ok=True)
        RESULTS.write_text(json.dumps(sess.log, indent=1, ensure_ascii=False), encoding="utf-8")


def test_30_prompts_end_to_end(s):  # noqa: PLR0915 — one story, step by step
    # 1-3: colour, then "aur thoda" / "kam karo" move the SAME edit
    res, b = s.say("warm karo")
    assert s.prev["rb"] > b["rb"] + 3, s.log[-1]
    warm1 = s.prev["rb"]
    res, b = s.say("aur thoda")
    assert res.get("decision") == "apply" and s.prev["rb"] > warm1 + 1, s.log[-1]
    res, b = s.say("kam karo")
    assert s.prev["rb"] < b["rb"] - 1, s.log[-1]
    # 4: "isko hata do" right after = undo (the version before comes back, no render)
    v = s.versions()
    res, b = s.say("isko hata do")
    assert res.get("decision") == "undo" and s.versions() >= v, s.log[-1]
    # 5-6: black and white, then the original bug as a timeline comment at 4.3 s → restore at that moment
    res, b = s.say("black and white karo")
    assert s.prev["sat"] < 5, s.log[-1]
    res, b = s.say("yaha screen white kar do nomal jasia tha", at=4.3)
    assert res.get("decision") == "act" and "flash" in [x["id"] for x in res["alternatives"]], res
    f = extract_frame(s.prev["path"], 4.3)
    assert sat(f) > 40, s.log[-1]  # colour is back at the marker
    # 7: the alternative chip instead (undo + flash at 4.3 s)
    flash = next(x for x in res["alternatives"] if x["id"] == "flash")
    assert s.c.post(f"/projects/{s.pid}/undo").status_code == 200
    r = s.c.post(f"/projects/{s.pid}/tools", json={"calls": flash["calls"], "prompt": "flash"})
    assert wait_job(s.c, r.json()["job_id"])["status"] == "done"
    m = s.measure()
    assert luma(extract_frame(m["path"], 4.3)) > luma(extract_frame(m["path"], 3.6)) + 30
    s.prev = m
    # 8: "pehle jaisa kar do" in the chat (no marker) → back to normal everywhere
    res, b = s.say("pehle jaisa kar do")
    assert s.prev["sat"] > 40, s.log[-1]
    # 9: a greeting never edits
    v = s.versions()
    res, b = s.say("hello bhai")
    assert res.get("error", {}).get("code") == "non_edit" and s.versions() == v
    # 10: a question never edits
    res, b = s.say("ye app kaise kaam karta hai?")
    assert s.versions() == v
    # 11: 5 instructions, 2 unsupported → the 3 others still applied
    res, b = s.say("warm karo, vignette lagao, music lagao, mera chehra jawan karo aur 3d animation daalo", at=0.5)
    assert res.get("decision") == "partial" and len(res["unclear"]) == 2, res
    assert s.prev["rb"] > b["rb"] + 2 and s.prev["db"] > b["db"] - 30, s.log[-1]
    # 12: negation inside a multi-instruction prompt
    res, b = s.say("zoom mat lagao, sepia karo")
    assert s.prev["rb"] > 5, s.log[-1]
    # 13-14: speed and slow motion change the length
    res, b = s.say("2x speed kar do")
    assert s.prev["dur"] < b["dur"] * 0.62, s.log[-1]
    res, b = s.say("ab slow motion karo")
    assert s.prev["dur"] > b["dur"] * 1.5, s.log[-1]
    # 15: undo the slow motion
    assert s.c.post(f"/projects/{s.pid}/undo").status_code == 200
    s.prev = s.measure()
    # 16: white screen card at a marker: +1 s, a white frame there
    d0 = s.prev["dur"]
    res, b = s.say("yaha 1 sec white screen daalo", at=1.0)
    assert abs(s.prev["dur"] - d0 - 1.0) < 0.15, s.log[-1]
    assert luma(extract_frame(s.prev["path"], 1.5)) > 235
    # 17: brighten towards white at a marker
    res, b = s.say("yaha screen white sa kar do", at=3.0)
    assert luma(extract_frame(s.prev["path"], 3.5)) > luma(extract_frame(b["path"], 3.5)) + 15, s.log[-1]
    # 18: tilt
    res, b = s.say("video thoda ghumao")
    t = s.prev["dur"] - 1.0  # a textured moment (2.0 s is now the white card: rotating white shows nothing)
    moved = float(np.abs(extract_frame(s.prev["path"], t).astype(float) - extract_frame(b["path"], t).astype(float)).mean())
    assert moved > 8, (moved, s.log[-1])
    # 19: mute
    res, b = s.say("awaaz band kar do")
    # documented: the clip's own sound goes off, the music added at step 11 stays (said back to the user)
    plan = s.c.get(f"/projects/{s.pid}/plan").json()
    assert plan["audio"]["mute"] is True and "music" in res.get("did", "") + json.dumps(plan["audio"]), s.log[-1]
    # 20: "dobara" → the last edit again (no crash, a new version)
    res, b = s.say("dobara karo")
    assert res.get("decision") in ("apply", "undo"), res
    # 21-22: Devanagari and typos
    res, b = s.say("आवाज़ बढ़ाओ")
    assert s.prev["db"] > b["db"] or b["db"] < -60, s.log[-1]
    res, b = s.say("blak and wite kro")
    assert s.prev["sat"] < 5, s.log[-1]
    # 23: restore by name of the effect with the effect on screen (comment)
    t = round(s.prev["dur"] - 1.5, 2)  # a textured moment (1-2 s is the white card of step 16)
    res, b = s.say("ye black white hatao yaha se", at=t)
    assert sat(extract_frame(s.prev["path"], t)) > 20, s.log[-1]
    # 24: unsupported request: nothing applied, closest options offered
    v = s.versions()
    res, b = s.say("meri height badha do")
    assert s.versions() == v and (res.get("error") or {}).get("choices"), res
    # 25: emoji only
    res, b = s.say("😂😂")
    assert s.versions() == v
    # 26: a clear multi-instruction prompt applies everything
    res, b = s.say("contrast badhao aur vignette lagao", at=0.5)
    assert s.versions() == v + 1, s.log[-1]
    # 27: relative after it
    res, b = s.say("thoda kam")
    assert res.get("decision") == "apply", res
    # 28: crop-free tilt back to normal via restore in chat
    res, b = s.say("sab effects hata ke normal karo")
    assert res.get("decision") in ("apply", "act"), res
    # 29: captions? (no speech in tones — the engine must answer, never crash)
    res, b = s.say("captions lagao", may_refuse=True)  # tones only: nothing is said, so the honest answer is no
    assert res.get("job_id") or res.get("error"), res
    # 30: export preset for reels
    res, b = s.say("instagram reels ke liye export karo")
    assert res.get("job_id") or res.get("error"), res
    assert len(s.log) >= 28
