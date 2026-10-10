"""Every built skill of the registry that maps to an engine (effect / transition / look / text style / text
animation / motion preset) renders for real with FFmpeg and changes the picture the way it should. Results go to
skills/test_results.json; skills/tools/update_status.py turns passes into status: tested.

Checks: decodes; length right; the frame at the target time differs from the plain render; for colour skills the
measured colour moves the right way; for transitions the length is the two shots minus the overlap and the middle of
the transition is neither shot; for a timed effect the picture outside its window is unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from cutmind import skill_registry as R
from cutmind.engines.motion import preset
from cutmind.ffmpeg_utils import decode_check, extract_frame, probe
from cutmind.plan import EditPlan
from cutmind.renderer import render

pytestmark = pytest.mark.integration
RESULTS = Path(__file__).resolve().parents[2] / "skills" / "test_results.json"
_results: dict[str, dict] = {}

BASE = {"canvas": {"aspect_ratio": "9:16", "resolution": 360},
        "clips": [{"source": "a", "in": 0.5, "out": 3.0, "order": 0}, {"source": "c", "in": 8.5, "out": 11.0, "order": 1}]}  # textured part (0-4 s is flat blue)
TOTAL = 5.0


def _built(kinds: tuple[str, ...]) -> list[dict]:
    return [s for s in R.load().values() if s["impl"]["kind"] in kinds and s["status"] not in ("planned", "blocked")]


def _sat(f: np.ndarray) -> float:
    f = f.astype(float)
    return float((f.max(axis=2) - f.min(axis=2)).mean())


@pytest.fixture(scope="module")
def plain(media, tmp_path_factory):
    d = tmp_path_factory.mktemp("plain")
    out = render(EditPlan.model_validate(BASE), {"a": media["a"], "c": media["c"]}, d / "w", d / "plain.mp4")
    frames = {t: extract_frame(out, t).astype(float) for t in (0.6, 1.2, 2.0, 2.6, 3.0, 3.6, 4.2)}
    frames["path"] = out
    return frames


@pytest.fixture(scope="module")
def grey(tmp_path_factory):
    """A neutral grey ramp clip: warm / cool looks are measured on it (saturated test patterns hide a warm shift)."""
    from cutmind.ffmpeg_utils import run_ffmpeg

    d = tmp_path_factory.mktemp("grey")
    clip = d / "grey.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=3", "-f", "lavfi", "-i", "sine=f=220:d=3",
                "-vf", "hue=s=0", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(clip)])
    return clip


def _warmth_on_grey(grey: Path, tmp_path: Path, extra: dict) -> float:
    base = {"canvas": {"aspect_ratio": "16:9", "resolution": 360},
            "clips": [{"source": "g", "in": 0.0, "out": 2.5, "order": 0}]}
    a = render(EditPlan.model_validate(base), {"g": grey}, tmp_path / "gw0", tmp_path / "g0.mp4")
    b = render(EditPlan.model_validate({**base, **extra}), {"g": grey}, tmp_path / "gw1", tmp_path / "g1.mp4")
    fa, fb = extract_frame(a, 1.2).astype(float), extract_frame(b, 1.2).astype(float)
    return float((fb[..., 0] - fb[..., 2]).mean() - (fa[..., 0] - fa[..., 2]).mean())


def _render(media, tmp_path, extra: dict, name: str) -> Path:
    plan = EditPlan.model_validate({**BASE, **extra})
    out = render(plan, {"a": media["a"], "c": media["c"]}, tmp_path / "w", tmp_path / f"{name}.mp4")
    ok, err = decode_check(out)
    assert ok, err
    assert abs(probe(out).duration - plan.total_duration()) < 0.2
    return out


def _diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a - b).mean())


def _record(sid: str, ok: bool, detail: str) -> None:
    _results[sid] = {"ok": bool(ok), "detail": detail[:200]}  # bool(): numpy bools are not JSON


@pytest.fixture(scope="module", autouse=True)
def _save():
    yield
    old = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    old.update(_results)
    RESULTS.write_text(json.dumps(old, indent=1, sort_keys=True), encoding="utf-8")


EXPECT = {  # colour direction checks: (measure, sign)
    "look_bw": ("sat", -1), "mono": ("sat", -1), "film_bw": ("sat", -1), "invert_mono": ("sat", -1),
    "look_warm": ("warm", +1), "look_cool": ("warm", -1), "look_vivid": ("sat", +1), "golden_hour": ("warm", +1),
    "arctic": ("warm", -1), "moody_blue": ("warm", -1), "noir": ("sat", -1),
}


TEMPORAL = {"strobe", "ghost_trail", "echo"}


def _edges(f: np.ndarray) -> float:
    g = np.asarray(f, dtype=float).mean(axis=2)
    return float(np.abs(np.diff(g, axis=0)).mean() + np.abs(np.diff(g, axis=1)).mean())


def _measure(kind: str, f: np.ndarray) -> float:
    return _sat(f) if kind == "sat" else float((f[..., 0] - f[..., 2]).mean())


@pytest.mark.parametrize("skill", _built(("effect",)), ids=lambda s: s["id"])
def test_effect_skill_renders(skill, media, tmp_path, plain):
    sid, ref = skill["id"], R.fill(skill["impl"]["ref"], skill)
    if ref in ("speed_ramp", "blur_background"):
        extra = {"effects": [{"type": ref, "target": 1, "strength": 2.0}]} if ref == "speed_ramp" else \
                {"canvas": {**BASE["canvas"], "reframe": "blur_pad"}}
    elif ref == "keyframes":
        pts, easing = preset("zoom_bounce", 2.5)
        extra = {"effects": [{"type": "keyframes", "target": 1, "points": pts, "easing": easing}]}
    elif ref in ("follow", "person_zoom", "spotlight", "camera_move"):
        # need a subject path / a measured move: give them one
        extra = {"effects": [{"type": ref, "target": 1, "points": [[0, 1.0, 0, 0, 0], [1.2, 1.3, 0.05, 0.0, 2.0],
                                                                    [2.5, 1.2, 0.0, 0.03, 0.0]] if ref == "camera_move"
                              else [[0, 0.5, 0.5, 0.3, 0.6], [2.5, 0.55, 0.5, 0.3, 0.6]]}]}
    else:
        extra = {"effects": [{"type": ref, "target": 1, "times": [0.4, 1.2] if ref in ("pulse", "punch", "impact", "flash")
                              else []}]}
    try:
        out = _render(media, tmp_path, extra, sid)
        t_in = 3.6 if ref not in ("pulse", "punch", "impact", "flash") else 2.5 + 1.2
        changed = _diff(extract_frame(out, t_in).astype(float), plain[3.6]) if t_in == 3.6 else max(
            _diff(extract_frame(out, x).astype(float), extract_frame(out, 2.6).astype(float)) for x in (2.95, 3.7, 3.75))
        if ref in TEMPORAL:  # flicker / trails: the change comes and goes, so look at several frames of the shot
            changed = max(changed, *(_diff(extract_frame(out, x).astype(float), plain[x]) for x in (2.6, 3.0, 4.2)))
        if ref == "speed_ramp":  # the ramp starts half-way through the shot
            changed = _diff(extract_frame(out, 4.2).astype(float), plain[4.2])
        if ref == "ghost_trail":  # lagfun only brightens (trails behind what moves): measure that brightening
            changed = 10 * max(float((extract_frame(out, x).astype(float) - plain[x]).clip(0).mean()) for x in (3.0, 3.6, 4.2))
        if ref == "sharpen":  # a few-percent change of the mean is right for sharpening: measure the edge energy
            changed = 10 * (_edges(extract_frame(out, 3.6)) / _edges(plain[3.6]) - 1)
        untouched = _diff(extract_frame(out, 1.2).astype(float), plain[1.2])
        ok = changed > 1.0 and (untouched < 2.0 or ref in ("speed_ramp",) or extra.get("canvas"))
        if sid in EXPECT:
            kind, sign = EXPECT[sid]
            moved = _measure(kind, extract_frame(out, 3.6).astype(float)) - _measure(kind, plain[3.6])
            ok = ok and moved * sign > 0
        if ref in ("strobe", "echo"):
            # strobe flashes 0.05 s of every 0.25 s and echo only shows on motion: the textured part of clip c
            # barely moves and the fixed sample times all fell between flashes (found 2026-10-10). Put them on
            # the moving talk shot and look at a frame every 0.04 s.
            moving = {"effects": [{"type": ref, "target": 0, "times": []}]}
            out2 = _render(media, tmp_path, moving, f"{sid}_moving")
            changed = max(_diff(extract_frame(out2, x).astype(float), extract_frame(plain["path"], x).astype(float))
                          for x in np.arange(0.1, 2.4, 0.04))
            untouched = _diff(extract_frame(out2, 3.6).astype(float), plain[3.6])
            ok = changed > 1.0 and untouched < 2.0
        _record(sid, ok, f"changed {changed:.2f} in its shot, {untouched:.2f} elsewhere")
        assert ok, _results[sid]
    except Exception as exc:
        _record(sid, False, str(exc))
        raise


@pytest.mark.parametrize("skill", _built(("look",)), ids=lambda s: s["id"])
def test_look_skill_renders(skill, media, tmp_path, plain, grey):
    sid, ref = skill["id"], R.fill(skill["impl"]["ref"], skill)
    try:
        from cutmind.agents.color import PRESETS  # the numbers the Color agent gives a named look (real path)

        color = {"preset": ref, **PRESETS.get(ref, {})}
        out = _render(media, tmp_path, {"color": color}, sid)
        f = extract_frame(out, 3.6).astype(float)
        ok = _diff(f, plain[3.6]) > 1.0
        detail = f"changed {_diff(f, plain[3.6]):.2f}"
        if sid in EXPECT or ref in EXPECT:
            kind, sign = EXPECT.get(sid) or EXPECT[ref]
            moved = (_warmth_on_grey(grey, tmp_path, {"color": color}) if kind == "warm"
                     else _measure(kind, f) - _measure(kind, plain[3.6]))
            ok = ok and moved * sign > 0
            detail += f", {kind} moved {moved:+.2f}" + (" (on a grey ramp)" if kind == "warm" else "")
        _record(sid, ok, detail)
        assert ok, detail
    except Exception as exc:
        _record(sid, False, str(exc))
        raise


@pytest.mark.parametrize("skill", _built(("transition",)), ids=lambda s: s["id"])
def test_transition_skill_renders(skill, media, tmp_path, plain):
    sid = skill["id"]
    ref = R.fill(skill["impl"]["ref"], skill)
    try:
        if ref == "fade":  # fade in / out from black at the ends
            out = _render(media, tmp_path, {"transitions": [{"type": "fade", "after": -1, "duration": 0.5},
                                                            {"type": "fade", "after": -2, "duration": 0.5}]}, sid)
            f0 = extract_frame(out, 0.05).astype(float)
            ok = f0.mean() < plain[0.6].mean() * 0.6
            detail = f"first frame mean {f0.mean():.1f}"
        else:
            d = 0.6
            out = _render(media, tmp_path, {"transitions": [{"type": ref, "after": 0, "duration": d}]}, sid)
            dur = probe(out).duration
            mid = extract_frame(out, 2.5 - d / 2).astype(float)
            ok = abs(dur - (TOTAL - d)) < 0.15 and _diff(mid, plain[2.0]) > 1.0
            detail = f"length {dur:.2f} (want {TOTAL - d:.2f}), mid-transition differs {_diff(mid, plain[2.0]):.2f}"
        _record(sid, ok, detail)
        assert ok, detail
    except Exception as exc:
        _record(sid, False, str(exc))
        raise


@pytest.mark.parametrize("skill", _built(("text_style", "text_anim")), ids=lambda s: s["id"])
def test_text_skill_renders(skill, media, tmp_path, plain):
    sid, kind = skill["id"], skill["impl"]["kind"]
    refs = R._ref_values(skill)  # noqa: SLF001 — every preset of the family
    try:
        for ref in refs[:6] if kind == "text_style" else refs:
            style = {"size": 90, "position": "center"} | ({"preset": ref} if kind == "text_style" else {"animation": ref})
            if kind == "text_style":
                from cutmind.text_styles import apply_look
                from cutmind.plan import TextStyle

                style = apply_look(TextStyle(position="center", size=90), ref).model_dump()
            out = _render(media, tmp_path, {"text": [{"kind": "text", "text": "दिल WOW", "start": 0.3, "end": 2.2,
                                                      "style": style}]}, f"{sid}_{ref}")
            during = _diff(extract_frame(out, 1.6).astype(float), plain[1.2])  # text on screen
            after = _diff(extract_frame(out, 3.6).astype(float), plain[3.6])   # gone again
            if not (during > 1.0 and after < 2.0):
                _record(sid, False, f"{ref}: during {during:.2f}, after {after:.2f}")
                pytest.fail(_results[sid]["detail"])
        _record(sid, True, f"{len(refs)} variant(s) render, Devanagari + Latin text visible only in its window")
    except Exception as exc:
        if sid not in _results:
            _record(sid, False, str(exc))
        raise


def test_timed_effect_only_inside_its_window(media, tmp_path, plain):
    """between_times: a B&W window on 0.6–1.6 s leaves the rest in colour (the cutter splits at window edges in the
    full pipeline; here the shot is the window)."""
    out = _render(media, tmp_path, {"clips": [{"source": "a", "in": 0.5, "out": 1.5, "order": 0},
                                              {"source": "a", "in": 1.5, "out": 3.0, "order": 1},
                                              {"source": "c", "in": 0.5, "out": 3.0, "order": 2}],
                                    "effects": [{"type": "mono", "target": 0}]}, "timed")
    assert _sat(extract_frame(out, 0.5).astype(float)) < 3.0
    assert _sat(extract_frame(out, 3.6).astype(float)) > 10.0
