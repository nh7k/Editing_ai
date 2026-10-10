"""Catalog difference test: every variant of a Tier 1 skill whose axis is a real parameter is rendered on the same
media as the skill's own Tier 1 test and compared with its siblings. A variant is only `ready` when it (1)
renders and decodes with sound and the planned length, (2) changes something compared with the plain video, and
(3) is VISIBLY / AUDIBLY different from every sibling accepted before it. Otherwise it is
`rejected-duplicate` (named: which sibling it copies) or `rejected-no-effect`.

"Different" (thresholds from docs/CATALOG_REVIEW.md):
- picture: the most-different of up to 72 frames (6 per second, so a 0.4 s slide-in is seen) differs by >= 3.0 (mean absolute, 0-255, at 256x256), OR
  one 16x16 tile of it differs by >= 10 (small things: a caption, a progress bar, a logo — a whole-frame mean
  hides them)
- sound: the 0.25 s loudness envelope differs somewhere by >= 1.5 dB (above -50 dBFS)
- length differs by >= 0.1 s, or the frame size / extra files (mp3, srt ...) differ, or the file is >= 1.3x
  bigger per second (export quality presets)

Results go to catalog/variant_results.json; catalog/build_catalog.py turns them into the catalog.

    TIER1_CATEGORY=color backend/.venv/Scripts/python.exe -m pytest tests/integration/test_catalog_variants.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest
from cutmind.ffmpeg_utils import decode_check, ffmpeg_bin, probe
from cutmind.renderer import render
from cutmind.tools import engine, spec
from cutmind.tools.engine import ToolCtx
from cutmind.tools.timeline import ToolError
from test_tier1 import (  # noqa: F401 — the same media fixtures
    box,
    box_track,
    dark,
    env,
    noisy,
    shaky,
    soft,
    tones,
)
from tier1_checks import pcm

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "catalog" / "variant_results.json"
PIC, TILE, SOUND_DB, LEN_S, SIZE_X = 3.0, 10.0, 1.5, 0.1, 1.3
_results: dict[str, dict] = {}
# variants that rightly change nothing on THIS test media (checked by hand, 2026-10-10). Still recorded as
# rejected-no-effect (never offered); listed so a NEW no-effect variant fails the test instead of hiding.
KNOWN_NO_EFFECT = {
    "caption_style.color=white": "the test captions are already white",
    "volume.what=voice": "the test media is tones, no voice — nothing to make louder",
    "extract_highlights.length=8s": "2 x 8 s is longer than the 12 s video, so the whole video is kept",
    "beat_sync.every=4": "the only cut is further than max_shift from every 4th beat; explain says '0 of 1 cuts moved'",
    "sharpen.amount=light": "on soft footage a light sharpen only shows at full size; this test looks at 256 px",
    "echo_reverb.amount=room": "a small room is subtle: 1.4 dB, just under the 1.5 dB audible limit",
}

LOW = {"light", "soft", "slow", "small", "room", "gentle", "fine"}
MID = {"normal", "medium", "hall"}
HIGH = {"strong", "heavy", "loud", "fast", "large", "cave", "full", "coarse"}
COLORS = {"red": "#FF3B30", "yellow": "#FFD60A", "blue": "#0A84FF", "green": "#30D158", "white": "#FFFFFF",
          "pink": "#FF2D92", "orange": "#FF7A18", "gold": "#F5B700", "black": "#000000"}


def value_for(p: dict, v) -> tuple[object | None, str]:
    """An axis value ('light', '0.3s', '2x', 'yellow') as the parameter value, or None + why it cannot be."""
    t = p.get("type")
    if t in ("number", "integer"):
        lo, hi, d = float(p.get("min", 0)), float(p.get("max", 1)), float(p.get("default", p.get("min", 0)))
        s = str(v).strip().lower()
        m = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*(?:s|x|db|sec)?", s)
        if m:
            x = float(m.group(1))
        elif s == "half":
            x = (lo + hi) / 2
        elif s in LOW:
            x = (lo + d) / 2 if d > lo else lo
        elif s in MID:
            x = d
        elif s in HIGH:
            x = d + 0.8 * (hi - d) if hi > d else hi
        else:
            return None, f"'{v}' is a word, not a number for this parameter"
        if not lo - 1e-9 <= x <= hi + 1e-9:
            return None, f"{x} is outside {lo}..{hi}"
        return (round(x) if t == "integer" else round(x, 3)), ""
    if t == "choice":
        ch = p.get("choices", [])
        for c in ch:
            if str(c) == str(v):
                return c, ""
        return None, f"'{v}' is not one of the parameter's choices yet"
    if t == "bool":
        return str(v).lower() in ("on", "true", "yes", "box", "1"), ""
    if t == "color":
        s = str(v).lower()
        return (COLORS.get(s) or (s if s.startswith("#") else None)), ("" if s in COLORS or s.startswith("#") else
                                                                       f"no colour named '{v}'")
    return v, ""


def candidates() -> list[dict]:
    names = engine.builder_names()
    only = os.environ.get("TIER1_CATEGORY")
    out = []
    for sid, s in spec.load().items():
        if s["builder"] not in names or (only and s["category"] not in only.split(",")):
            continue
        for axis, vals in (s.get("variant_axes") or {}).items():
            if axis in s.get("params", {}):
                out.append({"skill": sid, "axis": axis, "values": list(vals)})
    return out


def fingerprint(out: Path) -> dict:
    info = probe(out)
    d = max(info.duration, 0.1)
    raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(out), "-vf",
                          f"fps={min(6.0, 72 / d):.5f},scale=256:256:flags=area,format=rgb24", "-frames:v", "72",
                          "-f", "rawvideo", "-"], capture_output=True, timeout=120, check=False).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, 256, 256, 3)  # a different shape is caught by size
    a = pcm(out, 0.0, d, 8000)
    win = 2000  # 0.25 s
    env_db = np.array([20 * np.log10(max(1e-5, float(np.sqrt(np.mean(a[i:i + win] ** 2)))))
                       for i in range(0, max(1, len(a) - win + 1), win)])
    extras = sorted(p.suffix for p in out.parent.glob(out.stem + ".*") if p != out)
    return {"dur": info.duration, "size": (info.width, info.height), "frames": frames, "env": np.maximum(env_db, -50),
            "extras": extras, "bytes_per_s": out.stat().st_size / d}


def distance(a: dict, b: dict) -> tuple[bool, str]:
    """Is a visibly / audibly different from b? Returns (different, the strongest reason)."""
    if a["size"] != b["size"]:
        return True, f"frame size {a['size']} vs {b['size']}"
    if a["extras"] != b["extras"]:
        return True, f"extra files {a['extras']} vs {b['extras']}"
    if abs(a["dur"] - b["dur"]) >= LEN_S:
        return True, f"length {a['dur']:.2f}s vs {b['dur']:.2f}s"
    big, small = max(a["bytes_per_s"], b["bytes_per_s"]), max(1.0, min(a["bytes_per_s"], b["bytes_per_s"]))
    n = min(len(a["frames"]), len(b["frames"]))
    pic = max((float(np.abs(a["frames"][i].astype(np.float32) - b["frames"][i]).mean()) for i in range(n)), default=0.0)
    tile = max((float(np.abs(a["frames"][i].astype(np.float32) - b["frames"][i]).reshape(16, 16, 16, 16, 3).mean(axis=(1, 3, 4)).max())
                for i in range(n)), default=0.0)
    m = min(len(a["env"]), len(b["env"]))
    snd = float(np.max(np.abs(a["env"][:m] - b["env"][:m]))) if m else 0.0
    if pic >= PIC:
        return True, f"picture differs by {pic:.1f}"
    if tile >= TILE:
        return True, f"one part of the picture differs by {tile:.1f}"
    if snd >= SOUND_DB:
        return True, f"sound differs by {snd:.1f} dB"
    if big / small >= SIZE_X:
        return True, f"file {big / small:.2f}x bigger per second"
    return False, f"picture {pic:.1f} (< {PIC}), part {tile:.1f} (< {TILE}), sound {snd:.1f} dB (< {SOUND_DB}), same length"


@pytest.fixture(scope="module", autouse=True)
def _save():
    yield
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    old.update(_results)
    RESULTS.write_text(json.dumps(old, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("c", candidates(), ids=lambda c: f"{c['skill']}.{c['axis']}")
def test_variants_are_distinct(c, env, monkeypatch):  # noqa: F811 — env is the imported fixture
    s = spec.load()[c["skill"]]
    t = s["test"]
    media_set = t.get("media", "default")
    ids, srcs = env["sets"][media_set]
    pplan, pout = env["plain"](media_set)
    root = env["root"] / "variants" / c["skill"]
    if t.get("setup"):
        sctx = ToolCtx(sources=dict(srcs), gen_dir=env["root"] / "generated", clip_ids=list(ids),
                       music_dirs=[env["music"]], analysis=lambda: env["analysis"](media_set))
        pplan, _ = engine.run(pplan, t["setup"], sctx)
        pout = render(pplan, srcs, root / "plain_w", root / "plain.mp4", env["music"])
    if media_set == "box":
        import cutmind.tracking

        monkeypatch.setattr(cutmind.tracking, "track_clip", box_track)
    plain_fp = fingerprint(pout)
    accepted: list[tuple[str, dict]] = []
    no_effect: list[str] = []
    p = s["params"][c["axis"]]
    for v in c["values"]:
        vid = f"{c['skill']}.{c['axis']}={v}"
        value, why = value_for(s["params"][c["axis"]], v)
        if value is None:
            _results[vid] = {"status": "planned", "why": why}
            continue
        params = {**t.get("params", {}), c["axis"]: value}
        ctx = ToolCtx(sources=dict(srcs), gen_dir=env["root"] / "generated", clip_ids=list(ids),
                      analysis=lambda: env["analysis"](media_set), music_dirs=[env["music"]], logo=env["logo"])
        tag = re.sub(r"[^\w.-]+", "_", f"{c['axis']}_{v}")
        try:
            plan, applied = engine.run(pplan, [{"id": c["skill"], "params": params, "time": t.get("time")}], ctx)
        except ToolError as exc:  # the skill refused with a message to the user: this footage cannot show it
            _results[vid] = {"status": "planned", "why": f"not testable on the test media — the skill says: {exc}",
                             "params": params}
            continue
        try:
            out = render(plan, ctx.sources, root / f"w_{tag}", root / f"{tag}.mp4", env["music"])
            ok, err = decode_check(out)
            info = probe(out)
            assert ok, err
            assert info.has_audio, "no audio stream"
            assert abs(info.duration - plan.total_duration()) < 0.15, f"{info.duration} vs plan {plan.total_duration()}"
        except Exception as exc:  # a variant that does not render is a failure, not a quiet "planned"
            _results[vid] = {"status": "failed", "why": f"{type(exc).__name__}: {exc}"[:300], "params": params}
            raise
        fp = fingerprint(out)
        changed, how = distance(fp, plain_fp)
        if not changed:
            _results[vid] = {"status": "rejected-no-effect", "why": f"same as the plain video: {how}", "params": params}
            if value not in (p.get("default"), t.get("params", {}).get(c["axis"])):
                if vid in KNOWN_NO_EFFECT:
                    _results[vid]["reason"] = KNOWN_NO_EFFECT[vid]
                else:
                    no_effect.append(vid)  # the default can equal the plain video; any other value must change it
            continue
        dup = next(((o, d) for o, ofp in accepted for d in [distance(fp, ofp)] if not d[0]), None)
        if dup:
            _results[vid] = {"status": "rejected-duplicate", "duplicate_of": dup[0], "why": dup[1][1], "params": params}
            continue
        accepted.append((vid, fp))
        _results[vid] = {"status": "ready", "why": f"vs plain: {how}", "params": params,
                         "assumed": applied[0].assumed}
    assert not no_effect, f"these change nothing (a measuring or a skill bug): {no_effect}"
