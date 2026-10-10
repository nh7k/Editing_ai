"""Voice prompt (POST /transcribe): real synthesized speech → local faster-whisper → planner understands it."""

from __future__ import annotations

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient

from cutmind.intent import parse_intent
from cutmind.media_gen import VOICE_PROMPT_TEXT, make_corrupt_file, make_speech_wav

pytestmark = pytest.mark.integration


@pytest.fixture
def client(tmp_path, music_dir):
    with TestClient(create_app_for(tmp_path, music_dir)) as c:
        yield c


def create_app_for(tmp_path, music_dir):
    from cutmind.api import create_app

    return create_app(make_settings(tmp_path / "data", music_dir))


def test_spoken_prompt_becomes_an_edit_the_planner_understands(client, tmp_path):
    wav = tmp_path / "voice.wav"
    if make_speech_wav(wav, VOICE_PROMPT_TEXT) == "none":
        pytest.skip("no local TTS engine on this machine")
    # send it the way a browser does: compressed (Opus in WebM), not WAV
    from cutmind.ffmpeg_utils import run_ffmpeg

    webm = tmp_path / "voice.webm"
    run_ffmpeg(["-i", str(wav), "-c:a", "libopus", "-b:a", "32k", str(webm)])
    r = client.post("/transcribe", files={"audio": ("voice.webm", webm.read_bytes(), "audio/webm")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["language"] == "en"
    it = parse_intent(body["text"])
    assert it.captions and it.aspect_ratio == "9:16" and it.color_preset == "warm", body["text"]


def test_voice_errors_are_clear(client, tmp_path):
    r = client.post("/transcribe", files={"audio": ("e.webm", b"", "audio/webm")})
    assert r.status_code == 400 and r.json()["error"]["code"] == "empty_file"
    bad = make_corrupt_file(tmp_path / "bad.webm")
    r = client.post("/transcribe", files={"audio": ("bad.webm", bad.read_bytes(), "audio/webm")})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_audio"
    r = client.post("/transcribe", files={"audio": ("big.webm", b"0" * (5 * 1024 * 1024 + 1), "audio/webm")})
    assert r.status_code == 413
