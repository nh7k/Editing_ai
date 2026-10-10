"""Shared fixtures. Test media is generated with FFmpeg (no copyrighted files)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("CUTMIND_TRANSLATOR", "off")  # tests never depend on the downloaded translator model
# … nor on a downloaded planner LLM: rules unless a test sets a provider (LLM tests use the MockProvider;
# the real GGUF models are measured by backend/scripts/bench_llm.py and tests/integration/test_llm_real.py)
os.environ.setdefault("LLM_PROVIDER", "rules")
os.environ.setdefault("RATE_LIMIT_PER_MIN", "0")  # suites send many edits a minute; test_mind_api sets its own limit

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from cutmind.agents.analyzer import ClipAnalysis, ProjectAnalysis, Word  # noqa: E402
from cutmind.agents.base import AgentContext, ClipRef  # noqa: E402
from cutmind.config import Settings  # noqa: E402
from cutmind.intent import parse_intent  # noqa: E402
from cutmind.media_gen import make_clips, make_music  # noqa: E402

MEDIA_DIR = ROOT / "tests" / "media" / "generated"
RESULTS_DIR = ROOT / "tests" / "results"


@pytest.fixture(scope="session")
def media() -> dict[str, Path]:
    """Three generated clips (+ speech wav). Generated once, reused across runs."""
    names = {"a": "clip_a_talk.mp4", "b": "clip_b_tone.mp4", "c": "clip_c_scenes.mp4", "speech": "speech.wav"}
    if not all((MEDIA_DIR / n).exists() for n in names.values()):
        make_clips(MEDIA_DIR)
    return {k: MEDIA_DIR / n for k, n in names.items()}


@pytest.fixture(scope="session")
def music_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = BACKEND / "assets" / "music"
    if not any(d.glob("*.m4a")):
        make_music(d)
    return d


def make_settings(data_dir: Path, music_dir: Path, **overrides: object) -> Settings:
    s = Settings()
    s.planner_mode = "mock"
    s.data_dir = data_dir
    s.music_dir = music_dir
    s.enable_transcription = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@pytest.fixture
def settings(tmp_path: Path, music_dir: Path) -> Settings:
    return make_settings(tmp_path / "data", music_dir)


# ---- synthetic analysis for fast agent unit tests (no FFmpeg needed) --------------------------------
def words(*items: tuple[str, float, float]) -> list[Word]:
    return [Word(text=t, start=s, end=e) for t, s, e in items]


@pytest.fixture
def fake_project(tmp_path: Path, music_dir: Path):
    """3 clips: A speech with pauses, B tone with a silent gap, C no speech; analysis hand-made."""
    clips = [ClipRef("A", tmp_path / "a.mp4", "a.mp4", 0), ClipRef("B", tmp_path / "b.mp4", "b.mp4", 1),
             ClipRef("C", tmp_path / "c.mp4", "c.mp4", 2)]
    analysis = ProjectAnalysis(clips={
        "A": ClipAnalysis(clip_id="A", duration=14.0, width=1280, height=720, fps=30, has_audio=True,
                          silences=[(2.0, 5.0), (7.0, 9.5)],
                          words=words(("Welcome", 0.2, 0.7), ("to", 0.7, 0.85), ("the", 0.85, 1.0), ("mountains.", 1.0, 1.9),
                                      ("Um,", 5.1, 5.5), ("the", 5.6, 5.8), ("weather", 5.8, 6.2), ("was", 6.2, 6.4),
                                      ("amazing.", 6.4, 6.9), ("Let's", 9.7, 10.0), ("go", 10.0, 10.2),
                                      ("explore", 10.2, 10.8), ("the", 10.8, 10.95), ("town.", 10.95, 11.6)),
                          luma=0.55, quality=0.9),
        "B": ClipAnalysis(clip_id="B", duration=8.0, width=640, height=480, fps=30, has_audio=True,
                          silences=[(3.0, 5.5)], luma=0.30, quality=0.5),
        "C": ClipAnalysis(clip_id="C", duration=12.0, width=1280, height=720, fps=25, has_audio=True,
                          luma=0.6, quality=0.7),
    })

    def build(prompt: str, **kw: object) -> AgentContext:
        s = make_settings(tmp_path / "data", music_dir, **{k: v for k, v in kw.items() if k != "options"})
        ctx = AgentContext(job_id="job_test", prompt=prompt, clips=clips, settings=s, work_dir=tmp_path / "work",
                           options=kw.get("options", {}))  # type: ignore[arg-type]
        ctx.intent = parse_intent(prompt)
        ctx.analysis = analysis
        return ctx

    return build
