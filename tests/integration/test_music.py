"""Your own song: upload / list / pick / delete, an edit cut to it, sound controls, text behind a person, lyrics."""

from __future__ import annotations

import time

import numpy as np
import pytest
from conftest import make_settings
from fastapi.testclient import TestClient

from cutmind import segmentation
from cutmind.ffmpeg_utils import extract_frame, probe, run_ffmpeg
from cutmind.media_gen import make_song, make_speech_wav
from cutmind.plan import Canvas, ClipSegment, EditPlan, TextItem, TextStyle
from cutmind.renderer import render

pytestmark = pytest.mark.integration


@pytest.fixture
def client(tmp_path, music_dir):
    from cutmind.api import create_app

    with TestClient(create_app(make_settings(tmp_path / "data", music_dir))) as c:
        yield c


def _wait(client, job_id, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(1)
    raise AssertionError("job timed out")


def test_upload_pick_and_edit_to_your_song(client, tmp_path, media):
    pid = client.post("/projects", json={"name": "song"}).json()["id"]
    with open(media["c"], "rb") as f:
        assert client.post(f"/projects/{pid}/clips", files={"files": ("c.mp4", f, "video/mp4")}).status_code == 201
    song = make_song(tmp_path / "mysong.m4a", 128, 20, drop_at=6.0, busy=True)
    with open(song, "rb") as f:
        r = client.post(f"/projects/{pid}/music", files={"file": ("My Song!.mp3", f, "audio/mpeg")})
    assert r.status_code == 201, r.text
    up = r.json()
    assert up["name"] == "My_Song.m4a" and up["selected"] and up["feel"] == "fast" and abs(up["drop"] - 6.0) < 0.15
    lst = client.get(f"/projects/{pid}/music").json()
    assert lst["selected"] == "My_Song.m4a" and [s["name"] for s in lst["project"]] == ["My_Song.m4a"]
    assert len(lst["library"]) >= 2
    # a video works as a song source too (its sound is used); a text file does not
    with open(media["a"], "rb") as f:
        assert client.post(f"/projects/{pid}/music", files={"file": ("talk.mp4", f, "video/mp4")}).status_code == 201
    bad = client.post(f"/projects/{pid}/music", files={"file": ("x.txt", b"hello", "text/plain")})
    assert bad.status_code == 400 and "song file" in bad.json()["error"]["message"]
    assert client.put(f"/projects/{pid}/music/selected", json={"name": "My_Song.m4a"}).status_code == 200
    assert client.get(f"/projects/{pid}/music/My_Song.m4a/file").status_code == 200

    job = client.post(f"/projects/{pid}/edit", json={"prompt": "make a skate edit with nice animations, 9:16"}).json()
    done = _wait(client, job["job_id"])
    assert done["status"] == "done", done.get("error")
    plan = client.get(f"/projects/{pid}/plan").json()
    assert plan["audio"]["music"] == "My_Song.m4a"
    assert any(d["decision"] == "song feel" for d in plan["decisions"])
    assert any(d["decision"] == "song-driven cuts" for d in plan["decisions"])

    # instant sound controls on that edit
    m = client.post(f"/projects/{pid}/manual", json={"ops": [{"op": "set_audio", "music_volume": 0.3, "mute": True}]})
    assert m.status_code == 202, m.text
    assert _wait(client, m.json()["job_id"])["status"] == "done"
    a = client.get(f"/projects/{pid}/plan").json()["audio"]
    assert a["music_volume"] == 0.3 and a["mute"]
    nope = client.post(f"/projects/{pid}/manual", json={"ops": [{"op": "set_audio", "music": "missing.mp3"}]})
    assert nope.status_code == 422

    assert client.delete(f"/projects/{pid}/music/My_Song.m4a").json()["ok"]
    assert client.get(f"/projects/{pid}/music").json()["selected"] is None
    assert client.delete(f"/projects/{pid}/music/calm_80bpm.m4a").status_code == 404  # library songs stay


def test_voice_louder_than_the_music(tmp_path, media, music_dir):
    seg = [ClipSegment(source="a", **{"in": 0}, out=6, order=0)]
    canvas = Canvas(aspect_ratio="16:9", resolution=360)

    def voice_share(vol: float) -> float:
        plan = EditPlan(canvas=canvas, clips=seg, audio={"music": "upbeat_120bpm.m4a", "music_volume": 0.3,
                                                         "voice_volume": vol})
        out = render(plan, {"a": media["a"]}, tmp_path / f"w{vol}", tmp_path / f"o{vol}.mp4", [music_dir])
        # voice band vs the music's 7 kHz hi-hat (the only sound there; the clip has low hum of its own)
        wav = tmp_path / f"o{vol}.wav"
        run_ffmpeg(["-i", str(out), "-ac", "1", "-ar", "22050", str(wav)])
        import soundfile as sf

        x, sr = sf.read(str(wav))
        spec = np.abs(np.fft.rfft(x))
        f = np.fft.rfftfreq(len(x), 1 / sr)
        return float(spec[(f > 450) & (f < 3000)].sum() / spec[(f > 6950) & (f < 7050)].sum())

    assert voice_share(1.8) > 1.4 * voice_share(1.0)


def test_music_starts_where_the_plan_says(tmp_path, media):
    d = tmp_path / "m"
    make_song(d / "late.m4a", 120, 20, drop_at=10.0)  # silent drums until 10 s
    seg = [ClipSegment(source="c", **{"in": 0}, out=4, order=0)]
    canvas = Canvas(aspect_ratio="16:9", resolution=360)
    kick = []
    for start in (0.0, 10.0):
        plan = EditPlan(canvas=canvas, clips=seg, audio={"music": "late.m4a", "music_volume": 1.0, "mute": True,
                                                         "music_start": start})
        out = render(plan, {"c": media["c"]}, tmp_path / f"w{start}", tmp_path / f"o{start}.mp4", [d])
        assert abs(probe(out).duration - 4.0) < 0.15
        kick.append(_band_share(out, tmp_path, (30, 90), (200, 1000)))
    # from 0 s: the quiet pad only; from 10 s: the drums (55 Hz kick) are there
    assert kick[1] > 3 * kick[0], kick


def _band_share(video, tmp_path, band, ref):
    import soundfile as sf

    wav = tmp_path / f"{video.stem}_band.wav"
    run_ffmpeg(["-i", str(video), "-ac", "1", "-ar", "16000", str(wav)])
    x, sr = sf.read(str(wav))
    spec = np.abs(np.fft.rfft(x))
    f = np.fft.rfftfreq(len(x), 1 / sr)
    return float(spec[(f > band[0]) & (f < band[1])].sum() / (spec[(f > ref[0]) & (f < ref[1])].sum() + 1e-9))


def test_text_behind_the_person_is_hidden_where_the_person_is(tmp_path, media, monkeypatch):
    """Compositing: where the person mask is white the picture (person) is drawn over the text."""
    seg = [ClipSegment(source="c", **{"in": 0}, out=3, order=0)]
    canvas = Canvas(aspect_ratio="16:9", resolution=360)
    style = TextStyle(position="center", size=200, box_color=None, color="#FF00FF")
    text = TextItem(kind="text", text="COLD", start=0.5, end=2.5, style=style)

    def half_mask(video, windows, out):  # "a person" covering the left half of the frame
        info = probe(video)
        run_ffmpeg(["-f", "lavfi", "-i", f"color=black:s={info.width}x{info.height}:r={info.fps}:d={info.duration}",
                    "-vf", f"drawbox=x=0:y=0:w={info.width // 2}:h={info.height}:color=white:t=fill",
                    "-c:v", "ffv1", "-pix_fmt", "gray", str(out)])
        return out

    monkeypatch.setattr(segmentation, "available", lambda: True)
    monkeypatch.setattr(segmentation, "mask_video", half_mask)
    front = render(EditPlan(canvas=canvas, clips=seg, text=[text]), {"c": media["c"]}, tmp_path / "f", tmp_path / "f.mp4")
    behind = render(EditPlan(canvas=canvas, clips=seg, text=[text.model_copy(update={"behind": True})]),
                    {"c": media["c"]}, tmp_path / "b", tmp_path / "b.mp4")
    plain = render(EditPlan(canvas=canvas, clips=seg), {"c": media["c"]}, tmp_path / "p", tmp_path / "p.mp4")
    ff, bb, pp = (extract_frame(x, 1.5).astype(int) for x in (front, behind, plain))
    w = ff.shape[1]
    left = slice(0, w // 2 - 10)
    right = slice(w // 2 + 10, w)
    def changed(a, b, cols):  # share of pixels the text visibly changed
        return float((np.abs(a[:, cols] - b[:, cols]).max(axis=2) > 40).mean())

    # left half ("person"): the text is gone; right half: the text is there exactly as without "behind"
    assert changed(ff, pp, left) > 0.02 and changed(bb, pp, left) < 0.002
    assert changed(ff, pp, right) > 0.02 and changed(bb, ff, right) < 0.002


def test_person_mask_on_a_frame_without_people_is_empty(media):
    if not segmentation.available():
        pytest.skip("segmentation model not downloaded")
    frame = extract_frame(media["c"], 1.0)
    assert segmentation.person_mask(frame).max() == 0.0


def test_lyrics_are_found_with_their_times(tmp_path, monkeypatch):
    """A sung line over a beat → the words, at the time they are heard."""
    monkeypatch.setenv("LYRICS_MODEL", "tiny")
    voice = tmp_path / "v.wav"
    if make_speech_wav(voice, "it is too cold for you here") == "none":
        pytest.skip("no local TTS engine on this machine")
    beat = make_song(tmp_path / "beat.m4a", 100, 10)
    song = tmp_path / "song.m4a"
    run_ffmpeg(["-i", str(beat), "-i", str(voice), "-filter_complex",
                "[1:a]adelay=3000|3000,volume=2.0[v];[0:a]volume=0.4[b];[b][v]amix=inputs=2:duration=first",
                "-c:a", "aac", str(song)])
    from cutmind.lyrics import song_words

    words = song_words(song, tmp_path / "w", tmp_path / "cache")
    text = " ".join(w.text.lower() for w in words)
    assert "cold" in text, text
    cold = next(w for w in words if w.text.lower() == "cold")
    assert 3.0 < cold.start < 6.0  # the voice starts at 3 s
    again = song_words(song, tmp_path / "w", tmp_path / "cache", only_cached=True)
    assert again is not None and [w.text for w in again] == [w.text for w in words]
