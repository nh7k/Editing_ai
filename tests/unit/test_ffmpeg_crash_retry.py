"""FFmpeg 9.0.1's arnndn segfaults at random (8 of 20 runs of one command, measured): a crash is run again, a voice
clean-up that keeps crashing falls back to afftdn, and a real ffmpeg error is never retried."""

from __future__ import annotations

import pytest

from cutmind import ffmpeg_utils as fu


def _crash(msg: str = "ffmpeg crashed") -> fu.FFmpegError:
    e = fu.FFmpegError(msg)
    e.crashed = True  # type: ignore[attr-defined]
    return e


def test_a_crash_is_run_again(monkeypatch):
    calls = []

    def once(args, cwd, timeout, stall):  # noqa: ANN001
        calls.append(list(args))
        if len(calls) < 3:
            raise _crash()
        return "ok"

    monkeypatch.setattr(fu, "_run_ffmpeg_once", once)
    assert fu.run_ffmpeg(["-i", "x.mp4", "-af", "volume=2", "y.wav"]) == "ok"
    assert len(calls) == 3 and calls[0] == calls[2]


def test_voice_cleanup_that_keeps_crashing_uses_afftdn(monkeypatch):
    calls = []

    def once(args, cwd, timeout, stall):  # noqa: ANN001
        calls.append(list(args))
        if any("arnndn=" in a for a in args):
            raise _crash()
        return "ok"

    monkeypatch.setattr(fu, "_run_ffmpeg_once", once)
    # the renderer's real graph: the model name is followed directly by a pad label
    graph = "[0:a]asetpts=N/SR/TB,highpass=f=80,arnndn=m=rnn.rnnn[voice0];[voice0]volume=1.80[aout]"
    assert fu.run_ffmpeg(["-i", "x.mp4", "-filter_complex", graph, "-map", "[aout]", "y.wav"]) == "ok"
    assert len(calls) == fu.CRASH_RETRIES + 2
    assert calls[-1][3] == "[0:a]asetpts=N/SR/TB,highpass=f=80,afftdn=nf=-25[voice0];[voice0]volume=1.80[aout]"


def test_a_real_error_is_not_retried(monkeypatch):
    calls = []

    def once(args, cwd, timeout, stall):  # noqa: ANN001
        calls.append(args)
        raise fu.FFmpegError("ffmpeg failed", "No such filter: 'nope'")

    monkeypatch.setattr(fu, "_run_ffmpeg_once", once)
    with pytest.raises(fu.FFmpegError, match="No such filter"):
        fu.run_ffmpeg(["-af", "nope", "y.wav"])
    assert len(calls) == 1
