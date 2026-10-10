"""The agents learn the user's taste (Thompson-sampling bandit) and understand what NOT to do / whom to focus on."""

from __future__ import annotations

import random

import pytest

from cutmind.db import Database
from cutmind.editorial import apply_spec, compile_spec
from cutmind.intent import parse_intent
from cutmind.learning import DEFAULT, Learner
from cutmind.manual import ManualEdit


def test_a_user_who_likes_fast_cuts_gets_fast_cuts(tmp_path):
    """Simulated user: 👍 when the cut was faster, 👎 otherwise. After a few dozen edits the agent mostly cuts fast."""
    learner = Learner(Database(tmp_path / "db.sqlite3"), rng=random.Random(7))
    picks = []
    for n in range(60):
        job = f"job_{n}"
        choice = learner.choose("fan_edit|slow", ["pace"])
        learner.record(job, "p1", "fan_edit|slow", choice)
        learner.reward(job, 1.0 if choice["pace"] == "faster" else 0.0)
        picks.append(choice["pace"])
    assert picks[:10].count("faster") < 8                # it explored at first
    assert picks[-20:].count("faster") >= 16             # and learned
    # other contexts are not affected: a vlog still starts from the default
    assert Learner(Database(tmp_path / "db.sqlite3"))._arm("vlog|no_song", "pace", "faster") == (2.0, 2.0)


def test_rewards_from_words_and_hand_changes(tmp_path):
    learner = Learner(Database(tmp_path / "db.sqlite3"))
    learner.record("j1", "p1", "fan_edit|fast", {"pace": "faster", "punch": "hard", "bw_rate": "many"})
    assert learner.from_prompt("j1", "thoda slow kar do yaar") == ["pace missed"]
    assert learner._arm("fan_edit|fast", "pace", "faster") == (2.0, 3.0)
    ops = ManualEdit.model_validate({"ops": [{"op": "remove_effect", "type": "pulse"}]}).ops
    assert learner.from_manual("j1", ops) == ["punch changed by hand"]
    assert learner.from_prompt("j1", "perfect, same as before") == ["praise"]
    assert learner._arm("fan_edit|fast", "bw_rate", "many")[0] == 3.0  # praise counted
    assert DEFAULT["pace"] == "as_is"


@pytest.mark.parametrize("prompt,check", [
    ("black and white screen mat karo", lambda i: "bw" in i.avoid and not i.color_pass and i.color_preset is None),
    ("make a ronaldo edit, black and white mat karna", lambda i: "bw" in i.avoid),
    ("zoom mat karo aur glitch bhi nahi", lambda i: {"zoom", "glitch", "pulse"} <= set(i.avoid) and not i.effects),
    ("text mat daalo", lambda i: "text" in i.avoid and not i.kinetic_text),
    ("clean up the audio, remove ums", lambda i: "text" not in i.avoid),          # "filler words" are not on-screen text
    ("starting me bahut zoom karo", lambda i: [(t.effect, t.end, t.strength) for t in i.timed_effects] == [("zoom", 3.0, 1.8)]),
    ("caption person ke peeche lagao", lambda i: i.captions and i.captions_behind and "follow" not in i.effects),
    ("caption person ke peeche aa raha hai, aage lao", lambda i: i.text_front and not i.captions_behind),
    ("blue shirt wale person pe focus karo, baaki sab blur kar do", lambda i: (i.focus, i.track_color) == ("blur", "#3B82F6")
     and "blur" not in i.effects),
    ("red jersey wale ko main focus karo", lambda i: (i.focus, i.track_color) == ("dim", "#EF4444")),
    ("black and white old movie jaisa karo", lambda i: i.effects == ["film_bw"] and i.color_preset is None),
    ("jaha jaha me nahi bol raha us part ko cut kar do", lambda i: i.remove_silence and not i.auto),
    ("awaaz saaf kar do, hawa ki noise hai", lambda i: i.voice_cleanup and not i.voice_boost),
    ("hum dono ka video", lambda i: not i.voice_cleanup),
    ("is reference video jaisa mera video edit karo", lambda i: i.use_reference),
    ("sample example ke liye simple edit", lambda i: not i.use_reference),
])
def test_what_to_do_and_what_not_to_do(prompt, check):
    assert check(parse_intent(prompt)), parse_intent(prompt)


def test_no_black_and_white_beats_the_fan_edit_genre(fake_project):
    """A fan edit normally gets a colour pass; "black and white mat karna" switches it off."""
    ctx = fake_project("make a messi edit, black and white mat karna")
    final = apply_spec(ctx.intent, compile_spec(ctx.prompt, ctx.intent, ctx.analysis))
    assert not final.color_pass and final.color_preset != "bw"
    assert apply_spec(parse_intent("make a messi edit"), compile_spec("make a messi edit", parse_intent("make a messi edit"),
                                                                       ctx.analysis)).color_pass
