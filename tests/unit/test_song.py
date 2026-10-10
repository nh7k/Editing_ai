"""Edits that move with the song: song feel, drop, beat slots, song-driven cuts / motion / text, audio requests."""

from __future__ import annotations

import numpy as np
import pytest

from cutmind.agents.analyzer import ClipAnalysis, ProjectAnalysis
from cutmind.agents.cutter import CutterAgent, song_slots
from cutmind.agents.effects import QUICK_ANIMS, EffectsAgent
from cutmind.editorial import apply_spec, compile_spec
from cutmind.intent import parse_intent
from cutmind.manual import ManualEdit, ManualError, apply_ops
from cutmind.media_gen import make_song
from cutmind.plan import ClipSegment, EditPlan
from cutmind.song import STYLE, SongProfile, analyze_song, classify_feel


@pytest.fixture(scope="module")
def songs(tmp_path_factory):
    d = tmp_path_factory.mktemp("songs")
    out = {}
    for name, bpm, drop, busy in [("slow", 70, None, False), ("fast", 150, None, True), ("drop", 128, 8.0, True)]:
        out[name] = analyze_song(make_song(d / f"{name}.m4a", bpm, 30, drop, busy), d / "w")
    return out


def test_song_feel_tempo_and_drop(songs):
    assert songs["slow"].feel == "slow" and abs(songs["slow"].tempo - 70) < 3
    assert songs["fast"].feel == "fast" and abs(songs["fast"].tempo - 150) < 4
    assert songs["drop"].drop is not None and abs(songs["drop"].drop - 8.0) < 0.1  # snapped to the real beat
    assert songs["slow"].drop is None
    assert classify_feel(80, 1.3) == "slow" and classify_feel(120, 4.0) == "fast" and classify_feel(100, 3.0) == "medium"


def test_slots_are_long_when_quiet_short_when_loud_and_the_drop_starts_a_cut(songs):
    s = songs["drop"]
    slots = song_slots(s, 20.0)
    grid = [0.0, *s.grid(25.0)]
    assert all(min(abs(b - g) for g in grid) < 0.02 for _a, b in slots[:-1])  # every cut on a real beat
    assert any(abs(a - s.drop) < 0.02 for a, _b in slots)                       # a new cut exactly on the drop
    before = [b - a for a, b in slots if b <= s.drop]
    after = [b - a for a, b in slots if a >= s.drop]
    assert np.mean(before) > 2.5 * np.mean(after), (before, after)            # quiet intro: long shots; drop: fast


def test_slow_song_cuts_slower_than_fast_song(songs):
    slow = [b - a for a, b in song_slots(songs["slow"], 15.0)]
    fast = [b - a for a, b in song_slots(songs["fast"], 15.0)]
    assert np.mean(slow) > 1.5 * np.mean(fast)


def test_song_start_moves_a_late_drop_inside_the_edit(songs):
    s = songs["drop"]
    assert s.start_for(20.0) == 0.0          # drop at 8 s already inside a 20 s edit
    start = s.start_for(9.0)                 # drop at 8 s is late in a 9 s edit: the song starts later
    sh = s.shifted(start)
    assert start > 0 and sh.drop is not None and 0.2 * 9 < sh.drop < 0.6 * 9
    assert all(b >= 0 for b in sh.beats) and abs(sh.duration - (s.duration - start)) < 0.01


def _no_speech(ctx):
    for c in ctx.analysis.clips.values():
        c.words = []
        c.motion_curve = [float(10 + (i * 7) % 30) for i in range(int(c.duration * 2))]
    return ctx


def test_song_driven_cut_and_motion(fake_project, songs):
    """Cuts follow the song's beats and energy; the strongest footage hits the drop; animations follow the energy."""
    ctx = _no_speech(fake_project("make a messi edit with nice animations, 9:16 vertical"))
    ctx.intent = apply_spec(ctx.intent, compile_spec(ctx.prompt, ctx.intent, ctx.analysis))
    ctx.song = songs["drop"]
    ctx.music_beats = list(ctx.song.beats)
    out = CutterAgent().run(ctx).output
    ctx.sections["cutter"], ctx.sections["clips"] = out, out["clips"]
    segs = [ClipSegment.model_validate(c) for c in out["clips"]]
    total = sum(s.source_duration / s.speed for s in segs)
    assert abs(total - min(30.0, 34.0)) < 1.0 or total > 15  # the edit runs with the song, not "half the footage"
    starts = np.cumsum([0.0] + [s.source_duration / s.speed for s in segs])
    drop = ctx.song.shifted(out["music_start"]).drop if out["music_start"] else ctx.song.drop
    assert min(abs(t - drop) for t in starts) < 0.05                       # a cut lands on the drop
    assert any(d["decision"] == "song-driven cuts" for d in ctx.decisions)
    eff = EffectsAgent().run(ctx).output
    words = [t for t in eff["text"] if t["kind"] == "text"]
    assert any(abs(w["start"] - drop) < 0.05 for w in words)               # a word hits the drop
    quiet = [w["style"]["animation"] for w in words if w["end"] <= drop and w["end"] - w["start"] >= 0.45]
    loud = [w["style"]["animation"] for w in words if w["start"] >= drop and w["end"] - w["start"] >= 0.45]
    assert quiet and all(a in STYLE["slow"]["anims"] for a in quiet)       # calm part: calm animations
    assert loud and all(a in STYLE["fast"]["anims"] + QUICK_ANIMS for a in loud)
    anims = [w["style"]["animation"] for w in words]
    assert all(a != b for a, b in zip(anims, anims[1:], strict=False))     # never the same animation twice in a row
    pulses = {e["target"]: e["strength"] for e in eff["effects"] if e["type"] == "pulse"}
    seg_t = list(zip(starts[:-1], starts[1:], strict=False))
    calm = [i for i, (a, b) in enumerate(seg_t) if b <= drop and ctx.song.mean_energy(a, b) < 0.45]
    assert calm and not any(i in pulses for i in calm)                     # no beat punches in the quiet intro
    assert any(e["type"] == "drift" for e in eff["effects"])               # slow drift there instead


def test_animations_differ_between_edits(fake_project, songs):
    seen = set()
    for job in ("job_a", "job_b", "job_c"):
        ctx = _no_speech(fake_project("make a messi edit with nice animations"))
        ctx.job_id = job
        ctx.intent = apply_spec(ctx.intent, compile_spec(ctx.prompt, ctx.intent, ctx.analysis))
        ctx.song, ctx.music_beats = songs["fast"], list(songs["fast"].beats)
        out = CutterAgent().run(ctx).output
        ctx.sections["cutter"], ctx.sections["clips"] = out, out["clips"]
        seen.add(tuple(t["style"]["animation"] for t in EffectsAgent().run(ctx).output["text"] if t["kind"] == "text"))
    assert len(seen) >= 2


@pytest.mark.parametrize("prompt,want", [
    ("video ki music hata ke dusra gaana lagao", {"mute": True, "music": True}),
    ("video ki voice hata do", {"mute": True, "music": False}),
    ("voice ko tej karo aur background me music daal do", {"voice_boost": True, "music": True}),
    ("music hata do", {"music": False}),
    ("music halka rakho", {"music_volume": 0.12}),
    ("music thoda tej", {"music_volume": 0.6}),
    ("mere uploaded song pe edit karo", {"use_my_song": True, "music": True}),
    ("lyrics ko text bana do", {"lyrics": True, "kinetic_text": True}),
    ('text person ke peeche likho "COLD"', {"text_behind": True}),
    ("replace the original audio with a new song", {"mute": True, "music": True}),
    ("make a ronaldo edit that is cool with nice animations", {"color_preset": None, "mute": False}),
])
def test_sound_requests_in_hinglish(prompt, want):
    it = parse_intent(prompt)
    assert {k: getattr(it, k) for k in want} == want


def test_manual_sound_controls():
    plan = EditPlan(clips=[ClipSegment(source="a", **{"in": 0}, out=3, order=0)])
    edit = ManualEdit.model_validate({"ops": [{"op": "set_audio", "music": "mine.m4a", "music_volume": 0.8,
                                               "voice_volume": 0.3, "mute": False, "music_start": 4.5}]})
    out, _ = apply_ops(plan, edit.ops, song_exists=lambda n: n == "mine.m4a")
    a = out.audio
    assert (a.music, a.music_volume, a.voice_volume, a.music_start) == ("mine.m4a", 0.8, 0.3, 4.5)
    out2, _ = apply_ops(out, ManualEdit.model_validate({"ops": [{"op": "set_audio", "no_music": True, "mute": True}]}).ops)
    assert out2.audio.music is None and out2.audio.mute
    with pytest.raises(ManualError):
        apply_ops(plan, ManualEdit.model_validate({"ops": [{"op": "set_audio", "music": "nope.mp3"}]}).ops,
                  song_exists=lambda n: False)
    t, _ = apply_ops(plan, ManualEdit.model_validate({"ops": [{"op": "add_text", "text": "COLD", "behind": True}]}).ops)
    assert t.text[0].behind


def test_song_profile_cache_roundtrip(tmp_path, songs):
    s: SongProfile = songs["slow"]
    assert s.shifted(0) is s and s.beats_per_cut() >= 2 and s.energy_at(1e6) == s.energy[-1]


_ = ClipAnalysis, ProjectAnalysis  # imported for type context of the fixtures
