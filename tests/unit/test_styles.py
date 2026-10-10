"""Pro looks: animated gradient graphic tracks + grade, without touching the edit's timing."""

import numpy as np

from cutmind.ffmpeg_utils import extract_frame, probe
from cutmind.intent import parse_intent
from cutmind.plan import EditPlan
from cutmind.renderer import render
from cutmind.styles import STYLES, apply_style, public_styles


def base_plan() -> EditPlan:
    return EditPlan.model_validate({
        "canvas": {"aspect_ratio": "16:9", "resolution": 360},
        "clips": [{"source": "a", "in": 0.5, "out": 3.0, "order": 0}, {"source": "c", "in": 1.0, "out": 3.0, "order": 1}],
        "text": [{"kind": "caption", "text": "hello", "start": 0.5, "end": 1.5}],
    })


def test_apply_style_keeps_timing_and_adds_tracks():
    plan = base_plan()
    for sid in STYLES:
        styled = apply_style(plan, sid)
        assert styled.timeline() == plan.timeline() and styled.total_duration() == plan.total_duration()
        assert styled.style == sid and len(styled.overlays) >= 2
        assert all(o.end == round(plan.total_duration(), 3) for o in styled.overlays)
        assert styled.text[0].style.box_color == STYLES[sid].caption_box
    bw = EditPlan.model_validate({**plan.to_json(), "color": {"preset": "bw", "saturation": 0}})
    assert apply_style(bw, "cyan_kinetic", keep_color=True).color.saturation == 0  # explicit grade wins


def test_public_styles_and_parsing():
    assert {s["id"] for s in public_styles()} == set(STYLES)
    assert parse_intent("premium minimal look").style == "midnight_drift"
    assert parse_intent("edit like a pro").variations == 3
    assert parse_intent("give me 2 versions").variations == 2


def test_glow_frame_is_drawn_on_the_edges(media, tmp_path):
    plan = base_plan()
    plain = render(plan, {"a": media["a"], "c": media["c"]}, tmp_path / "w1", tmp_path / "plain.mp4")
    styled = render(apply_style(plan, "cyan_kinetic"), {"a": media["a"], "c": media["c"]}, tmp_path / "w2",
                    tmp_path / "cyan.mp4")
    assert abs(probe(styled).duration - probe(plain).duration) < 0.1
    f0, f1 = extract_frame(plain, 2.2).astype(int), extract_frame(styled, 2.2).astype(int)
    edge = (slice(0, 4), slice(40, 600))
    cyanish = f1[edge].mean(axis=(0, 1))
    assert cyanish[2] > 150 and cyanish[1] > 120  # bright blue/cyan band on the top edge
    assert np.abs(f1[edge] - f0[edge]).mean() > 40
