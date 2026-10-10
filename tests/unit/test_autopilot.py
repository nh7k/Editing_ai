"""Auto edit ("mast sa edit kar do"), smart arrange of messy uploads, hook shot, recording-time parsing."""

from datetime import datetime, timezone

import pytest

from cutmind.agents.analyzer import recording_time
from cutmind.agents.cutter import CutterAgent
from cutmind.agents.director import autopilot, reconcile
from cutmind.intent import Intent, parse_intent


def _ts(*a):
    return datetime(*a, tzinfo=timezone.utc).timestamp()


# ---- prompt understanding ------------------------------------------------------------------------------
@pytest.mark.parametrize("prompt", ["mast sa edit kar do", "make it look amazing", "badhiya reel bana do",
                                    "edit kar do", "jhakaas video bana do", "you decide, surprise me",
                                    "auto edit this", "khud se accha sa edit kar do"])
def test_vague_creative_prompts_turn_on_auto_edit(prompt):
    it = parse_intent(prompt)
    assert it.auto and it.order == "smart" and not it.is_empty()


@pytest.mark.parametrize("prompt", ["trim to 15 seconds", "reverse order", "asdf qwerty", "edit like a pro, 15 seconds",
                                    "cinematic look with captions", "remove silence"])
def test_specific_prompts_do_not_turn_on_auto_edit(prompt):
    assert not parse_intent(prompt).auto


@pytest.mark.parametrize("prompt", ["ulti sidhi raw footage hai, arrange kar do", "ulta sidha hai sab, sahi order me laga do",
                                    "sort the clips", "put them in the right order", "clips are jumbled"])
def test_messy_footage_prompts_ask_for_smart_order_not_reverse(prompt):
    assert parse_intent(prompt).order == "smart"


def test_ulta_alone_is_still_reverse():
    assert parse_intent("ulta kar do").order == "reverse"


def test_llm_cannot_switch_on_auto_edit_without_a_hint():
    llm = Intent(auto=True, recognized=["x"])
    merged, wrong = reconcile(llm, parse_intent("trim to 15 seconds"), "trim to 15 seconds")
    assert not merged.auto and any(w.startswith("auto") for w in wrong)
    merged, _ = reconcile(Intent(auto=True, recognized=["x"]), parse_intent("isko thik kar do"), "isko thik kar do")
    assert merged.auto


# ---- recording time ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("name,created,expected", [
    ("20260930151012.avi", None, _ts(2026, 9, 30, 15, 10, 12)),
    ("IMG_20260930_151641.mp4", None, _ts(2026, 9, 30, 15, 16, 41)),
    ("PXL_20250102_080910123.mp4", None, _ts(2025, 1, 2, 8, 9, 10)),
    ("VID-20260930-WA0012.mp4", None, _ts(2026, 9, 30) + 12),
    ("clip.mp4", "2026-05-01T10:00:00.000000Z", _ts(2026, 5, 1, 10)),
    ("clip.mp4", None, None),
    ("holiday 2026.mp4", None, None),  # a year alone is not a date
])
def test_recording_time(name, created, expected):
    assert recording_time(name, created) == expected


# ---- cutter: smart order + hook -------------------------------------------------------------------------------
def _with_times(ctx, times, curves=None):
    ctx.analysis = ctx.analysis.model_copy(deep=True)
    for cid, t in times.items():
        ctx.analysis.clips[cid].recorded_at = t
    for cid, c in (curves or {}).items():
        ctx.analysis.clips[cid].motion_curve = c
    return ctx


def test_smart_order_follows_filming_time(fake_project):
    ctx = _with_times(fake_project("arrange the clips"), {"A": 300.0, "B": 100.0, "C": 200.0})
    clips = CutterAgent().run(ctx).output["clips"]
    seen = list(dict.fromkeys(c["source"] for c in clips))
    assert seen == ["B", "C", "A"]


def test_smart_order_keeps_upload_order_without_times(fake_project):
    clips = CutterAgent().run(fake_project("arrange the clips")).output["clips"]
    assert list(dict.fromkeys(c["source"] for c in clips)) == ["A", "B", "C"]


def test_auto_edit_opens_with_the_most_eye_catching_silent_moment(fake_project):
    ctx = fake_project("mast sa edit kar do")
    curve_c = [1.0] * 24
    curve_c[12:16] = [30.0, 32.0, 31.0, 29.0]  # big movement at 6-8 s of clip C
    ctx = _with_times(ctx, {}, {"A": [40.0] * 23 + [1.0] * 5, "B": [2.0] * 16, "C": curve_c})
    ctx.intent = autopilot(ctx, ctx.intent)  # as the Director does after analysis
    before = sum(c.duration for c in ctx.analysis.clips.values())
    out = CutterAgent().run(ctx).output["clips"]
    first = out[0]
    # A moves more while someone talks (never chopped); its quiet tail is still. C's peak wins
    assert first["source"] == "C" and first["in"] == pytest.approx(6.0) and first["out"] == pytest.approx(8.0)
    kept = sum(c["out"] - c["in"] for c in out)
    assert kept <= before
    # the hook was moved, not duplicated: no two segments overlap in the source
    spans = sorted((c["source"], c["in"], c["out"]) for c in out)
    for (s1, _a1, e1), (s2, a2, _e2) in zip(spans, spans[1:], strict=False):
        assert s1 != s2 or a2 >= e1 - 1e-6


# ---- autopilot -----------------------------------------------------------------------------------------------
def test_autopilot_talking_video_gets_captions_and_keeps_sentences(fake_project):
    ctx = fake_project("mast sa edit kar do")
    it = autopilot(ctx, ctx.intent)
    assert it.captions and it.remove_silence and it.remove_fillers and it.music and it.music_mood == "calm"
    assert it.effects == ["zoom"] and it.color_preset == "vivid" and it.order == "smart"
    assert it.transition is None and not it.fast_cuts  # jump cuts on speech, no slow cross-fades
    assert any(r.startswith("auto:") for r in it.recognized)


def test_autopilot_action_montage_without_speech(fake_project):
    """Already-cut action footage (a scene change every 2 s): fast cuts on the beat."""
    ctx = fake_project("mast sa edit kar do")
    ctx.analysis = ctx.analysis.model_copy(deep=True)
    for c in ctx.analysis.clips.values():
        c.words = []
        c.scenes = [round(t * 2.0, 1) for t in range(1, int(c.duration / 2))]
    it = autopilot(ctx, ctx.intent)
    assert not it.captions and it.fast_cuts and it.beat_sync and it.music_mood == "upbeat"
    assert it.transition is None  # hard cuts on the beat: dozens of cross-fades were slow and mushy


def test_autopilot_scenic_footage_lets_shots_breathe(fake_project):
    """Drone / travel shots without cuts: ~2.5 s shots, each place together, calm music — not 0.5 s ping-pong
    (what the user's trip footage got, seen when testing the app as a noob user)."""
    ctx = fake_project("bhai isko accha sa bana do insta pe dalna hai")
    ctx.analysis = ctx.analysis.model_copy(deep=True)
    for c in ctx.analysis.clips.values():
        c.words, c.scenes = [], []
    it = autopilot(ctx, ctx.intent)
    assert not it.fast_cuts and it.cut_length == 2.5 and "cut_length" in it.inferred_fields
    assert it.order == "original" and it.music_mood == "calm"


def test_autopilot_action_words_win_on_scenic_footage(fake_project):
    ctx = fake_project("full josh wala edit kar do")
    ctx.analysis = ctx.analysis.model_copy(deep=True)
    for c in ctx.analysis.clips.values():
        c.words, c.scenes = [], []
    assert autopilot(ctx, ctx.intent).fast_cuts


def test_autopilot_few_short_silent_clips_get_soft_transitions(fake_project):
    ctx = fake_project("mast sa edit kar do")
    ctx.analysis = ctx.analysis.model_copy(deep=True)
    for c in ctx.analysis.clips.values():
        c.words, c.duration = [], 4.0
    it = autopilot(ctx, ctx.intent)
    assert it.transition == "crossfade" and not it.fast_cuts


def test_autopilot_never_overrides_what_the_user_said(fake_project):
    ctx = fake_project("mast sa edit kar do, black and white, no music, glitch effect, 20 seconds")
    it = autopilot(ctx, ctx.intent)
    assert it.color_preset == "bw" and it.effects == ["glitch"] and it.target_duration == 20
    assert not it.music and "no music" in it.recognized


def test_silent_track_loudness_survives_the_analysis_cache():
    # regression (user's 4K upload): a silent audio track measures -inf LUFS, the JSON cache stored null, and
    # every later job failed with "Clip analysis failed: loudness.lufs Input should be a valid number"
    from cutmind.agents.analyzer import ClipAnalysis

    a = ClipAnalysis(clip_id="x", duration=1, width=1, height=1, fps=1, has_audio=True,
                     loudness={"lufs": float("-inf"), "true_peak": float("-inf")})
    assert ClipAnalysis.model_validate_json(a.model_dump_json()).loudness == {"lufs": -99.0, "true_peak": -99.0}


def test_autopilot_keeps_a_timed_zoom_timed(fake_project):
    # regression (live E2E on the user's footage): "mast reel ... starting ke 3 sec zoom" got a whole-video zoom
    # from the autopilot on top of the timed one, and the reviewer failed timed_effects in every round
    ctx = fake_project("mast reel bana, starting ke 3 sec zoom ho")
    it = autopilot(ctx, ctx.intent)
    assert it.effects == [] and [t.effect for t in it.timed_effects] == ["zoom"]
