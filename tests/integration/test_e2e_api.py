"""End-to-end: real API, real agents (mock planner), real FFmpeg renders, independent verification.

Upload 3 generated clips once, run 8 prompts, verify every output with ffprobe + frame analysis.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from conftest import make_settings
from fastapi.testclient import TestClient
from helpers import band_change, center_stats, contact_sheet, download_output, long_silences, media_facts, rerender_variant, save_results, wait_job

from cutmind.api import create_app
from cutmind.ffmpeg_utils import extract_frame, probe
from cutmind.intent import parse_intent
from cutmind.plan import EditPlan

pytestmark = pytest.mark.integration
MODE = os.environ.get("E2E_PLANNER_MODE", "mock")
RESULTS: list[dict[str, Any]] = []


@pytest.fixture(scope="module")
def env(tmp_path_factory, media, music_dir):
    data = tmp_path_factory.mktemp("e2e_data")
    settings = make_settings(data, music_dir, planner_mode=MODE)
    app = create_app(settings)
    with TestClient(app) as client:
        pid = client.post("/projects", json={"name": "E2E travel"}).json()["id"]
        files = [("files", (p.name, p.read_bytes(), "video/mp4")) for p in (media["a"], media["b"], media["c"])]
        r = client.post(f"/projects/{pid}/clips", files=files)
        assert r.status_code == 201, r.text
        clips = r.json()["clips"]
        assert len(clips) == 3
        # map clip id -> stored file path (via the DB, the API never exposes paths)
        db = app.state.db
        sources = {c["id"]: Path(db.get_clip(c["id"])["path"]) for c in clips}
        c_id = next(c["id"] for c in clips if c["filename"] == media["c"].name)
        yield {"client": client, "pid": pid, "sources": sources, "settings": settings, "work": data, "c_id": c_id}
    save_results(f"e2e_{MODE}", RESULTS)


def run_prompt(env, key: str, prompt: str, **opts: Any) -> tuple[dict, Path, EditPlan, dict]:
    client, pid = env["client"], env["pid"]
    r = client.post(f"/projects/{pid}/edit", json={"prompt": prompt, **opts})
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["job_id"])
    assert job["status"] == "done", f"job failed: {job['error']}\n" + "\n".join(x["msg"] for x in job["logs"][-15:])
    out = download_output(client, pid, env["work"] / f"{key}.mp4")
    plan = EditPlan.model_validate(client.get(f"/projects/{pid}/plan").json())
    facts = media_facts(out)
    assert facts["plays"], facts["decode_errors"]
    assert facts["has_audio"]
    assert (facts["width"], facts["height"]) == plan.canvas.size
    assert abs(facts["duration"] - plan.total_duration()) <= 0.35
    # a prompt without a length (and nothing that removes material) must not shorten the video —
    # regression: a small LLM read "9:16" as 9 seconds and "1:1" as 1 second
    asked = parse_intent(prompt)
    if not (asked.target_duration or asked.fast_cuts or asked.remove_silence or asked.remove_fillers
            or asked.slow_motion or asked.remove_idle or asked.auto or "speed_ramp" in asked.effects):
        assert facts["duration"] >= 30, f"video was shortened without being asked: {facts['duration']}s"
    contact_sheet(out, f"{MODE}_{key}")
    row = {"key": key, "prompt": prompt, "mode": MODE, "job_id": job["id"], "match_percent": job["match_percent"],
           # a single clear change after an edit is made by the skills (no director review; measured by verify)
           "agent_scores": (job.get("review") or {}).get("agent_scores"),
           "failed_checks": [c["name"] for c in (job.get("review") or {}).get("checks", []) if not c["passed"]],
           "route": "skills" if (job.get("explain") or {}).get("tools") is not None else "director",
           "rounds": len(job.get("history", [])), "modes": job.get("modes"), "segments": len(plan.clips),
           "captions": sum(t.kind == "caption" for t in plan.text), "transitions": len(plan.transitions),
           "music": plan.audio.music, "color_preset": plan.color.preset, **facts, "extra": {}}
    RESULTS.append(row)
    return job, out, plan, row


def test_trim_to_15s(env):
    job, out, plan, row = run_prompt(env, "trim15", "Trim to 15 seconds")
    assert abs(row["duration"] - 15) <= 1.5
    assert (row["width"], row["height"]) == (1280, 720)
    assert len({s.source for s in plan.clips}) == 3


def test_remove_silence(env):
    job, out, plan, row = run_prompt(env, "silence", "Remove silence")
    gaps = long_silences(out, 1.0)
    row["extra"]["long_silences"] = gaps
    assert not gaps, f"silences left in output: {gaps}"
    assert row["duration"] < 34.5 - 4  # ~2.9 + 2.7 + 1.4 + 2.5 s of silence existed in the sources


def test_add_captions(env):
    job, out, plan, row = run_prompt(env, "captions", "New edit, add captions")  # a fresh edit, not a change to the last one
    caps = [t for t in plan.text if t.kind == "caption"]
    assert len(caps) >= 3
    variant = rerender_variant(plan, env["sources"], env["work"] / "nocap", env["settings"].music_dir, text=[])
    changes = []
    for c in caps[:3]:
        t = (c.start + c.end) / 2
        changes.append(band_change(extract_frame(out, t), extract_frame(variant, t), 0.62, 0.99))
    row["extra"]["caption_band_change"] = [round(x, 4) for x in changes]
    assert all(x > 0.02 for x in changes), f"captions not visible: {changes}"
    words = " ".join(c.text.lower() for c in caps)
    assert "mountains" in words or "weather" in words  # the narration was really transcribed


def test_9x16_reel_warm(env):
    job, out, plan, row = run_prompt(env, "reel_warm", "Make a 9:16 reel with warm color")
    assert (row["width"], row["height"]) == (720, 1280)
    neutral = rerender_variant(plan, env["sources"], env["work"] / "neutral", env["settings"].music_dir,
                               color={"preset": "none"})
    tl = plan.timeline()
    t = tl[0].start + tl[0].duration / 2
    g, n = center_stats(extract_frame(out, t)), center_stats(extract_frame(neutral, t))
    warm_shift = (g["r"] - g["b"]) - (n["r"] - n["b"])
    row["extra"]["warm_shift_r_minus_b"] = round(warm_shift, 2)
    assert warm_shift >= 4, f"warm grade not measurable: {warm_shift:.2f}"


def test_fast_cuts_with_music(env):
    job, out, plan, row = run_prompt(env, "fast_music", "Fast cuts with upbeat music, 20 seconds")
    assert abs(row["duration"] - 20) <= 2.0
    assert plan.audio.music and "upbeat" in plan.audio.music
    durs = sorted(e.duration for e in plan.timeline())
    row["extra"]["median_segment_s"] = round(durs[len(durs) // 2], 2)
    assert len(plan.clips) >= 8 and durs[len(durs) // 2] <= 2.0
    assert row["mean_volume"] is not None and row["mean_volume"] > -35


def test_fade_transitions(env):
    job, out, plan, row = run_prompt(env, "fades", "New edit, add fade transitions")
    assert any(t.after >= 0 for t in plan.transitions)
    first = center_stats(extract_frame(out, 0.02))["luma"]
    mid = center_stats(extract_frame(out, 1.5))["luma"]
    row["extra"]["fade_luma_first_vs_1_5s"] = [round(first, 1), round(mid, 1)]
    assert first < 25 and mid > first + 20


def test_travel_reel_full_prompt(env):
    job, out, plan, row = run_prompt(env, "travel", "make a 30 sec travel reel, fast cuts, warm color, add captions, remove silence")
    assert (row["width"], row["height"]) == (720, 1280)
    assert row["duration"] <= 31.5
    assert row["captions"] >= 3
    gaps = long_silences(out, 1.0)
    row["extra"]["long_silences"] = gaps
    assert not gaps


def test_square_bw_zoom_title(env):
    job, out, plan, row = run_prompt(env, "square_bw", 'Square 1:1 black and white video with zoom effect and title "Goa Trip"')
    assert (row["width"], row["height"]) == (720, 720)
    assert any(t.kind == "title" and t.text == "Goa Trip" for t in plan.text)
    assert any(e.type == "zoom" for e in plan.effects)
    chroma = center_stats(extract_frame(out, min(4.0, row["duration"] - 0.5)))["chroma"]
    row["extra"]["center_chroma"] = round(chroma, 2)
    assert chroma < 12


def test_api_overrides_resolution(env):
    job, out, plan, row = run_prompt(env, "override_480", "Trim to 10 seconds", aspect_ratio="1:1", resolution=480)
    assert (row["width"], row["height"]) == (480, 480)


def test_feedback_moves_the_scoreboard(env):
    client, pid = env["client"], env["pid"]
    job_id = client.get(f"/projects/{pid}").json()["last_job_id"]
    before = {a["name"]: a["total_points"] for a in client.get("/agents/scoreboard").json()["agents"]}
    r = client.post(f"/jobs/{job_id}/feedback", json={"rating": "up"})
    assert r.status_code == 200 and r.json()["points_delta"] == 5
    r = client.post(f"/jobs/{job_id}/feedback", json={"rating": "down", "agent": "color", "comment": "too grey"})
    assert r.status_code == 200
    after = {a["name"]: a for a in client.get("/agents/scoreboard").json()["agents"]}
    assert after["cutter"]["total_points"] == before["cutter"] + 5
    assert after["color"]["total_points"] == before["color"] + 5 - 5
    assert any("too grey" in lsn["text"] for lsn in after["color"]["recent_lessons"])


@pytest.mark.parametrize("key,prompt,check", [
    ("cinematic_1080", "Cinematic look, crossfade transitions, 1080p",
     lambda row, plan: min(row["width"], row["height"]) == 1080 and plan.color.preset == "cinematic"
     and any(t.type == "crossfade" for t in plan.transitions)),
    ("beat_shake", "Vertical short, beat sync cuts, chill music, shake",
     lambda row, plan: (row["width"], row["height"]) == (720, 1280) and plan.audio.beat_sync
     and plan.audio.music is not None and "calm" in plan.audio.music and any(e.type == "shake" for e in plan.effects)),
    ("highlights_ramp_blur", "Highlights only, speed ramp, blur background",
     lambda row, plan: plan.canvas.reframe == "blur_pad" and any(e.type == "speed_ramp" for e in plan.effects)),
    ("cleanup_fillers", "Clean up the audio, remove ums, landscape",
     lambda row, plan: plan.audio.voice_cleanup and (row["width"], row["height"]) == (1280, 720)
     and sum(s.source == plan.ordered_clips()[0].source for s in plan.clips) >= 2),  # the spoken "Um," was cut out
    ("reverse_vintage_wipe", "Reverse order, vintage, wipe transitions",
     lambda row, plan: plan.color.preset == "vintage" and any(t.type == "wipe" for t in plan.transitions)),
])
def test_more_sample_prompts(env, key, prompt, check):
    # each sample is its own edit: on one project a bare follow-up now (correctly) keeps the previous edit's length
    job, out, plan, row = run_prompt(env, key, "New edit, " + prompt)
    assert check(row, plan), f"{key}: plan does not reflect the prompt"
    assert job["match_percent"] >= 80, job["review"]


def test_ops_rotate_mirror_60fps(env):
    job, out, plan, row = run_prompt(env, "rotate_mirror", "rotate 90 and mirror it, 60 fps")
    assert (plan.canvas.rotate, plan.canvas.flip) == (90, "h")
    assert (row["width"], row["height"]) == (720, 1280)  # rotated landscape footage → portrait canvas
    assert abs(row["fps"] - 60) < 0.5


def test_ops_reverse_sepia_vignette(env):
    job, out, plan, row = run_prompt(env, "reverse_sepia", "play the video backwards with sepia and vignette")
    assert all(s.reverse for s in plan.clips) and max(s.source_duration for s in plan.clips) <= 8.3
    assert row["duration"] >= 30  # whole material, just backwards
    r, g, b = center_stats(extract_frame(out, 5.0))["r"], center_stats(extract_frame(out, 5.0))["g"], center_stats(extract_frame(out, 5.0))["b"]
    row["extra"]["center_rgb"] = [round(r), round(g), round(b)]
    assert r > g > b


def test_ops_mute_music_audio_fade_watermark(env):
    job, out, plan, row = run_prompt(env, "mute_wm", 'mute the sound, add calm music, fade the audio in and out, watermark "@cutmind"')
    assert plan.audio.mute and plan.audio.music and plan.audio.fade_in > 0
    assert any(t.kind == "watermark" and t.text == "@cutmind" for t in plan.text)
    variant = rerender_variant(plan, env["sources"], env["work"] / "nowm", env["settings"].music_dir, text=[])
    a, b = extract_frame(out, 3.0), extract_frame(variant, 3.0)
    h, w = a.shape[:2]
    corner = (slice(0, int(h * 0.12)), slice(int(w * 0.6), w))
    changed = float((abs(a[corner].astype(int) - b[corner].astype(int)).max(axis=2) > 30).mean())
    row["extra"]["watermark_corner_change"] = round(changed, 4)
    assert changed > 0.02


def test_ops_remove_idle_export_gif_mp3(env):
    job, out, plan, row = run_prompt(env, "idle_gif_mp3", "remove idle parts, export gif and mp3")
    c_kept = sum(s.source_duration for s in plan.clips if s.source == env["c_id"])
    row["extra"]["clip_c_kept_s"] = round(c_kept, 2)
    assert c_kept < 6  # clip C: 8 of its 12 s are static colour / bars
    client, pid = env["client"], env["pid"]
    gif = client.get(f"/projects/{pid}/output?format=gif")
    mp3 = client.get(f"/projects/{pid}/output?format=mp3")
    assert gif.status_code == 200 and gif.headers["content-type"] == "image/gif" and gif.content[:3] == b"GIF"
    assert mp3.status_code == 200 and mp3.headers["content-type"] == "audio/mpeg" and len(mp3.content) > 20000
    assert job["output"]["extras"] == ["gif", "mp3"]


def test_ops_louder_sharpen_gamma(env):
    job, out, plan, row = run_prompt(env, "louder_sharp", "make it louder, sharpen, gamma 1.4, 20 seconds")
    assert plan.audio.target_lufs == -11 and plan.color.gamma == 1.4 and any(e.type == "sharpen" for e in plan.effects)
    assert abs(row["lufs"] - (-11)) <= 2.5


def test_studio_three_versions_choose_filmstrip_waveform(env):
    client, pid = env["client"], env["pid"]
    styles = client.get("/styles").json()["styles"]
    assert len(styles) == 3 and all(len(s["colors"]) >= 3 for s in styles)
    r = client.post(f"/projects/{pid}/edit", json={"prompt": "edit like a pro, 12 seconds, add captions", "variations": 3})
    job = wait_job(client, r.json()["job_id"])
    assert job["status"] == "done", job["error"]
    vs = job["variations"]
    assert [v["index"] for v in vs] == [0, 1, 2] and sorted({v["style"] for v in vs}) == sorted(s["id"] for s in styles)
    assert [v["match_percent"] for v in vs] == sorted((v["match_percent"] for v in vs), reverse=True)
    assert vs[0]["chosen"] and all(abs(v["duration"] - 12) <= 1.5 for v in vs)
    files = [client.get(f"/projects/{pid}/output?variant={i}").content for i in range(3)]
    assert len({len(f) for f in files}) == 3  # three genuinely different renders
    plan = client.get(f"/projects/{pid}/plan").json()
    assert plan["style"] == vs[0]["style"] and len(plan["overlays"]) >= 2
    # pick the last-ranked version: it becomes the project's output AND its plan (timeline, next edit, undo follow
    # the chosen look — before, only the video bytes were swapped and the plan stayed version 0)
    chose = client.post(f"/jobs/{job['id']}/choose", json={"variant": 2}).json()
    assert chose["ok"] and chose["chosen"] == 2 and chose["job_id"] and chose["job_id"] != job["id"]
    assert client.get(f"/projects/{pid}/output").content == files[2]
    assert [v["chosen"] for v in client.get(f"/jobs/{job['id']}").json()["variations"]] == [False, False, True]
    chosen_plan = client.get(f"/projects/{pid}/plan").json()
    assert chosen_plan["style"] == vs[2]["style"] != plan["style"]
    # undo: back to the version that was current before the choice (rank 0 look, its own video)
    assert client.post(f"/projects/{pid}/undo").status_code == 200
    assert client.get(f"/projects/{pid}/plan").json()["style"] == vs[0]["style"]
    assert client.get(f"/projects/{pid}/output").content == files[0]
    assert client.post(f"/projects/{pid}/redo").status_code == 200
    assert client.get(f"/projects/{pid}/plan").json()["style"] == vs[2]["style"]
    assert client.post(f"/jobs/{job['id']}/choose", json={"variant": 5}).status_code == 422
    # timeline helpers
    cid = env["c_id"]
    strip = client.get(f"/projects/{pid}/clips/{cid}/filmstrip?frames=8")
    assert strip.status_code == 200 and strip.headers["content-type"] == "image/jpeg"
    (env["work"] / "strip.jpg").write_bytes(strip.content)
    info = probe(env["work"] / "strip.jpg")
    assert (info.width, info.height) == (8 * 160, 90)
    wave = client.get(f"/projects/{pid}/clips/{cid}/waveform?points=100").json()
    assert len(wave["peaks"]) == 100 and max(wave["peaks"]) == 1.0 and abs(wave["duration"] - 12) < 0.2


def test_capcut_style_fx_prompt(env):
    cat = env["client"].get("/fx").json()
    assert cat["counts"]["transition"] >= 58 and cat["counts"]["video_effect"] >= 25
    job, out, plan, row = run_prompt(env, "fx_mix",
                                     "glitch effect, vhs look, teal and orange, pixelize transitions, karaoke captions")
    assert {"glitch", "vhs"} <= {e.type for e in plan.effects}
    assert plan.color.preset == "teal_orange"
    assert any(t.type == "pixelize" for t in plan.transitions)
    caps = [t for t in plan.text if t.kind == "caption"]
    assert caps and all(t.style.animation == "karaoke" for t in caps)
    failed = [c["name"] for c in job["review"]["checks"] if not c["passed"]]
    row["extra"]["failed"] = failed
    assert "effect_glitch" not in failed and "transitions_present" not in failed


def test_memory_same_as_before(env):
    client, pid = env["client"], env["pid"]
    run_prompt(env, "mem_first", "warm color, 9:16 reel, add captions")
    job, out, plan, row = run_prompt(env, "mem_repeat", "same as before but add film grain")
    assert plan.canvas.aspect_ratio == "9:16" and plan.color.preset == "warm"
    assert any(t.kind == "caption" for t in plan.text) and any(e.type == "film_grain" for e in plan.effects)
    assert any("Repeating the previous edit" in lg["msg"] for lg in job["logs"])
    mem = client.get(f"/projects/{pid}/memory").json()
    assert mem["history"][0]["prompt"] == "same as before but add film grain"
    assert mem["preferences"]["edits_remembered"] >= 2 and "past edits" in mem["summary"]
