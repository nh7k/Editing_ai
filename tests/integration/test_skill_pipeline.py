"""Every built Tier 1/2 skill that works through the parser (impl kind "intent") runs through the REAL workflow
(understand → analyze → audio ∥ color → cutter → effects → render → review) on generated footage, and:

* the skill is in the final intent (the editor understood it),
* the rendered file decodes,
* the Reviewer — which reads the prompt again with its own keywords and measures the rendered file — passes every
  check it can fix (footage limits like "nobody speaks here" are reported, not failures),
* plus a direct measurement for skills with a clear number (length, aspect, brightness, speed, sound).

Results are merged into skills/test_results.json; skills/tools/update_status.py turns passes into status: tested.
moment_sticker (a timeline-comment skill) is tested in test_stickers_comments.py and test_skill_library.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from cutmind import skill_registry as R
from cutmind.agents.base import AgentContext, ClipRef
from cutmind.agents.director import DirectorAgent
from cutmind.ffmpeg_utils import decode_check, extract_frame, measure_loudness, probe

from conftest import make_settings

pytestmark = pytest.mark.integration
RESULTS = Path(__file__).resolve().parents[2] / "skills" / "test_results.json"
_results: dict[str, dict] = {}

SKIP = {"moment_sticker"}
FOOTAGE = 26.5  # clip_a_talk 14.53 s + clip_c_scenes 12.0 s  # needs a moment on the timeline: tested where comments are


def _skills() -> list[dict]:
    return [s for s in R.load().values() if s["tier"] < 3 and s["impl"]["kind"] == "intent" and s["id"] not in SKIP]


def _prompt(s: dict) -> str:
    return R.fill(s["impl"]["ref"], s)


@pytest.fixture(scope="module")
def run(media, music_dir, tmp_path_factory):
    """Runs one edit; the plain edit ("edit kar do") is run once and kept for A/B measurements."""
    root = tmp_path_factory.mktemp("skillpipe")
    settings = make_settings(root / "data", music_dir)
    cache: dict[str, object] = {}

    def go(prompt: str, key: str):
        if prompt not in cache:
            clips = [ClipRef("A", media["a"], "a.mp4", 0), ClipRef("C", media["c"], "c.mp4", 1)]
            ctx = AgentContext(job_id=key, prompt=prompt, clips=clips, settings=settings,
                               work_dir=root / "proj" / "work" / key)
            cache[prompt] = DirectorAgent().run_job(ctx, root / f"{key}.mp4")
        return cache[prompt]

    return go


@pytest.fixture(scope="module", autouse=True)
def _save():
    yield
    old = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    old.update(_results)
    RESULTS.write_text(json.dumps(old, indent=1, sort_keys=True), encoding="utf-8")


def _bright(path: Path, t: float) -> float:
    return float(extract_frame(path, t).astype(float).mean())


def _measure(sid: str, res, plain) -> tuple[bool, str]:
    """Direct numbers for the skills that have one (beyond the Reviewer)."""
    out, info, pinfo = res.output, probe(res.output), probe(plain.output)
    if sid == "target_duration":
        want = min(res.intent.target_duration, FOOTAGE)  # the footage is 26.5 s: a 30 s ask gets all of it
        return abs(info.duration - want) <= max(1.0, 0.1 * want), f"{info.duration:.1f}s for {want:g}s"
    if sid == "shorter":  # a fresh project: shorter than the footage (a follow-up is shorter than the last version)
        return info.duration < FOOTAGE - 2, f"{info.duration:.1f}s from {FOOTAGE:g}s of footage"
    if sid == "aspect":
        want = res.intent.aspect_ratio
        a, b = (float(x) for x in want.split(":"))
        return abs(info.width / info.height - a / b) < 0.02, f"{info.width}x{info.height} for {want}"
    if sid == "brightness":
        t = min(info.duration, pinfo.duration) / 2
        d = _bright(out, t) - _bright(plain.output, t)
        return d > 2, f"brighter by {d:.1f}"
    if sid == "mute":
        loud = measure_loudness(out) if info.has_audio else {}
        lv = loud.get("max_volume")
        return (not info.has_audio) or lv is None or lv < -50, f"max volume {lv}"
    if sid in ("slow_motion", "speed_up"):
        speeds = [c.speed for c in res.plan.clips]
        ok = any(s < 1 for s in speeds) if sid == "slow_motion" else any(s > 1 for s in speeds) or \
            info.duration < pinfo.duration - 0.5
        return ok, f"speeds {speeds}, {info.duration:.1f}s vs {pinfo.duration:.1f}s"
    if sid == "reverse":
        return any(c.reverse for c in res.plan.clips), "a reversed shot"
    if sid == "no_music":
        return not res.plan.audio.music, f"music {res.plan.audio.music}"
    if sid == "music":
        return bool(res.plan.audio.music), f"music {res.plan.audio.music}"
    if sid == "captions":
        caps = [t for t in res.plan.text if t.kind == "caption"]
        return bool(caps), f"{len(caps)} captions"
    return True, ""


@pytest.mark.parametrize("skill", _skills(), ids=lambda s: s["id"])
def test_skill_through_the_pipeline(skill, run):
    sid, prompt = skill["id"], _prompt(skill)
    try:
        res = run(prompt, sid)
        plain = run("edit kar do", "plain")
        ok, err = decode_check(res.output)
        assert ok, err
        named = R.skills_in_intent(res.intent)
        failed = [f"{c.name}: {c.detail}" for c in res.review.checks if not c.passed and c.data.get("fixable", True)]
        good, detail = _measure(sid, res, plain)
        ok = sid in named and not failed and good
        _results[sid] = {"ok": bool(ok), "detail": (f"'{prompt}': " + ("in intent" if sid in named else "NOT in intent")
                                                    + (f"; {detail}" if detail else "")
                                                    + (f"; review failed {failed}" if failed else ""))[:300]}
        assert ok, _results[sid]
    except Exception as exc:
        _results.setdefault(sid, {"ok": False, "detail": f"'{prompt}': {exc}"[:300]})
        raise
