"""'Original quality' export: the source's own size and frame rate, from the original files (never the 720p / 30 fps
proxies), no bitrate cap — and measured against the source, not only read from the plan."""

from __future__ import annotations

import re
import subprocess

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import wait_job

from cutmind.api import create_app
from cutmind.ffmpeg_utils import probe

pytestmark = pytest.mark.integration


def _ssim(a, b) -> float:
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(a), "-i", str(b), "-lavfi",
                        "[0:v]fps=60[x];[1:v]fps=60[y];[x][y]ssim", "-f", "null", "-"], capture_output=True, text=True)
    return float(re.search(r"All:([\d.]+)", r.stderr).group(1))


def test_original_quality_keeps_size_fps_and_detail(tmp_path, music_dir):
    src = tmp_path / "src_1080p60.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=60:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-crf", "12",
                    "-preset", "fast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)], check=True)
    with TestClient(create_app(make_settings(tmp_path / "data", music_dir))) as c:
        pid = c.post("/projects", json={"name": "quality"}).json()["id"]
        assert c.post(f"/projects/{pid}/clips", files=[("files", (src.name, src.read_bytes(), "video/mp4"))]).status_code == 201
        first = wait_job(c, c.post(f"/projects/{pid}/edit", json={"prompt": "isko 16:9 kar do"}).json()["job_id"])
        assert first["status"] == "done", first["error"]
        r = c.post(f"/projects/{pid}/edit", json={"prompt": "original quality me export karo"}).json()
        job = wait_job(c, r.get("job_id") or r["job"]["id"])
        assert job["status"] == "done", job["error"]
        plan = c.get(f"/projects/{pid}/plan").json()
        assert plan["export"]["platform"] == "original" and plan["export"]["crf"] == 17
        out = tmp_path / "data" / "projects" / pid / "output" / f"{job['id']}.mp4"
        info = probe(out)
        assert (info.width, info.height) == (1920, 1080), (info.width, info.height)
        assert abs(info.fps - 60) < 0.5, info.fps
        # near-identical to the source (the normal 720p30 render measures ~0.95 here)
        assert _ssim(src, out) > 0.99
        assert "1920x1080 60fps" in (job.get("explain") or {}).get("summary", "")
