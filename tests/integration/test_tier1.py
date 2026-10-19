"""Tier 1 render tests: every built Tier 1 skill runs through the tool engine on generated media, is rendered for
real with FFmpeg, and its output is measured (tier1_checks.py). Plus the invariants every patch must keep:
decodes, has audio, audio/video lengths agree, the originals are untouched.

Results go to skills/tier1_results.json (docs/TIER1_STATUS.md is written from it).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from conftest import make_settings

from cutmind.ffmpeg_utils import decode_check, probe, run_ffmpeg
from cutmind.plan import EditPlan
from cutmind.renderer import render
from cutmind.tools import engine, spec
from cutmind.tools.engine import ToolCtx

from tier1_checks import CHECKS, Run

pytestmark = pytest.mark.integration
RESULTS = Path(__file__).resolve().parents[2] / "skills" / "tier1_results.json"
_results: dict[str, dict] = {}


@pytest.fixture(scope="module")
def tones(tmp_path_factory):
    """Three 6 s clips, each with its own picture and a pure tone: T1 440 Hz, T2 880 Hz, T3 660 Hz."""
    d = tmp_path_factory.mktemp("tones")
    out = {}
    for cid, src, hz in (("T1", "testsrc2", 440), ("T2", "smptehdbars", 880), ("T3", "rgbtestsrc", 660)):
        f = d / f"{cid}.mp4"
        run_ffmpeg(["-f", "lavfi", "-i", f"{src}=s=640x360:r=30:d=6", "-f", "lavfi", "-i",
                    f"sine=frequency={hz}:sample_rate=48000:duration=6", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(f)])
        out[cid] = f
    return out


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    """3 s, 1280x720: a white 100x100 box moving left → right (x = 100 + 326·t), silent."""
    out = tmp_path_factory.mktemp("box") / "box.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=1280x720:d=3:r=30", "-f", "lavfi", "-i",
                "color=c=white:s=100x100:d=3:r=30", "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=3",
                "-filter_complex", "[0:v][1:v]overlay=x='100+326*t':y=310[v]", "-map", "[v]", "-map", "2:a", "-t", "3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)])
    return out


def box_track(path, target="person", cache_dir=None):
    from cutmind.tracking import Track

    pts = [(t / 10, (150 + 326 * t / 10) / 1280, 360 / 720, 100 / 1280, 100 / 720) for t in range(0, 31, 5)]
    return Track(target=target, points=pts, found=1.0, detector="test-known-path")


@pytest.fixture(scope="module")
def dark(tmp_path_factory):
    """6 s of an under-exposed test pattern (mean brightness ~0.2) with a tone."""
    out = tmp_path_factory.mktemp("dark") / "dark.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6", "-f", "lavfi", "-i",
                "sine=frequency=500:sample_rate=48000:duration=6", "-vf", "eq=brightness=-0.28:contrast=0.8",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)])
    return out


@pytest.fixture(scope="module")
def soft(tmp_path_factory):
    """6 s of a camera-like test picture: half the saturation and less contrast than testsrc2's pure primaries
    (a look / contrast / saturation change has room to show)."""
    out = tmp_path_factory.mktemp("soft") / "soft.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6", "-f", "lavfi", "-i",
                "sine=frequency=500:sample_rate=48000:duration=6", "-vf", "eq=saturation=0.45:contrast=0.75,gblur=sigma=1",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)])
    return out


@pytest.fixture(scope="module")
def noisy(tmp_path_factory):
    """6 s: a 300 Hz 'voice' tone in bursts (0.5-2.5 s, 3.5-5.5 s) over steady pink noise (a fan / hiss)."""
    out = tmp_path_factory.mktemp("noisy") / "noisy.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6", "-f", "lavfi", "-i",
                "aevalsrc='0.3*sin(2*PI*300*t)*(between(t,0.5,2.5)+between(t,3.5,5.5))':s=48000:d=6",
                "-f", "lavfi", "-i", "anoisesrc=c=pink:r=48000:a=0.05:d=6",
                "-filter_complex", "[1:a][2:a]amix=inputs=2:normalize=0[a]", "-map", "0:v", "-map", "[a]",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)])
    return out


@pytest.fixture(scope="module")
def shaky(tmp_path_factory):
    """5 s of a hand-held looking clip: the picture jumps around by a few pixels every frame."""
    out = tmp_path_factory.mktemp("shaky") / "shaky.mp4"
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=720x420:r=30:d=5", "-f", "lavfi", "-i",
                "sine=frequency=500:sample_rate=48000:duration=5",
                "-vf", "crop=640:360:x='40+30*sin(t*13)+12*sin(t*31)':y='30+22*cos(t*11)+9*sin(t*29)'",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)])
    return out


def _photos(root: Path) -> dict[str, Path]:
    """Two photos made into still clips the way an upload does it (cutmind.photos): detailed, different pictures."""
    from PIL import Image, ImageDraw

    from cutmind.photos import photo_to_clip

    out = {}
    for k, (bg, fg) in {"P1": ((20, 40, 90), (240, 200, 40)), "P2": ((90, 20, 30), (40, 220, 200))}.items():
        im = Image.new("RGB", (1280, 720), bg)
        dr = ImageDraw.Draw(im)
        for i in range(0, 1280, 64):  # a grid: zoom and pan are measurable
            dr.line([(i, 0), (i, 720)], fill=(200, 200, 200), width=3)
        for j in range(0, 720, 64):
            dr.line([(0, j), (1280, j)], fill=(200, 200, 200), width=3)
        dr.ellipse([440, 160, 840, 560], fill=fg)
        photo = root / f"{k}.jpg"
        im.save(photo, quality=95)
        out[k] = photo_to_clip(photo, root / f"{k}.mp4", seconds=4.0)
    return out


@pytest.fixture(scope="module")
def env(tmp_path_factory, media, tones, box, dark, soft, noisy, shaky, music_dir):
    root = tmp_path_factory.mktemp("tier1")
    settings = make_settings(root / "data", music_dir)
    sets = {
        "tones": (["T1", "T2", "T3"], {k: tones[k] for k in ("T1", "T2", "T3")}),
        "talk": (["A"], {"A": media["a"]}),
        "default": (["T1", "T2"], {k: tones[k] for k in ("T1", "T2")}),
        "vertical": (["T1", "T2"], {k: tones[k] for k in ("T1", "T2")}),
        "box": (["B"], {"B": box}),
        "dark": (["D"], {"D": dark}),
        "soft": (["S"], {"S": soft}),
        "noisy": (["N"], {"N": noisy}),
        "scenes": (["C"], {"C": media["c"]}),
        "shaky": (["K"], {"K": shaky}),
        "gap": (["G"], {"G": media["b"]}),
        "photos": (["P1", "P2"], _photos(root)),
    }
    canvas = {"vertical": "9:16", "box": "9:16"}
    analyses: dict[str, object] = {}

    def analysis(name: str):
        if name not in analyses:
            from cutmind.agents.analyzer import AnalyzerAgent
            from cutmind.agents.base import AgentContext, ClipRef

            ids, srcs = sets[name]
            ctx = AgentContext(job_id=f"an_{name}", prompt="analyze", clips=[ClipRef(i, srcs[i], srcs[i].name, k)
                                                                             for k, i in enumerate(ids)],
                               settings=settings, work_dir=root / f"an_{name}")
            ctx.need_transcript = True
            AnalyzerAgent().run(ctx)
            analyses[name] = ctx.analysis
        return analyses[name]

    plains: dict[str, tuple[EditPlan, Path]] = {}

    def plain(name: str) -> tuple[EditPlan, Path]:
        if name not in plains:
            ids, srcs = sets[name]
            p = engine.first_plan(ids, {i: probe(srcs[i]).duration for i in ids}, canvas.get(name, "16:9"), 360)
            out = render(p, srcs, root / f"plain_{name}", root / f"plain_{name}.mp4")
            plains[name] = (p, out)
        return plains[name]

    def words(path: Path):
        from cutmind.agents.analyzer import AnalyzerAgent
        from cutmind.agents.base import AgentContext, ClipRef

        ctx = AgentContext(job_id="w", prompt="w", clips=[ClipRef("X", path, path.name, 0)], settings=settings,
                           work_dir=root / f"w_{path.stem}")
        ctx.need_transcript = True
        AnalyzerAgent().run(ctx)
        return [(w.text, w.start, w.end) for w in ctx.analysis.get("X").words]

    from PIL import Image, ImageDraw

    logo = root / "logo.png"  # a test logo: a red disc with a white L on transparency
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.ellipse([10, 10, 190, 190], fill=(230, 30, 40, 255))
    dr.rectangle([80, 50, 100, 150], fill=(255, 255, 255, 255))
    dr.rectangle([80, 130, 140, 150], fill=(255, 255, 255, 255))
    img.save(logo)
    return {"root": root, "sets": sets, "analysis": analysis, "plain": plain, "words": words, "music": music_dir,
            "logo": logo}


@pytest.fixture(scope="module", autouse=True)
def _save():
    yield
    old = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    old.update(_results)
    RESULTS.write_text(json.dumps(old, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def _built() -> list[dict]:
    names = engine.builder_names()
    only = os.environ.get("TIER1_CATEGORY")
    return [s for s in spec.load().values() if s["builder"] in names and (not only or s["category"] in only.split(","))]


def _stat(paths: list[Path]) -> list[tuple[int, int]]:
    return [(p.stat().st_size, p.stat().st_mtime_ns) for p in paths]


@pytest.mark.parametrize("s", _built(), ids=lambda s: s["id"])
def test_tier1_skill_renders(s, env, monkeypatch):
    sid = s["id"]
    t = s["test"]
    media_set = t.get("media", "default")
    ids, srcs = env["sets"][media_set]
    pplan, pout = env["plain"](media_set)
    sources = dict(srcs)
    if t.get("setup"):  # the plain render for this test is the plan after the setup calls
        sctx = ToolCtx(sources=dict(srcs), gen_dir=env["root"] / "generated", clip_ids=list(ids),
                       music_dirs=[env["music"]], analysis=lambda: env["analysis"](media_set))
        pplan, _ = engine.run(pplan, t["setup"], sctx)
        pout = render(pplan, srcs, env["root"] / f"plain_w_{sid}", env["root"] / f"plain_{sid}.mp4", env["music"])
    if media_set == "box":  # a known subject path instead of the person detector (no people footage here)
        import cutmind.tracking

        monkeypatch.setattr(cutmind.tracking, "track_clip", box_track)
    before = _stat(list(srcs.values()))
    ctx = ToolCtx(sources=sources, gen_dir=env["root"] / "generated", clip_ids=list(ids),
                  analysis=lambda: env["analysis"](media_set), music_dirs=[env["music"]], logo=env["logo"])
    call = {"id": sid, "params": dict(t.get("params", {})), "time": t.get("time")}
    try:
        plan, applied = engine.run(pplan, [call], ctx)
        out = render(plan, sources, env["root"] / f"w_{sid}", env["root"] / f"{sid}.mp4", env["music"])
        ok_dec, err = decode_check(out)
        info = probe(out)
        assert ok_dec, err
        assert info.has_audio, "no audio stream"
        assert abs(info.duration - plan.total_duration()) < 0.15, f"{info.duration} vs plan {plan.total_duration()}"
        assert _stat(list(srcs.values())) == before, "an original file changed"
        media = {**sources, "_clips": [srcs[i] for i in ids], "_music": env["music"]}
        run = Run(plan, out, applied, pout, pplan, media, applied[0].params, env["words"])
        ok, detail = CHECKS[t["check"]](run)
        _results[sid] = {"ok": bool(ok), "check": t["check"], "detail": detail[:300],
                         "explain": applied[0].to_dict()["where"], "assumed": applied[0].assumed}
        assert ok, detail
    except Exception as exc:
        _results.setdefault(sid, {"ok": False, "check": t["check"], "detail": f"{type(exc).__name__}: {exc}"[:300]})
        raise
