"""Scoring, lessons storage/injection, feedback points and the leaderboard."""

from cutmind.agents.base import AgentContext
from cutmind.agents.color import ColorAgent
from cutmind.agents.director import DirectorAgent
from cutmind.agents.reviewer import FAIL_POINTS, PASS_POINTS, Check, Review
from cutmind.db import Database


def make_review():
    return Review([
        Check("duration", "cutter", False, "18.0s vs expected 15.0s", {"actual": 18, "expected": 15}),
        Check("clip_order", "cutter", True, "ok"),
        Check("silence_removed", "cutter", True, "ok"),
        Check("color_applied", "color", False, "too subtle"),
        Check("captions_present", "effects", True, "ok"),
        Check("file_plays", "director", True, "ok"),
    ])


def test_scores_and_match_percent():
    r = make_review()
    s = r.agent_scores
    # weighted: duration(3) failed, clip_order(1) + silence_removed(2) passed → 3/6
    assert s["cutter"] == 50.0 and s["color"] == 0.0 and s["effects"] == 100.0
    assert s["audio"] == 100.0  # no checks → not penalised
    assert r.match_percent == round(100 * 9 / 14, 1)
    assert [c.name for c in r.failed_for("cutter")] == ["duration"]
    assert make_review().checks[0].points == FAIL_POINTS and make_review().checks[1].points == PASS_POINTS


def test_record_writes_points_and_lessons(tmp_path, settings):
    db = Database(tmp_path / "t.sqlite3")
    ctx = AgentContext(job_id="j1", prompt="p", clips=[], settings=settings, db=db)
    DirectorAgent().record(ctx, make_review(), attempt=1)
    board = {a["name"]: a for a in db.scoreboard()}
    assert board["cutter"]["total_points"] == FAIL_POINTS + 2 * PASS_POINTS
    assert board["color"]["total_points"] == FAIL_POINTS
    assert board["cutter"]["last_delta"] == FAIL_POINTS + 2 * PASS_POINTS
    lessons = db.recent_lessons("cutter")
    assert len(lessons) == 1 and lessons[0]["text"].startswith("duration:")
    # leaderboard ordering: highest points first
    totals = [a["total_points"] for a in db.scoreboard()]
    assert totals == sorted(totals, reverse=True)


def test_lessons_dedupe_and_limit(tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    for i in range(3):
        db.add_lesson("color", "color_applied", f"old lesson {i}", None)
    for i in range(8):
        db.add_lesson("color", f"check_{i}", f"lesson {i}", None)
    got = db.recent_lessons("color", 5)
    assert len(got) == 5
    assert got[0]["text"] == "lesson 7"
    assert sum("color_applied" == g["check_name"] for g in db.recent_lessons("color", 50)) == 1  # deduped per check


def test_lessons_are_injected_into_prompt(fake_project, tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    db.add_lesson("color", "color_applied", "color_applied: make the warm grade clearly visible", None)
    ctx = fake_project("warm color")
    ctx.db = db
    prompt = ColorAgent().run(ctx).prompt
    assert "LESSONS FROM PAST MISTAKES" in prompt and "clearly visible" in prompt
    # and they're recorded in the runs table
    assert db.one("SELECT COUNT(*) AS n FROM runs WHERE agent='color'")["n"] == 1


def test_final_score_rows_do_not_change_totals(tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    db.add_score("j", "audio", 0, "_final_score", 90, "final")
    db.add_score("j", "audio", 1, "music_present", 10, "ok")
    a = next(x for x in db.scoreboard() if x["name"] == "audio")
    assert a["total_points"] == 10 and a["avg_score"] == 90 and a["runs"] == 1
