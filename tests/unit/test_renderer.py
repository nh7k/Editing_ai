"""Renderer: pure filter builders + small REAL renders (FFmpeg is never mocked)."""

import pytest

from cutmind.ffmpeg_utils import decode_check, extract_frame, probe
from cutmind.plan import EditPlan
from cutmind.renderer import RenderError, atempo_chain, build_ass, color_filters, reframe_filter, render


def test_atempo_chain_ranges():
    assert atempo_chain(1.0) == []
    assert atempo_chain(4.0) == ["atempo=2.0", "atempo=2.0"]
    assert atempo_chain(0.25) == ["atempo=0.5", "atempo=0.5"]
    assert atempo_chain(1.5) == ["atempo=1.500000"]


def test_color_filters():
    p = EditPlan.model_validate({"clips": [{"source": "x", "in": 0, "out": 2, "order": 0}],
                                 "color": {"warmth": 0.5, "saturation": 1.2, "preset": "bw", "clip_brightness": {"x": 0.1}}})
    f = color_filters(p, "x")
    assert f[0].startswith("eq=brightness=0.100") and "saturation=1.200" in f[0]
    assert "colortemperature=temperature=5000" in f[1]
    assert f[-1] == "hue=s=0"
    neutral = EditPlan.model_validate({"clips": [{"source": "x", "in": 0, "out": 2, "order": 0}]})
    assert color_filters(neutral, "x") == []


def test_reframe_modes():
    assert "crop=720:1280" in reframe_filter(720, 1280, "crop", "in", "out")
    assert "boxblur" in reframe_filter(720, 1280, "blur_pad", "in", "out")


def test_build_ass_escapes_and_times():
    p = EditPlan.model_validate({"clips": [{"source": "x", "in": 0, "out": 5, "order": 0}],
                                 "text": [{"kind": "caption", "text": "hi {there}\nyou", "start": 1.0, "end": 2.5}]})
    ass = build_ass(p.text, 720, 1280)
    assert "PlayResX: 720" in ass
    assert "Dialogue: 0,0:00:01.00,0:00:02.50,S0,,0,0,0,,hi (there)\\Nyou" in ass
    assert "&H00FF5C7C" in ass  # violet box (#7C5CFF) in ASS BGR order


def _plan(**extra):
    base = {"canvas": {"aspect_ratio": "9:16", "resolution": 360},
            "clips": [{"source": "a", "in": 0.5, "out": 3.0, "order": 0},
                      {"source": "c", "in": 1.0, "out": 3.5, "order": 1, "speed": 2.0}]}
    base.update(extra)
    return EditPlan.model_validate(base)


def test_render_basic_two_segments(media, tmp_path):
    plan = _plan(transitions=[{"type": "crossfade", "after": 0, "duration": 0.4}])
    out = render(plan, {"a": media["a"], "c": media["c"]}, tmp_path / "w", tmp_path / "o.mp4")
    info = probe(out)
    assert (info.width, info.height) == (360, 640)
    assert info.duration == pytest.approx(plan.total_duration(), abs=0.15)  # 2.5 + 1.25 - 0.4
    assert info.has_audio and info.fps == 30
    assert decode_check(out)[0]


def test_render_speed_ramp_and_effects(media, tmp_path):
    plan = _plan(effects=[{"type": "speed_ramp", "target": 0, "strength": 2.0}, {"type": "zoom", "target": -1},
                          {"type": "shake", "target": 1}])
    out = render(plan, {"a": media["a"], "c": media["c"]}, tmp_path / "w", tmp_path / "o.mp4")
    assert probe(out).duration == pytest.approx(plan.total_duration(), abs=0.15)


def test_render_text_is_visible(media, tmp_path):
    base = _plan()
    with_text = _plan(text=[{"kind": "caption", "text": "HELLO", "start": 0.5, "end": 2.0}])
    a = render(base, {"a": media["a"], "c": media["c"]}, tmp_path / "w1", tmp_path / "a.mp4")
    b = render(with_text, {"a": media["a"], "c": media["c"]}, tmp_path / "w2", tmp_path / "b.mp4")
    fa, fb = extract_frame(a, 1.2), extract_frame(b, 1.2)
    band = slice(int(640 * 0.75), int(640 * 0.97))
    changed = (abs(fa[band].astype(int) - fb[band].astype(int)).max(axis=2) > 40).mean()
    assert changed > 0.02, f"caption band barely changed ({changed:.2%} of pixels)"


def test_render_silent_source_gets_audio_track(tmp_path):
    from cutmind.media_gen import make_silent_clip

    src = make_silent_clip(tmp_path / "silent.mp4", 3)
    plan = EditPlan.model_validate({"canvas": {"resolution": 360}, "clips": [{"source": "s", "in": 0, "out": 2.5, "order": 0}]})
    out = render(plan, {"s": src}, tmp_path / "w", tmp_path / "o.mp4")
    assert probe(out).has_audio


def test_render_with_music_and_ducking(media, music_dir, tmp_path):
    plan = _plan(audio={"music": "upbeat_120bpm.m4a", "ducking": True, "music_volume": 0.3})
    out = render(plan, {"a": media["a"], "c": media["c"]}, tmp_path / "w", tmp_path / "o.mp4", music_dir)
    assert probe(out).has_audio


def test_render_errors_are_clear(media, tmp_path):
    with pytest.raises(RenderError, match="unknown clips"):
        render(_plan(), {"a": media["a"]}, tmp_path / "w", tmp_path / "o.mp4")
    with pytest.raises(RenderError, match="music track not found"):
        render(_plan(audio={"music": "missing.mp3"}), {"a": media["a"], "c": media["c"]}, tmp_path / "w", tmp_path / "o.mp4",
               tmp_path)
    late = EditPlan.model_validate({"clips": [{"source": "a", "in": 100, "out": 102, "order": 0}]})
    with pytest.raises(RenderError, match="starts at"):
        render(late, {"a": media["a"]}, tmp_path / "w", tmp_path / "o.mp4")


def test_render_word_sticker_pops_up(media, tmp_path):
    from cutmind import stickers
    if not stickers.available():
        pytest.skip("no colour emoji font on this machine")
    plan = _plan(stickers=[{"emoji": "\U0001F339", "word": "gulab", "start": 1.0, "end": 2.6}])
    out = render(plan, {"a": media["a"], "c": media["c"]}, tmp_path / "w", tmp_path / "o.mp4")
    assert decode_check(out)[0]
    def reddish(t):  # sticker red in the top-right corner, where the sticker sits
        f = extract_frame(out, t).astype(int)
        h, w, _ = f.shape
        c = f[: int(h * 0.3), int(w * 0.6):]
        return int(((c[..., 0] > 150) & (c[..., 1] < 90) & (c[..., 2] < 110)).sum())
    assert reddish(1.8) > reddish(0.5) + 50
    assert reddish(3.5) < reddish(1.8)
