"""Every effect / motion / colour look must VISIBLY change the picture (not just render without errors).

Regression: the "zoom" transition id once shadowed the zoom *effect*, which then silently did nothing; an
"it renders and has the right length" test didn't notice.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from cutmind.ffmpeg_utils import extract_frame
from cutmind.fx_catalog import catalog
from cutmind.plan import EditPlan
from cutmind.renderer import render

CAT = catalog()
SAMPLE_T = {"flash": 0.05, "strobe": 0.22}  # flash only at the start; strobe pulses when mod(t,0.25) > 0.2


def _render(src: Path, tmp: Path, name: str, extra: dict) -> Path:
    base = {"canvas": {"aspect_ratio": "16:9", "resolution": 360},
            "clips": [{"source": "s", "in": 0.5, "out": 3.0, "order": 0}], **extra}
    return render(EditPlan.model_validate(base), {"s": src}, tmp / f"w_{name}", tmp / f"{name}.mp4")


@pytest.fixture(scope="module")
def neutral(media, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fxv")
    return tmp, {"a": _render(media["a"], tmp, "neutral_a", {}), "b": _render(media["b"], tmp, "neutral_b", {})}

# follow / person_zoom / spotlight need a tracked path (Effect.points): pixel-tested in test_tracking.py;
# camera_move needs a measured path: round-trip tested in test_live_copy_templates.py;
# keyframes needs its points (a motion preset): pixel-tested in test_skill_library.py + test_skill_renders.py;
# grade / crop need their params (Tier 1 colour / crop): pixel-tested in tests/integration/test_tier1.py;
# impact acts on the first 0.25 s only: tested in test_editorial.py
@pytest.mark.parametrize("fx_id", [i["id"] for i in CAT["video_effect"] + CAT["motion"]
                                   if i["id"] not in ("follow", "person_zoom", "spotlight", "punch", "impact", "camera_move", "keyframes", "grade", "crop")])
def test_effect_changes_the_picture(fx_id, media, neutral):
    tmp, ref = neutral
    out = _render(media["a"], tmp, fx_id, {"effects": [{"type": fx_id, "target": -1}]})
    t = SAMPLE_T.get(fx_id, 1.2)
    a, b = extract_frame(out, t).astype(np.float32), extract_frame(ref["a"], t).astype(np.float32)
    if fx_id == "sharpen":
        lap = lambda f: cv2.Laplacian(cv2.cvtColor(f.astype(np.uint8), cv2.COLOR_RGB2GRAY), cv2.CV_64F).var()  # noqa: E731
        assert lap(a) > 1.15 * lap(b)
        return
    diff = float(np.abs(a - b).mean())
    assert diff > 2.0, f"{fx_id} barely changed the frame (mean |diff| {diff:.2f})"


@pytest.mark.parametrize("look", [i["id"] for i in CAT["color"]])
def test_colour_look_changes_the_picture(look, media, neutral):
    tmp, ref = neutral
    out = _render(media["b"], tmp, f"look_{look}", {"color": {"preset": look}})  # smooth fractal colours
    diff = float(np.abs(extract_frame(out, 1.2).astype(np.float32) - extract_frame(ref["b"], 1.2).astype(np.float32)).mean())
    assert diff > 3.0, f"{look} barely changed the frame (mean |diff| {diff:.2f})"
