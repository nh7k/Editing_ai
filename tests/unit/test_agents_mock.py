"""Each agent in mock (rule) mode, on hand-made analysis — fast, no FFmpeg."""

import json

import pytest

from cutmind.agents.audio import AudioAgent
from cutmind.agents.base import Feedback
from cutmind.agents.color import ColorAgent
from cutmind.agents.cutter import CutterAgent, Piece, chunk_piece, speech_pieces, word_cut_inside
from cutmind.agents.director import DirectorAgent
from cutmind.agents.effects import EffectsAgent
from cutmind.llm import LLMError
from cutmind.plan import FADE_IN, EditPlan


def run_chain(ctx, *names):
    agents = {"audio": AudioAgent(), "cutter": CutterAgent(), "color": ColorAgent(), "effects": EffectsAgent()}
    for n in names:
        out = agents[n].run(ctx).output
        ctx.sections[n] = out
        if n == "cutter":
            ctx.sections["clips"] = out["clips"]
    return ctx


def total(clips):
    return sum((c["out"] - c["in"]) / c["speed"] for c in clips)


# ---- Cutter ------------------------------------------------------------------------------------------
def test_cutter_keeps_everything_without_target(fake_project):
    ctx = run_chain(fake_project("just tidy it"), "cutter")
    clips = ctx.sections["cutter"]["clips"]
    assert [c["source"] for c in clips] == ["A", "B", "C"]
    assert total(clips) == pytest.approx(34.0)


def test_cutter_removes_silence_and_never_cuts_words(fake_project):
    ctx = run_chain(fake_project("remove silence"), "cutter")
    a = ctx.analysis.get("A")
    segs = [c for c in ctx.sections["cutter"]["clips"] if c["source"] == "A"]
    for c in segs:
        for s, e in a.silences:
            assert min(e, c["out"]) - max(s, c["in"]) < 0.5, "a long silence was kept"
        assert word_cut_inside(c["in"], a.words) is None and word_cut_inside(c["out"], a.words) is None
    b_segs = [c for c in ctx.sections["cutter"]["clips"] if c["source"] == "B"]
    assert len(b_segs) == 2  # B's silent gap split it in two


def test_cutter_removes_fillers(fake_project):
    pieces = speech_pieces(fake_project("tidy up").analysis.get("A"), remove_silence=True, remove_fillers=True)
    assert all(not (s < 5.3 < e) for s, e in pieces), "the 'Um' filler (5.1-5.5) must be cut out"


@pytest.mark.parametrize("target", [8, 15, 20])
def test_cutter_fits_target(fake_project, target):
    ctx = run_chain(fake_project(f"trim to {target} seconds"), "cutter")
    clips = ctx.sections["cutter"]["clips"]
    assert abs(total(clips) - target) <= max(1.0, 0.1 * target)
    assert {c["source"] for c in clips} == {"A", "B", "C"}  # fair: every clip is used


def test_cutter_budgets_transition_overlap(fake_project):
    ctx = run_chain(fake_project("15 seconds with crossfade transitions"), "cutter", "effects")
    plan = EditPlan.model_validate({"clips": ctx.sections["clips"], "transitions": ctx.sections["effects"]["transitions"]})
    assert abs(plan.total_duration() - 15) <= 1.5


def test_cutter_fast_cuts_are_short_and_ordered(fake_project):
    ctx = run_chain(fake_project("20 sec, fast cuts"), "cutter")
    clips = ctx.sections["cutter"]["clips"]
    assert len(clips) >= 8
    nonspeech = [c for c in clips if c["source"] != "A"]
    assert max(c["out"] - c["in"] for c in nonspeech) <= 1.2 * 1.4 + 0.01
    order = ["ABC".index(c["source"]) for c in clips]
    assert order == sorted(order)


def test_cutter_reverse_and_best_order(fake_project):
    rev = run_chain(fake_project("reverse order"), "cutter").sections["cutter"]["clips"]
    assert [c["source"] for c in rev] == ["C", "B", "A"]
    best = run_chain(fake_project("best moments"), "cutter").sections["cutter"]["clips"]
    assert [c["source"] for c in best] == ["A", "C", "B"]  # sorted by quality


def test_cutter_uses_duration_feedback(fake_project):
    ctx = fake_project("trim to 15s")
    base = total(CutterAgent().run(ctx).output["clips"])
    fixed = total(CutterAgent().run(ctx, [Feedback("duration", "too long", {"expected": 15, "actual": 17})]).output["clips"])
    assert fixed < base - 1.0


def test_chunking_moves_boundaries_out_of_words(fake_project):
    a = fake_project("tidy up").analysis.get("A")
    from cutmind.agents.base import ClipRef
    chunks = chunk_piece(Piece(ClipRef("A", None, "a", 0), 0.0, 2.0), 0.9, a.words)  # type: ignore[arg-type]
    for ch in chunks:
        assert word_cut_inside(ch.end, a.words) is None


def test_cutter_errors_when_nothing_left(fake_project):
    ctx = fake_project("remove silence")
    for c in ctx.analysis.clips.values():
        c.silences = [(0.0, c.duration)]
        c.words = []
    with pytest.raises(ValueError, match="silent"):
        CutterAgent().run(ctx)


# ---- Audio -------------------------------------------------------------------------------------------
def test_audio_music_and_ducking_with_speech(fake_project):
    ctx = run_chain(fake_project("add upbeat music"), "audio")
    a = ctx.sections["audio"]
    assert a["music"] and "upbeat" in a["music"]
    assert a["ducking"] is True and a["music_volume"] <= 0.35
    assert len(ctx.music_beats) > 10


def test_audio_without_music_request(fake_project):
    a = run_chain(fake_project("trim to 10s"), "audio").sections["audio"]
    assert a["music"] is None and a["ducking"] is False


def test_audio_missing_library_warns(fake_project, tmp_path):
    logs = []
    ctx = fake_project("add music")
    ctx.settings.music_dir = tmp_path / "nope"
    ctx.log = lambda ag, lvl, msg: logs.append((lvl, msg))
    a = AudioAgent().run(ctx).output
    assert a["music"] is None
    assert any(lvl == "warn" and "no tracks" in m for lvl, m in logs)


# ---- Color -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("prompt,check", [
    ("warm color", lambda c: c["warmth"] > 0.3),
    ("cool tone", lambda c: c["warmth"] < -0.3),
    ("black and white", lambda c: c["saturation"] == 0),
    ("vivid", lambda c: c["saturation"] > 1.3),
    ("trim to 10s", lambda c: c["preset"] == "none" and c["warmth"] == 0),
])
def test_color_presets(fake_project, prompt, check):
    assert check(ColorAgent().run(fake_project(prompt)).output)


def test_color_exposure_matching(fake_project):
    c = ColorAgent().run(fake_project("warm")).output
    assert c["clip_brightness"]["B"] > 0  # B is darker than the others → brightened
    assert "A" not in c["clip_brightness"] or abs(c["clip_brightness"]["A"]) < 0.05


def test_color_feedback_pushes_grade(fake_project):
    ctx = fake_project("warm color")
    base = ColorAgent().run(ctx).output["warmth"]
    stronger = ColorAgent().run(ctx, [Feedback("color_applied", "too subtle")]).output["warmth"]
    assert stronger > base


# ---- Effects -----------------------------------------------------------------------------------------
def test_effects_captions_follow_the_cut(fake_project):
    ctx = run_chain(fake_project("remove silence, add captions, 9:16"), "cutter", "effects")
    fx = ctx.sections["effects"]
    assert fx["canvas"]["aspect_ratio"] == "9:16"
    caps = [t for t in fx["text"] if t["kind"] == "caption"]
    assert len(caps) >= 3
    plan = EditPlan.model_validate({"clips": ctx.sections["clips"], **{k: fx[k] for k in ("canvas", "text", "transitions", "effects")}})
    assert caps[-1]["end"] <= plan.total_duration() + 1e-6
    assert all(a["end"] <= b["start"] + 1e-6 for a, b in zip(caps, caps[1:], strict=False))  # no overlap
    # the 2nd sentence started at 5.1s in the source, but silence was removed, so it appears earlier
    second = next(c for c in caps if "weather" in c["text"] or "Um" in c["text"])
    assert second["start"] < 5.1 - 2.0


def test_effects_transitions_title_and_fx(fake_project):
    ctx = run_chain(fake_project('fade transitions, zoom, speed ramp, blur background, title "Hello"'), "cutter", "effects")
    fx = ctx.sections["effects"]
    afters = {t["after"] for t in fx["transitions"]}
    assert {0, 1, FADE_IN} <= afters
    assert {e["type"] for e in fx["effects"]} == {"zoom", "speed_ramp", "blur_background"}
    ramp = next(e for e in fx["effects"] if e["type"] == "speed_ramp")
    assert ctx.sections["clips"][ramp["target"]]["source"] != "A"  # never ramp speech
    assert fx["canvas"]["reframe"] == "blur_pad"
    assert any(t["kind"] == "title" and t["text"] == "Hello" for t in fx["text"])


def test_effects_respects_api_overrides(fake_project):
    ctx = run_chain(fake_project("9:16 reel", options={"aspect_ratio": "1:1", "resolution": 480}), "cutter", "effects")
    assert ctx.sections["effects"]["canvas"]["aspect_ratio"] == "1:1"
    assert ctx.sections["effects"]["canvas"]["resolution"] == 480


def test_merged_plan_is_valid(fake_project):
    ctx = run_chain(fake_project("30 sec travel reel, fast cuts, warm color, add captions, remove silence, crossfade, music"),
                    "audio", "cutter", "color", "effects")
    plan = DirectorAgent.merge(ctx.sections)
    assert plan.canvas.aspect_ratio == "9:16"
    assert json.loads(json.dumps(plan.to_json()))["version"] == "1.0"


# ---- Director (intent) ---------------------------------------------------------------------------------
class BrokenLLM:
    def __init__(self):
        self.calls = 0

    def complete(self, system, user, schema=None):
        self.calls += 1
        return "sure! here is the plan: {not json"


def test_director_mock_mode_uses_rules(fake_project):
    intent, mode = DirectorAgent().understand(fake_project("trim to 15s and add captions"))
    assert mode == "rules" and intent.target_duration == 15 and intent.captions


def test_director_falls_back_on_invalid_llm_json(fake_project):
    ctx = fake_project("trim to 15s and add captions", planner_mode="local")
    llm = BrokenLLM()
    ctx.llm = llm
    intent, mode = DirectorAgent().understand(ctx)
    assert mode == "llm_fallback"
    assert llm.calls == 3  # first try + 2 retries
    assert intent.target_duration == 15


def test_agent_falls_back_on_invalid_llm_json(fake_project):
    ctx = fake_project("warm color", planner_mode="local", llm_agents="all")
    ctx.llm = BrokenLLM()
    res = ColorAgent().run(ctx)
    assert res.mode == "llm_fallback" and res.output["preset"] == "warm"


def test_llm_error_type_is_exported():
    assert issubclass(LLMError, RuntimeError)


class ScriptedLLM:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, system, user, schema=None):
        return self.reply


def test_color_llm_decision_enums_map_to_valid_values(fake_project):
    ctx = fake_project("brighter, vibrant look", planner_mode="local", llm_agents="all")
    ctx.llm = ScriptedLLM('{"preset": "vivid", "brightness": "brighter", "contrast": "unchanged", '
                          '"saturation": "higher", "warmth": "unchanged"}')
    res = ColorAgent().run(ctx)
    assert res.mode == "llm"
    assert res.output["preset"] == "vivid" and res.output["brightness"] == 0.08
    assert 1.45 < res.output["saturation"] <= 2.0


def test_effects_llm_extras_are_kept_but_reviewable(fake_project):
    """The LLM may add things nobody asked for; they stay valid in the plan (the Reviewer penalises them)."""
    ctx = run_chain(fake_project("trim to 15 seconds"), "cutter")
    ctx.settings.planner_mode = "local"
    ctx.settings.llm_agents = "all"
    ctx.llm = ScriptedLLM('{"captions": false, "transition": "wipe", "transition_seconds": 0.4, "effects": [], "title": null}')
    out = EffectsAgent().run(ctx).output
    assert any(t["type"] == "wipe" for t in out["transitions"])


def test_fillers_removed_even_without_silence_removal(fake_project):
    """Regression: the 'merge tiny gaps' step used to glue the filler back in."""
    a = fake_project("tidy up").analysis.get("A")
    pieces = speech_pieces(a, remove_silence=False, remove_fillers=True)
    assert len(pieces) == 2
    assert all(not (s < 5.3 < e) for s, e in pieces)


def test_keyword_guard_corrects_llm_misreads():
    """Seen in a real run with a 3B model: 'Cinematic look, crossfade transitions, 1080p' → LLM said warm, 720."""
    from cutmind.agents.director import reconcile
    from cutmind.intent import Intent, parse_intent

    llm = Intent(color_preset="warm", transition="crossfade", recognized=["warm look"])
    merged, wrong = reconcile(llm, parse_intent("Cinematic look, crossfade transitions, 1080p"))
    assert merged.color_preset == "cinematic" and merged.resolution == 1080 and merged.transition == "crossfade"
    assert any("color_preset" in w for w in wrong) and any("resolution" in w for w in wrong)
    same, none = reconcile(parse_intent("trim to 15s"), parse_intent("trim to 15s"))
    assert none == [] and same.target_duration == 15


def test_director_llm_mode_reports_disagreements(fake_project):
    ctx = fake_project("Reverse order, vintage, wipe transitions", planner_mode="local")
    ctx.llm = ScriptedLLM('{"color_preset": "vivid", "transition": "wipe", "recognized": ["vivid"]}')
    intent, mode = DirectorAgent().understand(ctx)
    assert mode == "llm"
    assert intent.color_preset == "vintage" and intent.order == "reverse"
    assert len(ctx.intent_disagreements) == 2


def test_evidence_gate_drops_llm_decorations():
    """Seen with Qwen2.5-1.5B: 'Clean up the audio, remove ums, landscape' came back with bw, 1080p and fades."""
    from cutmind.agents.director import reconcile
    from cutmind.intent import Intent, parse_intent

    prompt = "Clean up the audio, remove ums, landscape"
    llm = Intent(voice_cleanup=True, color_preset="bw", resolution=1080, transition="fade", aspect_ratio="16:9")
    merged, wrong = reconcile(llm, parse_intent(prompt), prompt)
    assert merged.color_preset is None and merged.resolution is None and merged.transition is None
    assert merged.voice_cleanup and merged.remove_fillers and merged.aspect_ratio == "16:9"
    assert len([w for w in wrong if "without any hint" in w]) == 3


def test_evidence_gate_keeps_supported_paraphrases():
    from cutmind.agents.director import reconcile
    from cutmind.intent import Intent, parse_intent

    prompt = "jahan koi bol nahi raha woh hissa hata do, aur blend between clips"  # ("smooth" alone is a rule now)
    llm = Intent(remove_silence=True, transition="crossfade")
    merged, wrong = reconcile(llm, parse_intent(prompt), prompt)
    assert merged.remove_silence and merged.transition == "crossfade" and wrong == []
    assert any(r.startswith("(llm)") for r in merged.recognized)


def test_evidence_gate_title_needs_real_evidence():
    from cutmind.evidence import has_evidence

    assert not has_evidence("title", "", "add subtitles")          # seen live: empty title + "subtitles"
    assert not has_evidence("title", "My Trip", "add subtitles")
    assert has_evidence("title", "Goa Trip", 'title "Goa Trip"')


@pytest.mark.parametrize("prompt,ok", [
    ("Make a 9:16 reel with warm color", False),          # seen live: 0.5B returned target_duration=9
    ("Square 1:1 black and white video", False),          # seen live: 0.5B returned target_duration=1
    ("Vertical short, beat sync cuts", False),            # "short" is a format here, not a length
    ("trim to 15 seconds", True),
    ("isko 20 second ka bana do", True),
    ("make it a bit shorter", True),
])
def test_evidence_gate_duration_needs_a_time_unit(prompt, ok):
    from cutmind.evidence import has_evidence

    assert has_evidence("target_duration", 9.0, prompt) is ok
