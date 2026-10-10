"""Edit proxies: heavy sources (MJPEG / 60 fps / >720p) get a light H.264 copy with the same timeline."""

import pytest

from cutmind.ffmpeg_utils import probe, run_ffmpeg
from cutmind.plan import EditPlan
from cutmind.proxy import ensure_proxy, needs_proxy, proxy_path
from cutmind.renderer import render


@pytest.fixture(scope="module")
def heavy_clip(tmp_path_factory):
    """Like the user's camera files: 1080p, 60 fps, MJPEG in AVI, PCM audio."""
    out = tmp_path_factory.mktemp("heavy") / "cam.avi"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=60:d=6", "-f", "lavfi", "-i", "sine=f=440:d=6",
                "-c:v", "mjpeg", "-q:v", "5", "-c:a", "pcm_s16le", "-shortest", str(out)])
    return out


def test_light_sources_need_no_proxy(media):
    assert ensure_proxy(media["a"]) is None  # 1280x720 H.264 @30 is already light
    assert not proxy_path(media["a"]).exists()


def test_proxy_keeps_the_timeline(heavy_clip):
    assert needs_proxy(probe(heavy_clip))
    proxy = ensure_proxy(heavy_clip)
    p, src = probe(proxy), probe(heavy_clip)
    assert (p.width, p.height) == (1280, 720) and p.fps == 30 and p.video_codec == "h264"
    assert p.has_audio and abs(p.duration - src.duration) < 0.1
    assert ensure_proxy(heavy_clip) == proxy  # idempotent


def test_render_from_proxy_matches_plan(heavy_clip, tmp_path):
    proxy = ensure_proxy(heavy_clip)
    plan = EditPlan.model_validate({"canvas": {"aspect_ratio": "9:16", "resolution": 720},
                                    "clips": [{"source": "x", "in": 1.0, "out": 5.0, "order": 0}]})
    out = render(plan, {"x": proxy}, tmp_path / "w", tmp_path / "o.mp4")
    info = probe(out)
    assert (info.width, info.height) == (720, 1280) and abs(info.duration - 4.0) < 0.15
