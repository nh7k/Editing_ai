"""Live editing view, Copy an Edit, templates, and the agent remembering a conversation of changes."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from cutmind import live
from cutmind import templates as tpl
from cutmind.blueprint import Blueprint, Shot, ShotRhythm, _cuts, _frames, _same_text, _shot_stats, load_blueprint, save_blueprint
from cutmind.coach import understand
from cutmind.ffmpeg_utils import ffmpeg_bin, probe
from cutmind.intent import Intent, parse_intent
from cutmind.memory import is_follow_up, merge_with_last, wants_repeat


# ---- talking to the agent again and again ------------------------------------------------------------------
def test_follow_up_or_new_edit():
    for p in ("thoda slow karo", "ab black and white kar do", "text bhi daal do 'RONALDO' bada sa",
              "nahi yrr black and white hata do, warm color karo", "end me slow motion bhi", "captions hata do",
              # follow-ups are patches of the current edit by default (a long or "brief-like" one too)
              "15 sec ka short bana, black and white mat karna, starting me zoom", "make it a 9:16 reel"):
        assert is_follow_up(p, parse_intent(p)), p
    for p in ("isko insta reel bana do jhakaas wali", "naya edit banao travel wala", "video boring hai kuch karo",
              "shuru se bana do"):
        assert not is_follow_up(p, parse_intent(p)), p
    assert wants_repeat("pichla wala hi dobara bana do") and wants_repeat("pehle jaisa bana do")


def test_a_conversation_of_changes_keeps_every_earlier_change():
    """The same sequence the live test sends to the app (7/7 there): each message changes one thing, the rest stays."""
    defaults = Intent().model_dump()
    last = parse_intent("isko 15 sec ka fast edit bana do gaane pe").model_dump(exclude_defaults=True)
    steps = ["thoda slow karo", "ab black and white kar do", "text bhi daal do 'RONALDO' bada sa",
             "nahi yrr black and white hata do, warm color karo", "end me slow motion bhi", "thoda slow karo"]
    seen = []
    for p in steps:
        m = merge_with_last(parse_intent(p), last, defaults, wants_repeat(p))
        last = m.model_dump(exclude_defaults=True)
        seen.append(m)
    assert all(m.target_duration == 15 and m.fast_cuts and m.music for m in seen)  # never forgotten
    assert seen[0].pace_change == 1.5 and seen[-1].pace_change == pytest.approx(2.25)  # slower twice = slower
    assert seen[1].color_preset == "bw" and seen[2].color_preset == "bw" and seen[2].title == "RONALDO"
    assert seen[3].color_preset == "warm" and seen[3].title == "RONALDO" and "bw" in seen[3].avoid
    assert seen[4].slow_end and seen[4].color_preset == "warm"
    rep = merge_with_last(parse_intent("pichla wala hi dobara bana do"), last, defaults, True)
    assert not rep.auto and rep.color_preset == "warm" and rep.slow_end and rep.title == "RONALDO"


def test_new_words_the_agent_understands():
    assert parse_intent("thoda slow karo").pace_change == 1.5
    assert parse_intent("bahut fast karo").pace_change == 0.5
    assert parse_intent("slow motion me").pace_change is None and parse_intent("slow motion me").slow_motion
    it = parse_intent("nahi yrr black and white hata do, warm color karo")
    assert it.color_preset == "warm" and "bw" in it.avoid
    assert parse_intent("text bhi daal do 'RONALDO' bada sa").title == "RONALDO"
    assert parse_intent("RONALDO likh do").title == "RONALDO"
    it = parse_intent("some shots black and white")
    assert it.color_pass and it.color_preset is None
    assert parse_intent("black and white kar do").color_preset == "bw"
    assert "ghost_trail" not in parse_intent("movie trailer, cinematic").effects  # "trail" inside "trailer"


# ---- templates --------------------------------------------------------------------------------------------
def test_every_builtin_template_is_understood():
    items = tpl.builtin()
    assert len(items) >= 15 and len({t["id"] for t in items}) == len(items)
    for t in items:
        r = understand(t["prompt"])
        assert not r.get("unclear"), (t["id"], r.get("unclear"))
        assert parse_intent(t["prompt"]).recognized, t["id"]
        assert t["category"] in tpl.CATEGORY_ORDER
    fan = understand(next(t for t in items if t["id"] == "tpl_velocity")["prompt"])["pro_brief"]
    assert "stutter" in fan and "black and white" in fan


def test_template_cards_and_my_templates(tmp_path):
    card = tpl.preview(tmp_path, "tpl_travel_diary", tmp_path / "cards")
    assert card is not None and card.stat().st_size > 2000
    assert tpl.preview(tmp_path, "tpl_nope", tmp_path / "cards") is None
    copy = tmp_path / "copy"
    copy.mkdir()
    with pytest.raises(tpl.TemplateError):
        tpl.save_mine(tmp_path, "x", copy, tmp_path / "music")
    save_blueprint(Blueprint(name="liked.mp4", duration=6, shots=[Shot(0, 2), Shot(2, 4)]), copy / "blueprint.json")
    t = tpl.save_mine(tmp_path, "Mera style", copy, tmp_path / "music")
    listed = tpl.all_templates(tmp_path)
    assert listed["templates"][0]["id"] == t["id"] and "Mine" in listed["categories"]
    other = tmp_path / "other_copy"
    tpl.install_mine(tmp_path, t["id"], other, tmp_path / "music2")
    assert load_blueprint(other / "blueprint.json").duration == 6
    assert not tpl.delete_mine(tmp_path, "tpl_velocity")  # built-ins can't be deleted
    assert tpl.delete_mine(tmp_path, t["id"]) and tpl.get(tmp_path, t["id"]) is None


# ---- Copy an Edit -----------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def three_shots(tmp_path_factory) -> Path:
    """1 s red, 1.5 s grey (black & white), 1 s blue, 9:16."""
    out = tmp_path_factory.mktemp("bp") / "liked.mp4"
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=s=360x640:d=1:r=25,hue=h=0:s=2",
                    "-f", "lavfi", "-i", "testsrc2=s=360x640:d=1.5:r=25,hue=s=0",
                    "-f", "lavfi", "-i", "smptebars=s=360x640:d=1:r=25",
                    "-filter_complex", "[0][1][2]concat=n=3:v=1[v]", "-map", "[v]", "-pix_fmt", "yuv420p", str(out)],
                   check=True)
    return out


def test_blueprint_finds_the_shots_and_the_black_and_white_one(three_shots):
    f = _frames(three_shots)
    dur = probe(three_shots).duration
    cuts = _cuts(three_shots, f, dur)
    assert any(abs(c - 1.0) < 0.15 for c in cuts) and any(abs(c - 2.5) < 0.15 for c in cuts)
    shots = _shot_stats(f, [0.0, 1.0, 2.5, dur])
    assert [s.bw for s in shots] == [False, True, False]
    assert sorted(s.motion for s in shots) == [0.0, 0.5, 1.0]  # a rank inside this edit


def test_blueprint_rhythm_and_text_matching(tmp_path):
    bp = Blueprint(duration=4, shots=[Shot(0, 1, motion=0.0), Shot(1, 2, motion=1.0), Shot(3, 1, motion=0.5)])
    r = ShotRhythm(bp)
    assert r.period == 1.0 and r.mean_energy(1.2, 2.5) == 1.0 and bp.slots() == [(0, 1), (1, 3), (3, 4)]
    assert _same_text("Edits get done while u sleep", "Edits get done while u O")
    assert _same_text("Followformorehacks", "Follow for more hacks") and not _same_text("Let it cook", "Go to invideo")
    save_blueprint(bp, tmp_path / "b.json")
    assert load_blueprint(tmp_path / "b.json").shots[1].dur == 2


# ---- live editing view ------------------------------------------------------------------------------------
class _Tracker:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def event(self, kind: str, **data) -> None:
        self.events.append((kind, data))


def test_live_view_reports_thoughts_once_and_the_video_track():
    tr = _Tracker()
    ctx = SimpleNamespace(decisions=[{"decision": "fast cuts", "where": "whole edit", "reason": "a fan edit"}],
                          clips=[SimpleNamespace(id="c1", filename="a.mp4")], project_id="p1",
                          sections={"cutter": {"clips": [{"source": "c1", "in": 2.0, "out": 4.0, "order": 0},
                                                         {"source": "c1", "in": 6.0, "out": 7.0, "speed": 0.5, "order": 1}]},
                                    "audio": {"music": "song.m4a"}})
    live.started(tr, "cutter")
    live.finished(ctx, tr, "cutter")
    live.finished(ctx, tr, "cutter")  # the same decision is not repeated
    thoughts = [d["text"] for k, d in tr.events if k == "thought"]
    assert thoughts[0].startswith("Cutting") and sum("fast cuts" in t for t in thoughts) == 1
    video = next(d["items"] for k, d in tr.events if k == "timeline" and d["track"] == "video")
    assert [(v["start"], v["dur"]) for v in video] == [(0.0, 2.0), (2.0, 2.0)]
    assert video[0]["thumb"] == "/projects/p1/clips/c1/frame?t=3.00" and video[0]["filename"] == "a.mp4"
    assert any(k == "timeline" and d["track"] == "music" for k, d in tr.events)
    live.started(object(), "cutter")  # a tracker without events (tests, CLI) is fine


def test_each_styled_version_draws_its_own_tracks():
    """Variations are most of such a job's time (job_75684d9d5b5e: 12 s edit, 105 s rendering 3 versions) and
    the timeline used to stand still meanwhile: now every version says its name and draws its looks."""
    from cutmind.plan import EditPlan

    tr = _Tracker()
    ctx = SimpleNamespace(clips=[SimpleNamespace(id="c1", filename="a.mp4")], project_id="p1")
    plan = EditPlan.model_validate({
        "clips": [{"source": "c1", "in": 0, "out": 4, "order": 0}],
        "effects": [{"type": "zoom", "target": -1}], "color": {"preset": "bw"},
        "text": [{"kind": "title", "text": "Hi", "start": 0, "end": 1}]})
    live.variation(ctx, tr, 2, 3, "Violet Authority", "bold purple", plan)
    assert any(k == "thought" and d["text"].startswith("Version 2/3: Violet Authority") for k, d in tr.events)
    tracks = {d["track"]: d["items"] for k, d in tr.events if k == "timeline"}
    assert tracks["color"][0]["name"] == "Violet Authority" and tracks["color"][0]["preset"] == "bw"
    assert [f["type"] for f in tracks["fx"]] == ["zoom"] and tracks["text"][0]["text"] == "Hi"
    live.variation(ctx, object(), 1, 3, "x", "y", plan)  # a tracker without events is fine


# ---- camera moves: measured on a liked video, replayed on the user's footage -------------------------------
@pytest.fixture(scope="module")
def still_clip(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("cam")
    img = d / "still.png"
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=s=720x1280:d=1,noise=alls=40:allf=0", "-frames:v", "1", str(img)], check=True)
    out = d / "still.mp4"
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-loop", "1", "-i", str(img), "-t", "3", "-r", "30", "-vf",
                    "scale=360:640", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out


@pytest.mark.parametrize("path, kind, check", [
    ([[0, 1, 0, 0, 0], [3, 1.3, 0, 0, 0]], "push_in", lambda e: abs(e[1] - 1.3) < 0.04 and abs(e[2]) < 0.02),
    ([[0, 1, 0, 0, 0], [3, 1, 0.10, 0, 0]], "move_left", lambda e: abs(e[2] - 0.10) < 0.02 and abs(e[3]) < 0.02),
    ([[0, 1.25, 0, 0, 0], [3, 1, 0, -0.08, 0]], "pull_out", lambda e: e[1] < 0.85 and abs(e[3] + 0.08) < 0.02),
    ([[0, 1, 0, 0, 0], [3, 1, 0, 0, 0.06]], "roll", lambda e: abs(e[4] - 0.06) < 0.01),
    ([[0, 1, 0, 0, 0], [3, 1, 0, 0, 0]], "static", lambda e: abs(e[1] - 1) < 0.01 and abs(e[2]) < 0.01),
])
def test_a_camera_move_is_replayed_and_measured_back(still_clip, tmp_path, path, kind, check):
    from cutmind.camera_move import gray_frames, replay_filters, shot_path

    out = tmp_path / "moved.mp4"
    vf = ",".join(replay_filters(path, 360, 640, 3.0)) or "null"
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(still_clip), "-vf", vf, "-pix_fmt", "yuv420p",
                    str(out)], check=True)
    r = shot_path(gray_frames(out, 640, 360), 0, 3.0)
    assert r["kind"].split("+")[0] == kind and check(r["path"][-1]), r["path"][-1]


def test_zoom_effect_stays_centred(still_clip, tmp_path):
    """The old zoom (per-frame scale + crop) drifted 5 % towards a corner."""
    from cutmind.camera_move import gray_frames, shot_path
    from cutmind.fx_catalog import FxContext, effect_filters

    out = tmp_path / "zoom.mp4"
    vf = ",".join(effect_filters("zoom", FxContext(w=360, h=640, duration=3.0, fps=30, strength=1.0, times=())))
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(still_clip), "-vf", vf, "-pix_fmt", "yuv420p",
                    str(out)], check=True)
    e = shot_path(gray_frames(out, 640, 360), 0, 3.0)["path"][-1]
    assert e[1] > 1.08 and abs(e[2]) < 0.01 and abs(e[3]) < 0.01


def test_a_crash_zoom_is_replayed_softer():
    from cutmind.camera_move import MAX_SCALE, MAX_ZOOM, replay_filters

    f = replay_filters([[0, 1, 0, 0, 0], [2, 2.6, 1.1, 0, 0.3]], 360, 640, 2.0)
    z = f[-1].split("z='")[1].split("'")[0]
    nums = [float(x) for x in __import__("re").findall(r"\,(\d+\.\d+)\,", z) + [z.split("\,")[-1].rstrip(")")]]
    assert max(nums) <= MAX_SCALE * MAX_ZOOM + 1e-3


def test_audio_complaints_bring_the_sound_back():
    for p in ("audio sunai nhi de raha h", "awaaz nahi aa rahi", "pehle jaisa audio la do", "sound wapas lao"):
        it = parse_intent(p)
        assert it.restore_audio and not it.mute and not it.remove_silence, p
    assert parse_intent("mute kar do").mute and not parse_intent("mute kar do").restore_audio
    defaults = Intent().model_dump()
    m = merge_with_last(parse_intent("audio nahi aa raha"), {"mute": True, "music": True, "music_volume": 0.9,
                                                             "target_duration": 16.0}, defaults, False)
    assert not m.mute and m.target_duration == 16 and m.music
