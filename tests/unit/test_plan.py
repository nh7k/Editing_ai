"""Edit Plan validation and timeline maths."""

import pytest
from pydantic import ValidationError

from cutmind.plan import FADE_IN, FADE_OUT, Canvas, EditPlan


def seg(src: str, a: float, b: float, order: int, speed: float = 1.0) -> dict:
    return {"source": src, "in": a, "out": b, "order": order, "speed": speed}


def test_minimal_plan_defaults_and_roundtrip():
    plan = EditPlan.model_validate({"clips": [seg("x", 0, 5, 0)]})
    assert plan.version == "1.0"
    assert plan.canvas.size == (1280, 720)
    data = plan.to_json()
    assert data["clips"][0]["in"] == 0  # serialised with the JSON field name "in"
    assert EditPlan.model_validate(data) == plan


@pytest.mark.parametrize("aspect,res,size", [("9:16", 720, (720, 1280)), ("1:1", 1080, (1080, 1080)),
                                             ("16:9", 480, (854, 480)), ("16:9", 1080, (1920, 1080))])
def test_canvas_sizes_are_even(aspect, res, size):
    c = Canvas(aspect_ratio=aspect, resolution=res)
    assert c.size == size
    assert all(v % 2 == 0 for v in c.size)


@pytest.mark.parametrize("bad,match", [
    ({"clips": []}, "at least 1"),
    ({"clips": [seg("x", 3, 3.1, 0)]}, "at least 0.2s"),
    ({"clips": [seg("x", 0, 2, 0), seg("y", 0, 2, 0)]}, "orders must be unique"),
    ({"clips": [seg("x", 0, 2, 0, speed=9)]}, "less than or equal to 4"),
    ({"version": "2.0", "clips": [seg("x", 0, 2, 0)]}, "unsupported plan version"),
    ({"clips": [seg("x", 0, 2, 0)], "canvas": {"aspect_ratio": "4:3"}}, "aspect_ratio"),
    ({"clips": [seg("x", 0, 2, 0), seg("y", 0, 2, 1)], "transitions": [{"type": "fade", "after": 1}]}, "no following"),
    ({"clips": [seg("x", 0, 2, 0), seg("y", 0, 2, 1)], "transitions": [{"type": "fade", "after": 0, "duration": 1.5}]},
     "longer than half"),
    ({"clips": [seg("x", 0, 2, 0)], "text": [{"kind": "caption", "text": "hi", "start": 2.5, "end": 3}]}, "outside the video"),
    ({"clips": [seg("x", 0, 2, 0)], "text": [{"kind": "caption", "text": "hi", "start": 1, "end": 0.5}]}, "end must be after"),
    ({"clips": [seg("x", 0, 2, 0)], "effects": [{"type": "zoom", "target": 3}]}, "only 1"),
    ({"clips": [seg("x", 0, 2, 0)], "color": {"saturation": 5}}, "saturation"),
    ({"clips": [seg("x", 0, 2, 0)], "color": {"clip_brightness": {"x": 0.9}}}, "clip_brightness"),
    ({"clips": [seg("x", 0, 2, 0)], "surprise": 1}, "Extra inputs"),
])
def test_invalid_plans_rejected(bad, match):
    with pytest.raises(ValidationError, match=match):
        EditPlan.model_validate(bad)


def test_timeline_with_speed_and_transitions():
    plan = EditPlan.model_validate({
        "clips": [seg("a", 0, 4, 0), seg("b", 2, 6, 1, speed=2.0), seg("c", 0, 3, 2)],
        "transitions": [{"type": "crossfade", "after": 0, "duration": 0.5},
                        {"type": "fade", "after": FADE_IN, "duration": 0.3},
                        {"type": "fade", "after": FADE_OUT, "duration": 0.3}],
    })
    tl = plan.timeline()
    assert [round(e.duration, 3) for e in tl] == [4.0, 2.0, 3.0]
    assert tl[1].start == pytest.approx(3.5)  # overlaps the first segment by 0.5s
    assert tl[2].start == pytest.approx(5.5)  # no overlap between b and c
    assert plan.total_duration() == pytest.approx(8.5)
    assert plan.source_to_output("b", 4.0) == pytest.approx(4.5)
    assert plan.source_to_output("b", 7.0) is None


def test_speed_ramp_shortens_segment():
    plan = EditPlan.model_validate({"clips": [seg("a", 0, 4, 0)], "effects": [{"type": "speed_ramp", "target": 0, "strength": 2}]})
    assert plan.total_duration() == pytest.approx(2 + 1)
