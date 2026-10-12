"""'jo bol raha hu wo screen pe aaye' end to end: real API + speech-to-text + FFmpeg on a vertical speech clip.
The first message makes the talking-head reel (skills, not a director re-edit): captions with each word's real time,
layouts that change with the sentences, keyword cards from what is said, the @handle; the edit stays vertical."""

from __future__ import annotations

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import wait_job

from cutmind.api import create_app
from cutmind.ffmpeg_utils import extract_frame, probe, run_ffmpeg
from cutmind.media_gen import make_speech_wav

pytestmark = pytest.mark.integration

SAY = ('Hello friends, welcome to my channel.<break time="900ms"/> Today we talk about video editing.'
       '<break time="900ms"/> The future of motion design is automatic.<break time="900ms"/> Type motion in the '
       'comments and I will send you the link.')


def test_what_i_say_appears_on_screen(tmp_path, music_dir):
    wav = tmp_path / "say.wav"
    if make_speech_wav(wav, SAY) == "none":
        pytest.skip("no local text-to-speech on this machine")
    clip = tmp_path / "talk.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=360x640:r=30", "-i", str(wav), "-filter_complex",
                "[1:a]aresample=48000,apad=pad_dur=0.6[a]", "-map", "0:v", "-map", "[a]", "-shortest", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)])
    with TestClient(create_app(make_settings(tmp_path / "data", music_dir))) as c:
        pid = c.post("/projects", json={"name": "talk"}).json()["id"]
        assert c.post(f"/projects/{pid}/clips", files=[("files", (clip.name, clip.read_bytes(), "video/mp4"))]).status_code == 201
        r = c.post(f"/projects/{pid}/edit", json={"prompt": "jo bol raha hu wo screen pe aaye @cutmind"})
        assert r.status_code == 202, r.text
        assert r.json().get("decision") == "apply", r.json()  # the skills, also as the FIRST message
        job = wait_job(c, r.json()["job_id"])
        assert job["status"] == "done", job.get("error")
        plan = c.get(f"/projects/{pid}/plan").json()
        out = tmp_path / "out.mp4"
        out.write_bytes(c.get(f"/projects/{pid}/output").content)
    info = probe(out)
    assert info.height > info.width  # a vertical talking head stays vertical
    caps = [t for t in plan["text"] if t["kind"] == "caption"]
    assert len(caps) >= 3 and all(t["style"]["animation"] == "karaoke" for t in caps)
    assert sum(1 for t in caps if t["word_times"]) >= len(caps) - 1  # each word lights up at its real time
    assert {e["type"] for e in plan["effects"]} & {"inset_card", "split_top"}  # the layout changes with the sentences
    titles = [t["text"] for t in plan["text"] if t["kind"] == "title"]
    assert titles, plan["text"]
    assert any(t["text"] == "@CUTMIND" for t in plan["text"])
    # a paper layout really shows cream paper on screen
    lay = next(e for e in plan["effects"] if e["type"] in ("inset_card", "split_top"))
    seg = [x for x in plan["clips"]]  # timeline order = clip order here (one source, split)
    start = sum(cc["out"] - cc["in"] for cc in sorted(seg, key=lambda x: x["order"])[:lay["target"]])
    f = extract_frame(out, start + 0.3).astype(float)
    corner = f[-10:, :10].mean(axis=(0, 1))  # bottom-left corner: paper
    assert abs(corner[0] - 0xEC) < 25 and abs(corner[2] - 0xDA) < 25, corner
