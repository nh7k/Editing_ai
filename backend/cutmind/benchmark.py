"""Benchmark: the same desi prompts edited WITHOUT and WITH the editorial brain, scored on professional criteria.

    python -m cutmind.benchmark            # writes docs/VIDEO_EDITOR_BENCHMARK.md

Scenarios use the generated test clips (tests/media/generated): a talking clip with pauses and an "um", a tone
clip, and a fast-changing scenes clip. Every criterion is measured on the real render / plan — no human scoring,
so it measures "did the edit follow professional rules", not taste.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .agents.base import AgentContext, ClipRef
from .agents.director import DirectorAgent
from .config import get_settings
from .ffmpeg_utils import probe
from .fx_catalog import BW_PASS
from .media_gen import make_clips, make_music

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "tests" / "media" / "generated"
Check = Callable[[Any, Any, float], bool]  # (result, plan, source seconds) -> ok


def _avg_shot(plan: Any) -> float:
    tl = plan.timeline()
    return sum(e.duration for e in tl) / max(1, len(tl))


def _review(result: Any, name: str) -> bool | None:
    c = next((c for c in result.review.checks if c.name == name), None)
    return None if c is None else c.passed


@dataclass
class Scenario:
    id: str
    prompt: str
    clips: list[str]
    expect: list[tuple[str, Check]]


SCENARIOS = [
    Scenario("talking_mast", "bhai isko mast bana de", ["a"], [
        ("pauses removed (shorter than the source)", lambda r, p, src: p.total_duration() < src - 1.0),
        ("captions for the speech", lambda r, p, src: any(t.kind == "caption" for t in p.text)),
        ("jump cuts covered or key words punched", lambda r, p, src: any(e.type in ("punch", "punch_static") for e in p.effects)),
        ("speech not chopped to a beat (avg shot > 1.5 s)", lambda r, p, src: _avg_shot(p) > 1.5),
        ("no template transitions", lambda r, p, src: not [t for t in p.transitions if t.after >= 0]),
    ]),
    Scenario("party_reel", "party ka mast energetic reel insta ke liye", ["c", "b"], [
        ("vertical 9:16 for Instagram", lambda r, p, src: p.canvas.aspect_ratio == "9:16"),
        ("music", lambda r, p, src: bool(p.audio.music)),
        ("fast pacing (avg shot ≤ 2.5 s)", lambda r, p, src: _avg_shot(p) <= 2.5),
        ("cuts on the beat", lambda r, p, src: p.audio.beat_sync),
        ("hook: opening shot is energetic", lambda r, p, src: _review(r, "hook_strength") is True),
        ("ends on a strong moment", lambda r, p, src: _review(r, "ending_strength") is True),
        ("restraint: no template transitions, ≤ 2 flashes",
         lambda r, p, src: not [t for t in p.transitions if t.after >= 0] and sum(e.type == "flash" for e in p.effects) <= 2),
    ]),
    Scenario("fan_edit", "make a max verstappen edit with nice animations", ["c", "b"], [
        ("cuts on the beat, fast", lambda r, p, src: p.audio.beat_sync and _avg_shot(p) <= 1.5),
        ("punch on the beats", lambda r, p, src: any(e.type == "pulse" and e.times for e in p.effects)),
        ("colour pass (some shots B&W, not all)",
         lambda r, p, src: 0 < len({e.target for e in p.effects if e.type in BW_PASS}) < len(p.clips)),
        ("big words on the beat (MAX / VERSTAPPEN)", lambda r, p, src: [t.text for t in p.text if t.kind == "text"][:2] == ["MAX", "VERSTAPPEN"]),
        ("no template transitions", lambda r, p, src: not [t for t in p.transitions if t.after >= 0]),
    ]),
    Scenario("travel_restrained", "travel vlog jaisa bana, over mat kar", ["c", "b"], [
        ("music", lambda r, p, src: bool(p.audio.music)),
        ("no template transitions", lambda r, p, src: not [t for t in p.transitions if t.after >= 0]),
        ("restraint: at most 2 video effects", lambda r, p, src: len({e.type for e in p.effects}) <= 2),
        ("a look (graded)", lambda r, p, src: p.color.preset != "none"),
    ]),
    Scenario("podcast_premium", "podcast clip, premium captions, ye banda jab important baat bole tab zoom kar", ["a"], [
        ("captions", lambda r, p, src: any(t.kind == "caption" for t in p.text)),
        ("premium caption style", lambda r, p, src: any(t.style.preset == "hormozi" for t in p.text if t.kind == "caption")),
        ("pauses removed", lambda r, p, src: p.total_duration() < src - 1.0),
        ("punch-ins on key words", lambda r, p, src: any(e.type == "punch" for e in p.effects)),
        ("cleaner voice", lambda r, p, src: p.audio.voice_cleanup),
    ]),
    Scenario("boring_hata", "boring hata de", ["a"], [
        ("dead air removed", lambda r, p, src: p.total_duration() < src - 1.0),
        ("no word cut", lambda r, p, src: _review(r, "no_mid_word_cuts") is not False),
    ]),
    Scenario("cinematic_restrained", "thoda cinematic bana, over mat kar", ["c"], [
        ("cinematic grade", lambda r, p, src: p.color.preset == "cinematic"),
        ("no template transitions", lambda r, p, src: not [t for t in p.transitions if t.after >= 0]),
        ("restraint: at most 2 video effects", lambda r, p, src: len({e.type for e in p.effects}) <= 2),
        ("no flashes", lambda r, p, src: not any(e.type == "flash" for e in p.effects)),
    ]),
]


def run(editorial: bool) -> list[dict[str, Any]]:
    base = get_settings()
    rows = []
    names = {"a": "clip_a_talk.mp4", "b": "clip_b_tone.mp4", "c": "clip_c_scenes.mp4"}
    if not all((MEDIA / n).exists() for n in names.values()):
        make_clips(MEDIA)
    music = ROOT / "backend" / "assets" / "music"
    if not any(music.glob("*.m4a")):
        make_music(music)
    for sc in SCENARIOS:
        tmp = Path(tempfile.mkdtemp(prefix="cmbench_"))
        try:
            st = replace(base, data_dir=tmp / "data", planner_mode="mock", editorial=editorial, music_dir=music)
            clips = [ClipRef(k.upper(), MEDIA / names[k], names[k], i) for i, k in enumerate(sc.clips)]
            ctx = AgentContext(job_id=f"bench_{sc.id}", prompt=sc.prompt, clips=clips, settings=st,
                               work_dir=tmp / "proj" / "work" / sc.id)
            t0 = time.perf_counter()
            res = DirectorAgent().run_job(ctx, tmp / "out.mp4")
            secs = time.perf_counter() - t0
            src = sum(probe(c.path).duration for c in clips)
            hits = [(name, bool(fn(res, res.plan, src))) for name, fn in sc.expect]
            rows.append({"id": sc.id, "prompt": sc.prompt, "editorial": editorial, "seconds": round(secs, 1),
                         "match": res.review.match_percent, "hits": hits,
                         "score": round(100 * sum(h for _, h in hits) / len(hits)),
                         "decisions": len(res.plan.decisions), "duration": round(res.plan.total_duration(), 1)})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return rows


def report(base: list[dict[str, Any]], brain: list[dict[str, Any]]) -> str:
    lines = ["# Video editor benchmark", "",
             "Same desi prompts, same clips, edited twice: **baseline** (prompt parser only) vs **editorial brain**",
             "(Hinglish concepts → content type → skills → inferred professional choices). Each criterion is measured on",
             "the real render/plan. Generated test clips; mock (rules) planner; CPU only. Reproduce: `python -m cutmind.benchmark`.",
             "", "| Scenario | Prompt | Baseline | Editorial brain | Reviewer match (base → brain) | Time (base → brain) | Decisions logged |",
             "|---|---|---|---|---|---|---|"]
    for a, b in zip(base, brain, strict=True):
        lines.append(f"| {a['id']} | {a['prompt']} | {a['score']}% | **{b['score']}%** | {a['match']} → {b['match']} | "
                     f"{a['seconds']}s → {b['seconds']}s | {b['decisions']} |")
    avg_a = sum(r["score"] for r in base) / len(base)
    avg_b = sum(r["score"] for r in brain) / len(brain)
    lines += ["", f"**Average professional-criteria score: {avg_a:.0f}% → {avg_b:.0f}%**", "", "## Criteria per scenario", ""]
    for a, b in zip(base, brain, strict=True):
        lines.append(f"**{a['id']}** — “{a['prompt']}”")
        lines.append("")
        lines.append("| Criterion | Baseline | Brain |")
        lines.append("|---|---|---|")
        for (name, ha), (_n, hb) in zip(a["hits"], b["hits"], strict=True):
            lines.append(f"| {name} | {'✓' if ha else '✗'} | {'✓' if hb else '✗'} |")
        lines.append("")
    lines += ["## Limits of this benchmark", "",
              "* Criteria are rules a professional editor would follow; they are not a human taste rating.",
              "* Synthetic clips (TTS speech, test patterns) — real footage behaves differently; the user's own footage",
              "  runs are in TEST_REPORT.md.",
              "* The local-LLM planner was not used here (rules planner), so this isolates the editorial brain."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    a = run(False)
    b = run(True)
    out = ROOT / "docs" / "VIDEO_EDITOR_BENCHMARK.md"
    out.write_text(report(a, b), encoding="utf-8")
    print(out.read_text(encoding="utf-8"))
