"""Tier 1 tool engine: the specs, the timeline operations, the parser's hard cases and the engine's guarantees
(atomic, invariants). No rendering here — tests/integration/test_tier1.py renders every skill."""

from __future__ import annotations

from pathlib import Path

import pytest

from cutmind.plan import EditPlan
from cutmind.tools import engine, spec
from cutmind.tools.engine import ToolCtx
from cutmind.tools.parse import parse
from cutmind.tools.timeline import ToolError, isolate, remap_timed, remove_range, split_at


def plan2(text: list[dict] | None = None) -> EditPlan:
    return EditPlan.model_validate({
        "canvas": {"aspect_ratio": "16:9", "resolution": 360},
        "clips": [{"source": "a", "in": 0, "out": 6, "order": 0}, {"source": "b", "in": 0, "out": 6, "order": 1}],
        "effects": [{"type": "vignette", "target": 1}],
        "text": text or [{"kind": "text", "text": "late", "start": 8.0, "end": 9.0}],
    })


def test_specs_are_valid_and_complete():
    s = spec.load()
    assert len(s) == 105, len(s)
    assert spec.problems() == []
    for sid, x in s.items():
        assert sum(len(v) for v in x["synonyms"].values()) >= 15, sid
        assert len(x["examples"]) >= 8, sid
        assert {e["lang"] for e in x["examples"]} >= {"en", "hi", "hinglish", "typo", "vague", "multi"}, sid


def test_split_is_invisible_and_reindexes():
    p = plan2()
    q = split_at(p, 7.5)
    assert len(q.clips) == 3 and abs(q.total_duration() - p.total_duration()) < 1e-6
    # the vignette on shot 2 is now on both halves of it
    assert sorted(e.target for e in q.effects if e.type == "vignette") == [1, 2]
    assert q.text[0].start == 8.0  # text did not move


def test_remove_range_moves_later_text_and_drops_text_inside():
    p = plan2([{"kind": "text", "text": "in", "start": 2.2, "end": 2.8},
               {"kind": "text", "text": "after", "start": 8.0, "end": 9.0}])
    q = remove_range(p, 2.0, 3.0)
    assert abs(q.total_duration() - 11.0) < 1e-6
    assert [t.text for t in q.text] == ["after"] and abs(q.text[0].start - 7.0) < 1e-6


def test_isolate_snaps_instead_of_leaving_a_sliver():
    p = plan2()
    q, idx = isolate(p, 1.0, 5.9)  # 0.1 s before the cut: snapped to the cut, not a 0.1 s piece
    assert all(c.source_duration >= 0.2 for c in q.clips)
    assert abs(q.timeline()[idx[-1]].end - 6.0) < 1e-6


def test_remap_keeps_text_inside_its_shot():
    p = plan2([{"kind": "text", "text": "x", "start": 9.0, "end": 10.0}])
    data = p.to_json()
    data["transitions"] = [{"type": "crossfade", "after": 0, "duration": 1.0}]
    q = EditPlan.model_validate(remap_timed(p, data))
    # shot 2 now starts at 5.0 instead of 6.0: the text moved with it
    assert abs(q.text[0].start - 8.0) < 1e-6


@pytest.mark.parametrize("prompt,skill", [
    ("zoom mat lagao", "zoom_in"), ("music nahi chahiye", "add_music"), ("bina captions ke", "auto_captions"),
    ("don't add transitions crossfade", "crossfade"),
])
def test_negation_never_applies_the_skill(prompt, skill):
    r = parse(prompt)
    assert skill not in [c["id"] for c in r["calls"]] and skill in r["negated"], r


def test_beech_beech_me_is_intermittent_with_the_assumption_said():
    r = parse("beech beech me black and white karo")
    call = next(c for c in r["calls"] if c["id"] == "grayscale")
    assert call["time"]["mode"] == "intermittent"
    from cutmind.tools.timewin import resolve

    w = resolve(call["time"], spec.load()["grayscale"]["time_modes"], plan2())
    assert w.assumed == ["1s at a time", "every 4s"] and len(w.windows) == 3


def test_magnitude_and_direction_words():
    assert next(c for c in parse("thoda bright karo")["calls"])["params"]["amount"] == 0.06
    assert next(c for c in parse("thoda dark karo")["calls"])["params"]["amount"] == -0.06
    assert next(c for c in parse("contrast kam karo")["calls"])["params"]["amount"] < 1
    assert next(c for c in parse("music volume down 6 dB")["calls"])["params"] == {"gain_db": -6.0, "what": "music"}


def test_hindi_text_in_quotes_keeps_its_script():
    call = parse("intro lagao 'दिवाली मुबारक'")["calls"][0]
    assert call["id"] == "intro_outro" and call["params"]["text"] == "दिवाली मुबारक"


def test_unsupported_is_refused_with_three_nearest():
    r = parse("make my face look younger")
    assert not r["calls"] and len(r["unknown"][0]["nearest"]) == 3


class _Ctx(ToolCtx):
    pass


def _ctx(tmp_path: Path) -> ToolCtx:
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    for f in (a, b):
        f.write_bytes(b"")
    from cutmind.tools import invariants

    invariants._DUR_CACHE.update({str(a): 6.0, str(b): 6.0})
    return ToolCtx(sources={"a": a, "b": b}, gen_dir=tmp_path / "gen", clip_ids=["a", "b"])


def test_engine_is_atomic(tmp_path):
    """Three calls, the last one invalid: nothing is applied (the caller keeps the old version)."""
    p = plan2()
    before = p.to_json()
    with pytest.raises(ToolError):
        engine.run(p, [{"id": "grayscale"}, {"id": "zoom_in", "params": {"amount": 0.2}},
                       {"id": "trim", "params": {"start": 9, "end": 3}}], _ctx(tmp_path))
    assert p.to_json() == before


def test_engine_explains_what_it_assumed(tmp_path):
    q, applied = engine.run(plan2(), [{"id": "zoom_in", "time": {"mode": "intermittent"}}], _ctx(tmp_path))
    a = applied[0]
    assert "amount = 0.15 (default)" in a.assumed and "every 4s" in a.assumed
    assert a.adjust and all(o["call"]["id"] == "zoom_in" for o in a.adjust)
    assert abs(q.total_duration() - 12.0) < 1e-6


def test_invariant_refuses_a_builder_that_changes_the_length(tmp_path, monkeypatch):
    from cutmind.tools import engine as eng

    def bad(plan, p, when, ctx):  # noqa: ANN001, ANN202 — a broken colour tool that cuts the video
        return remove_range(plan, 0.0, 2.0)
    eng._load_builders()
    monkeypatch.setitem(eng._BUILDERS, "grayscale", bad)
    with pytest.raises(ToolError, match="changed the length"):
        eng.run(plan2(), [{"id": "grayscale"}], _ctx(tmp_path))


def test_a_split_next_to_a_transition_never_changes_the_length():
    """Found by the 30-edit run: 'glitch 5 se 6 sec' next to a 0.6 s crossfade. Shortening the crossfade to fit
    made the video 0.36 s LONGER (the invariant caught it). Now: no split there; the window widens to the cut."""
    data = plan2().to_json()
    data["transitions"] = [{"type": "crossfade", "after": 0, "duration": 0.6}]
    p = EditPlan.model_validate(data)
    with pytest.raises(ToolError):
        split_at(p, 5.0)
    q, idx = isolate(p, 1.0, 5.0)
    assert abs(q.total_duration() - p.total_duration()) < 1e-6 and idx
