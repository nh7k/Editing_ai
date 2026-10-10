"""Editorial brain: Hinglish concepts, content classification, skill retrieval, explicit vs inferred, restraint."""

from __future__ import annotations

import numpy as np
import pytest

from cutmind.agents.analyzer import ClipAnalysis, ProjectAnalysis, Word
from cutmind.editorial import apply_spec, classify, compile_spec, concepts_in, is_adjustment, knowledge, platform_for, wants_editorial
from cutmind.ffmpeg_utils import extract_frame, run_ffmpeg
from cutmind.intent import parse_intent
from cutmind.plan import Canvas, ClipSegment, EditPlan, Effect
from cutmind.renderer import render


def clip(cid: str, dur: float, motion: float, n_words: int = 0) -> ClipAnalysis:
    words = [Word(text=f"w{i}", start=i * 0.6, end=i * 0.6 + 0.4) for i in range(n_words)]
    return ClipAnalysis(clip_id=cid, duration=dur, width=1920, height=1080, fps=30, has_audio=True, motion=motion,
                        words=words)


TALKING = ProjectAnalysis(clips={"t": clip("t", 30, 2.5, 45)})
PARTY = ProjectAnalysis(clips={"a": clip("a", 12, 18), "b": clip("b", 10, 22), "c": clip("c", 9, 15)})
SCENIC = ProjectAnalysis(clips={"a": clip("a", 12, 6), "b": clip("b", 14, 8)})


def test_knowledge_base_is_complete_and_consistent():
    kn = knowledge()
    assert len(kn["genres"]) >= 20 and len(kn["skills"]) >= 30 and len(kn["platforms"]) >= 5
    for g in kn["genres"].values():
        assert all(s in kn["skills"] for s in g["skills"]), g["id"]
    for s in kn["skills"].values():
        for f in ("name", "category", "when_to_use", "when_not_to_use", "why", "rules", "avoid"):
            assert s.get(f) is not None, (s["id"], f)


@pytest.mark.parametrize("prompt,concept", [
    ("bhai isko mast bana de", "make_it_good"), ("boring hata de", "remove_low_value"), ("party ko dhamaka bana", "high_energy"),
    ("starting 3 second killer chahiye", "strong_hook"), ("cinematic kar de but over mat kar", "restraint"),
    ("thoda shaant cinematic", "calm"), ("captions thode premium lagne chahiye", "premium_captions"),
    ("ye banda jab important baat bole tab zoom kar", "emphasis_punch"), ("music beat pe cut kar", "beat_cut"),
])
def test_desi_phrases_become_concepts(prompt, concept):
    assert concept in concepts_in(prompt)


def test_classification_from_words_and_from_footage():
    assert [g["id"] for g in classify("shaadi ka video bana")] == ["wedding"]
    assert {"party", "reel"} <= {g["id"] for g in classify("party ka reel")}
    t = classify("bhai mast bana", TALKING)
    assert t[0]["id"] == "talking_head" and "speech high" in t[0]["why"]
    assert classify("bhai mast bana", PARTY)[0]["id"] == "montage"
    assert classify("bhai mast bana", SCENIC)[0]["id"] == "travel"
    assert platform_for("insta reel bana")["id"] == "instagram_reels"


def test_explicit_wins_over_inferred_and_everything_inferred_has_a_reason():
    p = "party ka mast energetic reel insta ke liye, black and white"
    it = parse_intent(p)
    spec = compile_spec(p, it, PARTY)
    assert "color_preset" in spec.explicit
    assert not any(d.field == "color_preset" for d in spec.inferred)  # warm grade from the party skill is NOT applied
    assert all(d.reason and d.skill for d in spec.inferred)
    final = apply_spec(it, spec)
    assert final.color_preset == "bw" and final.beat_sync and final.hook_first and final.ending_peak
    assert final.transition is None and spec.limits["max_transitions"] == 0
    assert final.platform == "instagram_reels" and final.aspect_ratio == "9:16" and final.target_lufs == -14


def test_talking_footage_is_never_beat_chopped():
    p = "isko mast energetic bana do"
    spec = compile_spec(p, parse_intent(p), TALKING)
    fields = {d.field for d in spec.inferred}
    assert "beat_sync" not in fields and "fast_cuts" not in fields
    assert any("chop sentences" in u for u in spec.unknown)
    assert {"remove_silence", "emphasis_punch"} <= fields


def test_precise_requests_are_done_exactly_as_said():
    assert not wants_editorial("trim to 15 seconds", parse_intent("trim to 15 seconds"))
    assert wants_editorial("bhai mast bana", parse_intent("bhai mast bana"))


def test_adjustments_and_removals():
    assert is_adjustment("thoda dark kar") and is_adjustment("captions hata de") and not is_adjustment("party reel bana do")
    assert parse_intent("zyada dark ho gaya").brightness > 0     # too dark → brighter
    assert parse_intent("thoda dark kar").brightness < 0
    it = parse_intent("captions hata de")
    assert not it.captions and it.remove == ["captions"]


def test_emphasis_punch_moves_the_frame(tmp_path):
    src = tmp_path / "grid.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:d=3:r=30", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)])
    seg = [ClipSegment(source="g", **{"in": 0}, out=3, order=0)]
    canvas = Canvas(aspect_ratio="16:9", resolution=360)
    plain = render(EditPlan(canvas=canvas, clips=seg), {"g": src}, tmp_path / "w0", tmp_path / "p.mp4")
    pun = render(EditPlan(canvas=canvas, clips=seg, effects=[Effect(type="punch", target=0, times=[1.0])]),
                 {"g": src}, tmp_path / "w1", tmp_path / "q.mp4")
    diff = lambda t: np.abs(extract_frame(plain, t).astype(int) - extract_frame(pun, t).astype(int)).mean()  # noqa: E731
    before, on, after = diff(0.5), diff(1.15), diff(2.6)
    assert on > 8.0 and on > 4 * max(before, after), (before, on, after)  # pushed in on the word, back to normal after


@pytest.mark.parametrize("prompt,words", [
    ("make a max verstappen edit", ["MAX", "VERSTAPPEN"]),
    ("make a snowboarding edit that is cool with nice animations", ["SNOWBOARDING"]),
    ("bhai virat kohli ka edit bana do", ["VIRAT", "KOHLI"]),
])
def test_fan_edit_like_the_reference_apps(prompt, words):
    """'make a X edit' (the reference videos the user sent): beat cuts, beat punches, colour pass, kinetic words."""
    it = parse_intent(prompt)
    spec = compile_spec(prompt, it, PARTY)
    assert "fan_edit" in [g["id"] for g in spec.genres]
    final = apply_spec(it, spec)
    assert final.beat_sync and final.fast_cuts and final.color_pass and final.kinetic_text and "pulse" in final.effects
    assert final.kinetic_words == words and final.text_style == "glass" and final.transition is None
    assert final.color_preset is None  # "an edit that is cool" means good, not a blue grade


def test_colour_pass_and_kinetic_words_in_the_plan(fake_project):
    from cutmind.agents.cutter import CutterAgent
    from cutmind.agents.effects import EffectsAgent

    ctx = fake_project("make a max verstappen edit, 9:16 vertical")  # vertical: the biggest text size
    ctx.intent = apply_spec(ctx.intent, compile_spec(ctx.prompt, ctx.intent, ctx.analysis))
    ctx.music_beats = [round(0.5 * k, 3) for k in range(80)]
    for agent in (CutterAgent(), EffectsAgent()):
        out = agent.run(ctx).output
        ctx.sections[agent.name] = out
        if agent.name == "cutter":
            ctx.sections["clips"] = out["clips"]
    eff = ctx.sections["effects"]
    n = len(ctx.sections["clips"])
    bw = {e["target"] for e in eff["effects"] if e["type"] in ("mono", "silhouette", "invert_mono", "film_bw")}
    assert bw and len(bw) < n and 0 not in bw and n - 1 not in bw
    assert not any(b - a == 1 for a, b in zip(sorted(bw), sorted(bw)[1:], strict=False))  # never two in a row
    stutter = set(ctx.sections["cutter"]["moves"]["stutter"])
    assert stutter and not bw & stutter  # the 3 repeats look the same: one moment, three times
    assert stutter.issuperset({e["target"] for e in eff["effects"] if e["type"] == "impact"} & set(range(min(stutter), max(stutter))))
    words = [t for t in eff["text"] if t["kind"] == "text"]
    assert [w["text"] for w in words[:2]] == ["MAX", "VERSTAPPEN"]
    assert all(abs((w["start"] * 2) - round(w["start"] * 2)) < 1e-6 for w in words)  # on the 0.5 s beat grid
    assert any("colour pass" == d["decision"] for d in ctx.decisions)


def test_velocity_moves_keep_every_cut_on_the_beat(fake_project):
    """Stutter (one moment 3x) and a half-speed takeoff ramp, like the reference edits — and the beat grid survives."""
    from cutmind.agents.cutter import CutterAgent

    ctx = fake_project("make a snowboarding edit, 9:16 vertical")
    ctx.intent = apply_spec(ctx.intent, compile_spec(ctx.prompt, ctx.intent, ctx.analysis))
    assert ctx.intent.speed_moves and ctx.intent.impact_hits
    ctx.music_beats = [round(0.5 * k, 3) for k in range(80)]
    out = CutterAgent().run(ctx).output
    segs = out["clips"]
    st, ramp = out["moves"].get("stutter", []), out["moves"].get("ramp", [])
    assert len(st) == 4 and len(ramp) == 2, out["moves"]
    assert len({(segs[i]["in"], segs[i]["out"]) for i in st[:3]}) == 1  # the same moment three times
    assert [segs[i]["speed"] for i in ramp] == [0.5, 2.0]
    assert 0 not in st + ramp and len(segs) - 1 not in st + ramp  # never the hook or the ending
    # output time at the end of every ORIGINAL piece is still a multiple of the beat
    t, ends = 0.0, []
    for i, s in enumerate(segs):
        t += (s["out"] - s["in"]) / s["speed"]
        if i + 1 not in st[1:] + ramp[1:]:
            ends.append(t)
    assert all(abs(e * 2 - round(e * 2)) < 0.02 for e in ends[:-1]), ends


def test_talking_footage_gets_no_velocity_moves():
    p = "make a podcast edit"
    final = apply_spec(parse_intent(p), compile_spec(p, parse_intent(p), TALKING))
    assert not final.speed_moves and not final.impact_hits


def test_impact_hit_and_negative_pass_change_the_picture(tmp_path):
    src = tmp_path / "grid.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:d=2:r=30", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)])
    seg = [ClipSegment(source="g", **{"in": 0}, out=2, order=0)]
    canvas = Canvas(aspect_ratio="16:9", resolution=360)
    plain = render(EditPlan(canvas=canvas, clips=seg), {"g": src}, tmp_path / "w0", tmp_path / "p.mp4")
    hit = render(EditPlan(canvas=canvas, clips=seg, effects=[Effect(type="impact", target=0)]),
                 {"g": src}, tmp_path / "w1", tmp_path / "q.mp4")
    neg = render(EditPlan(canvas=canvas, clips=seg, effects=[Effect(type="invert_mono", target=0)]),
                 {"g": src}, tmp_path / "w2", tmp_path / "n.mp4")
    diff = lambda a, b, t: np.abs(extract_frame(a, t).astype(int) - extract_frame(b, t).astype(int)).mean()  # noqa: E731
    assert diff(plain, hit, 0.05) > 10 and diff(plain, hit, 1.2) < 3  # a hit on the cut, then the normal shot
    f = extract_frame(neg, 1.0).astype(int)
    assert np.abs(f[..., 0] - f[..., 2]).mean() < 4  # grey
    assert diff(plain, neg, 1.0) > 40                 # and inverted


def test_fast_cuts_never_straddle_a_shot_change(fake_project):
    """Footage that is already edited (many shots in one file): each fast cut shows one shot only."""
    from cutmind.agents.cutter import CutterAgent

    ctx = fake_project("make a messi edit, 9:16 vertical")
    ctx.analysis.clips["C"].scenes = [1.3, 2.9, 4.1, 7.7, 9.25]
    ctx.intent = apply_spec(ctx.intent, compile_spec(ctx.prompt, ctx.intent, ctx.analysis))
    ctx.music_beats = [round(0.5 * k, 3) for k in range(80)]
    segs = [s for s in CutterAgent().run(ctx).output["clips"] if s["source"] == "C"]
    assert segs
    for s in segs:
        assert not any(s["in"] + 1e-3 < x < s["out"] - 1e-3 for x in ctx.analysis.clips["C"].scenes), s
