"""Vlog word stickers: someone SAYS "rose", "tree", "coffee" — the agent pops those up as stickers at that moment.
Real speech (local TTS), real transcription, real render."""

from __future__ import annotations

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import wait_job

from cutmind import stickers
from cutmind.api import create_app
from cutmind.ffmpeg_utils import decode_check, run_ffmpeg
from cutmind.media_gen import make_speech_wav
from cutmind.plan import EditPlan

pytestmark = pytest.mark.integration

SAID = ('Look at this beautiful rose. <break time="1500ms"/> And here is a very big tree. '
        '<break time="1500ms"/> Now we drink some coffee.')


@pytest.fixture(scope="module")
def vlog(tmp_path_factory):
    d = tmp_path_factory.mktemp("vlog")
    wav = d / "say.wav"
    if make_speech_wav(wav, SAID) == "none":
        pytest.skip("no local text-to-speech on this machine")
    clip = d / "vlog.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30", "-i", str(wav), "-shortest",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)])
    return clip


@pytest.fixture(scope="module")
def env(tmp_path_factory, vlog, music_dir):
    data = tmp_path_factory.mktemp("stickers")
    with TestClient(create_app(make_settings(data, music_dir))) as c:
        pid = c.post("/projects", json={"name": "vlog"}).json()["id"]
        assert c.post(f"/projects/{pid}/clips", files=[("files", ("vlog.mp4", vlog.read_bytes(), "video/mp4"))]
                      ).status_code == 201
        yield c, pid, data


def edit(c, pid, prompt, **extra):
    r = c.post(f"/projects/{pid}/edit", json={"prompt": prompt, **extra})
    assert r.status_code == 202, r.text
    job = wait_job(c, r.json()["job_id"])
    assert job["status"] == "done", (job["error"], [x["msg"][-900:] for x in job.get("logs", []) if x["level"] == "error"])
    return job, EditPlan.model_validate(c.get(f"/projects/{pid}/plan").json())


def test_said_things_pop_up_as_stickers_and_go_away_on_request(env):
    if not stickers.available():
        pytest.skip("no colour emoji font")
    c, pid, data = env
    job, plan = edit(c, pid, "vlog me jo bhi bol raha hu jaise rose, tree uske stickers daal do")
    emojis = [s.emoji for s in plan.stickers]
    assert "\U0001F339" in emojis and "\U0001F333" in emojis, (
        [(s.word, s.start) for s in plan.stickers], [(k.in_, k.out) for k in plan.ordered_clips()],
        [d.decision + ": " + d.where for d in plan.decisions][:40])
    rose = next(s for s in plan.stickers if s.emoji == "\U0001F339")
    tree = next(s for s in plan.stickers if s.emoji == "\U0001F333")
    assert rose.start < tree.start  # in the order they are said
    ok, err = decode_check(data / "projects" / pid / "output" / f"{job['id']}.mp4")
    assert ok, err
    _job, plan2 = edit(c, pid, "stickers hata do")
    assert plan2.stickers == []


def test_timeline_comments_change_only_their_moment_and_add_up(env):
    c, pid, data = env
    _job, base = edit(c, pid, "naya edit, warm color kar do")
    total = base.total_duration()
    at = round(total / 2, 2)
    # 1) "WOW likh do" at the middle: text there, colour kept
    _job, p1 = edit(c, pid, "WOW likh do", at=at)
    wow = [t for t in p1.text if t.text == "WOW"]
    assert wow and abs(wow[0].start - at) < 0.05, [(t.text, t.start) for t in p1.text]
    assert p1.color.preset == "warm"
    # 2) "zoom" at 1 s: an effect only on the shot(s) there, the WOW text stays
    _job, p2 = edit(c, pid, "yaha zoom karo", at=1.0)
    tl = p2.timeline()
    # the zoom skill (comments go to the skills since the understanding engine) writes a keyframed zoom; the
    # requirement is unchanged: a zoom only on the shot(s) at that moment, never the whole video
    zoomed = [e.target for e in p2.effects if e.type in ("zoom", "keyframes")]
    assert zoomed and -1 not in zoomed
    assert all(tl[i].start < 1.0 + 2.6 and tl[i].end > 1.0 - 0.05 for i in zoomed)
    assert any(t.text == "WOW" for t in p2.text), "an earlier comment was lost"
    # 3) a sticker by name
    if stickers.available():
        _job, p3 = edit(c, pid, "rose", at=0.5)
        assert any(s.emoji == "\U0001F339" and abs(s.start - 0.5) < 0.05 for s in p3.stickers)
    # 4) "ye part hata do": the shot there is cut out, the video gets shorter
    before = EditPlan.model_validate(c.get(f"/projects/{pid}/plan").json())
    job, p4 = edit(c, pid, "ye part hata do", at=before.timeline()[-1].start + 0.1)
    assert p4.total_duration() < before.total_duration() - 0.3
    ok, err = decode_check(data / "projects" / pid / "output" / f"{job['id']}.mp4")
    assert ok, err
    # nonsense at a moment: an honest "not understood", no edit
    r = c.post(f"/projects/{pid}/edit", json={"prompt": "kya hai ye?", "at": 1.0})
    assert r.status_code == 422


def test_comment_restyles_or_removes_the_text_at_that_moment(env):
    c, pid, _data = env
    _job, base = edit(c, pid, "naya edit, warm color kar do")
    at = round(base.total_duration() / 2, 2)
    _job, p1 = edit(c, pid, "WOW likh do", at=at)
    _job, p2 = edit(c, pid, "change the text colour black to white", at=at + 0.3)
    wow = [t for t in p2.text if t.text == "WOW"]
    assert wow and wow[0].style.color.upper() == "#FFFFFF", [(t.text, t.style.color) for t in p2.text]
    _job, p3 = edit(c, pid, "ye text hata do", at=at + 0.3)
    assert not any(t.text == "WOW" for t in p3.text)
    r = c.post(f"/projects/{pid}/edit", json={"prompt": "text red kar do", "at": 0.1})
    assert r.status_code == 422 and "koi text nahi" in r.text  # nothing on screen there: said, not faked
