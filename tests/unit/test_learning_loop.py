"""Learning loop (docs/UNDERSTANDING_REVIEW.md, Phase 5): reactions to a reading become a per-user, decaying,
signed preference for the same words — never a change to the shared skills."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cutmind import unmet
from cutmind.db import Database
from cutmind.tools.resolve import resolve
from cutmind.unmet import UnmetLog

CHOICES = [{"id": "flash"}, {"id": "white_screen_card"}]


def log(tmp_path):  # noqa: ANN001, ANN201
    return UnmetLog(Database(tmp_path / "d.sqlite3"))


def test_a_picked_chip_helps_and_an_undo_hurts_the_same_words(tmp_path):
    lg = log(tmp_path)
    rid = lg.log("p1", "yaha screen white kar do", {}, "act", CHOICES, applied=["flash"], job_id="j1")
    lg.pick(rid, "white_screen_card")
    lg.log("p2", "yaha screen white kar do", {}, "act", CHOICES, applied=["flash"], job_id="j2")
    lg.undone("j2")
    got = lg.learned("yahan screen wite kardo")  # same words, other spelling
    assert got["white_screen_card"] > 0 and got["flash"] < 0, got
    # and the resolver follows it: the safed screen now leads for these words
    r = resolve("yaha screen white kar do", {"marker_time": 2.0, "learned": got})
    assert r.choices[0]["id"] == "white_screen_card", r.trace


def test_a_quick_rephrase_counts_against_the_reading(tmp_path):
    lg = log(tmp_path)
    lg.log("p1", "zoom karo thoda", {}, "apply", [{"id": "zoom_in"}], applied=["zoom_in"], job_id="j1")
    lg.log("p1", "nahi, paas jao", {}, "apply", [{"id": "zoom_in"}], applied=["zoom_in"], job_id="j2")
    assert lg.learned("zoom karo thoda").get("zoom_in", 0) < 0


def test_old_evidence_fades(tmp_path, monkeypatch):
    lg = log(tmp_path)
    lg.pick(lg.log("p1", "safed karo", {}, "choose", CHOICES), "flash")
    fresh = lg.learned("safed karo")["flash"]
    later = datetime.now(timezone.utc) + timedelta(days=60)
    monkeypatch.setattr(unmet, "_now", lambda: later)
    assert lg.learned("safed karo")["flash"] < fresh / 3  # two half-lives


def test_reset_my_data_deletes_everything(tmp_path):
    lg = log(tmp_path)
    lg.log("p1", "safed karo", {}, "choose", CHOICES)
    assert lg.forget() == 1 and lg.recent() == [] and lg.learned("safed karo") == {}


def test_a_different_request_soon_after_is_not_a_rephrase(tmp_path):
    """Found live: 'black and white karo' then a different comment within 30 s marked black and white as a miss."""
    lg = log(tmp_path)
    lg.log("p1", "black and white karo", {}, "apply", [{"id": "grayscale"}], applied=["grayscale"], job_id="j1")
    lg.log("p1", "yaha pehle jaisa kar do", {}, "act", [{"id": "restore_normal"}], applied=["restore_normal"], job_id="j2")
    assert lg.learned("black and white karo").get("grayscale", 0) >= 0
