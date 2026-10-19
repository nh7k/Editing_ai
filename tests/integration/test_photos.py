"""Photos as clips, end to end through the API: upload (EXIF rotation, size), a broken photo, the photo recipe as the
FIRST chat message, and the claude.ai connector page (only on this laptop)."""

from __future__ import annotations

import io

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import wait_job
from PIL import Image, ImageDraw

from cutmind.api import create_app

pytestmark = pytest.mark.integration


def _jpg(w: int, h: int, color: tuple[int, int, int], orientation: int | None = None) -> bytes:
    im = Image.new("RGB", (w, h), color)
    ImageDraw.Draw(im).rectangle([w // 4, h // 4, w * 3 // 4, h * 3 // 4], fill=(240, 240, 240))
    buf = io.BytesIO()
    if orientation:
        ex = im.getexif()
        ex[0x0112] = orientation
        im.save(buf, "JPEG", exif=ex, quality=92)
    else:
        im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


@pytest.fixture(scope="module")
def client(tmp_path_factory, music_dir):
    with TestClient(create_app(make_settings(tmp_path_factory.mktemp("photos"), music_dir))) as c:
        yield c


def test_photos_upload_upright_and_a_broken_one_is_refused(client):
    pid = client.post("/projects", json={"name": "photos"}).json()["id"]
    r = client.post(f"/projects/{pid}/clips", files=[
        ("files", ("phone.jpg", _jpg(1600, 1200, (30, 60, 120), orientation=6), "image/jpeg")),  # shot upright
        ("files", ("wide.png", _jpg(1280, 720, (120, 40, 40)), "image/png"))])
    assert r.status_code == 201, r.text
    clips = {c["filename"]: c for c in r.json()["clips"]}
    assert (clips["phone.jpg"]["width"], clips["phone.jpg"]["height"]) == (1200, 1600)  # EXIF applied
    assert (clips["wide.png"]["width"], clips["wide.png"]["height"]) == (1280, 720)
    assert abs(clips["phone.jpg"]["duration"] - 5.0) < 0.1
    bad = client.post(f"/projects/{pid}/clips", files=[("files", ("broken.jpg", b"not a photo", "image/jpeg"))])
    assert bad.status_code == 400 and "photo" in bad.json()["error"]["message"]


def test_photo_recipe_is_the_first_message(client):
    pid = client.post("/projects", json={"name": "car photos"}).json()["id"]
    files = [("files", (f"car{k}.jpg", _jpg(1080, 1920, c), "image/jpeg")) for k, c in ((1, (20, 30, 80)), (2, (80, 20, 30)))]
    assert client.post(f"/projects/{pid}/clips", files=files).status_code == 201
    r = client.post(f"/projects/{pid}/edit", json={"prompt": "in photos se cinematic edit banao camera push in ke saath"})
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json().get("job_id") or r.json()["job"]["id"])
    assert job["status"] == "done", job["error"]
    plan = client.get(f"/projects/{pid}/plan").json()
    sources = [c["source"] for c in sorted(plan["clips"], key=lambda c: c["order"])]
    assert len(sources) >= 4 and all(a != b for a, b in zip(sources, sources[1:]))  # the photos take turns
    assert all(any(e["type"] == "keyframes" and e["target"] == i for e in plan["effects"]) for i in range(len(sources)))
    assert plan["color"]["preset"] == "cinematic" and plan["audio"]["music"]
    assert not any(e["type"] in ("film_bw", "impact") for e in plan["effects"])  # not the director's fan edit


def test_connector_url_is_only_for_this_laptop(client, tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    r = client.get("/connect/claude").json()
    assert r["running"] is False and r["url"] is None and "start_remote.py" in r["start"]
    (tmp_path / "CutMind").mkdir()
    (tmp_path / "CutMind" / "connector_url.txt").write_text("https://x.trycloudflare.com/secret/mcp")
    assert client.get("/connect/claude").json()["url"] == "https://x.trycloudflare.com/secret/mcp"
    with TestClient(client.app, client=("192.168.1.20", 5000)) as lan:  # another device on the Wi-Fi
        assert lan.get("/connect/claude").status_code == 403
