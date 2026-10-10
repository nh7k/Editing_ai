"""What real users type to the agent (rough Hinglish, typos, no punctuation) — every message must be understood
as the change the user means. A message the rules do not understand must never silently become a "default edit".

Each case: (message, check on the understood intent). Messages are sent on top of a previous edit (`LAST`), as in
the chat, so follow-ups are merged with what is already there.
"""

from __future__ import annotations

import pytest

from cutmind.intent import Intent, parse_intent
from cutmind.memory import is_follow_up, merge_with_last, wants_repeat

# the edit the user already has (a 15 s fan edit with music and a title)
LAST = parse_intent("Fan edit, 15 seconds, 9:16, fast cuts on the beat, upbeat music, title 'RONALDO'").model_dump(
    exclude_defaults=True)


def understood(msg: str) -> Intent:
    it = parse_intent(msg)
    rep = wants_repeat(msg)
    if rep or it.remove or is_follow_up(msg, it):
        it = merge_with_last(it, LAST, Intent().model_dump(), rep)
    return it


CASES = [
    # ---- sound -------------------------------------------------------------------------------------------
    ("audio nhi aa rhai ha usko thik karo or audio lagao", lambda i: i.restore_audio and not i.mute),
    ("awaz nhi aa rahi", lambda i: i.restore_audio and not i.mute),
    ("sound band ho gaya wapas lao", lambda i: i.restore_audio and not i.mute),
    ("video me awaaz hi nahi hai", lambda i: i.restore_audio),
    ("gaane ki awaaz kam karo", lambda i: i.music_volume is not None and i.music_volume < 0.5),
    ("music thoda dheere karo", lambda i: i.music_volume is not None and i.music_volume < 0.5),
    ("gaana tez karo", lambda i: i.music_volume is not None and i.music_volume > 0.5),
    ("meri awaaz tez karo", lambda i: i.voice_boost),
    ("video ki awaaz hata do", lambda i: i.mute),
    ("mute kar do", lambda i: i.mute),
    ("gaana hata do", lambda i: not i.music),
    ("bina music ke banao", lambda i: not i.music),
    ("koi gaana laga do", lambda i: i.music),
    ("background music daal do", lambda i: i.music),
    ("sad gaana lagao", lambda i: i.music and i.music_mood == "calm"),
    ("mera gaana use karo", lambda i: i.use_my_song),
    ("noise hata do", lambda i: i.voice_cleanup),
    ("bass badha do", lambda i: i.bass_boost > 0),
    # ---- text / captions ---------------------------------------------------------------------------------
    ("captions laga do", lambda i: i.captions),
    ("subtitle daalo", lambda i: i.captions),
    ("caption hata do", lambda i: not i.captions),
    ("text hata do", lambda i: i.title is None and not i.kinetic_text),
    ("RONALDO likh do", lambda i: i.title == "RONALDO"),
    ("upar naam likh do 'CR7'", lambda i: i.title == "CR7"),
    ("text bada karo", lambda i: bool(i.recognized) and "text" in " ".join(i.recognized).lower()),
    ("text person ke peeche", lambda i: i.text_behind),
    # ---- colour / look -----------------------------------------------------------------------------------
    ("black and white kar do", lambda i: i.color_preset == "bw"),
    ("black and white hata do", lambda i: i.color_preset != "bw" and "bw" in i.avoid),
    ("colour wapas lao", lambda i: i.color_preset is None and not i.color_pass),
    ("thoda bright karo", lambda i: i.brightness is not None and i.brightness > 0 or "bright" in " ".join(i.recognized)),
    ("thoda dark karo", lambda i: "dark" in " ".join(i.recognized).lower()),
    ("warm color karo", lambda i: i.color_preset == "warm"),
    ("cinematic look do", lambda i: i.color_preset == "cinematic"),
    ("purani film jaisa", lambda i: i.color_preset in ("vintage", "faded_film") or "film_bw" in i.effects),
    ("rang tez karo", lambda i: i.color_preset == "vivid" or (i.saturation or 0) > 0 or "satur" in " ".join(i.recognized)),
    # ---- pace / length / speed ---------------------------------------------------------------------------
    ("thoda slow karo", lambda i: (i.pace_change or 1) > 1),
    ("aur fast karo", lambda i: (i.pace_change or 1) < 1),
    ("slow motion me karo", lambda i: i.slow_motion),
    ("end me slow motion", lambda i: i.slow_end),
    ("30 sec ka karo", lambda i: i.target_duration == 30),
    ("thoda chhota karo", lambda i: i.target_duration is not None and i.target_duration < 15),
    ("thoda lamba karo", lambda i: i.target_duration is not None and i.target_duration > 15),
    ("1 minute ka bana do", lambda i: i.target_duration == 60),
    ("video ulta chala do", lambda i: i.reverse_playback),
    # ---- cutting -----------------------------------------------------------------------------------------
    ("jahan koi nahi bol raha wo part hata do", lambda i: i.remove_silence),
    ("boring part kaat do", lambda i: i.remove_idle or i.auto),
    ("best part pehle dikhao", lambda i: i.hook_first),
    ("clips ka order ulta karo", lambda i: i.order == "reverse"),
    # ---- effects / transitions ---------------------------------------------------------------------------
    ("zoom effect lagao", lambda i: "zoom" in i.effects),
    ("zoom hata do", lambda i: "zoom" not in i.effects and "zoom" in i.avoid),
    ("starting me zoom karo", lambda i: any(t.effect == "zoom" for t in i.timed_effects)),
    ("shake effect daalo", lambda i: "shake" in i.effects),
    ("glitch effect", lambda i: "glitch" in i.effects),
    ("transition laga do", lambda i: i.transition is not None),
    ("transition hata do", lambda i: i.transition is None),
    ("fade in fade out", lambda i: i.transition == "fade"),
    ("blur background", lambda i: "blur_background" in i.effects),
    ("blue shirt wale pe focus baaki blur", lambda i: i.focus == "blur" and i.track_color == "#3B82F6"),
    ("flash effect daalo", lambda i: "flash" in i.effects or i.flash_accents),
    # ---- size / platform ---------------------------------------------------------------------------------
    ("instagram ke liye", lambda i: i.aspect_ratio == "9:16"),
    ("youtube ke liye landscape", lambda i: i.aspect_ratio == "16:9"),
    ("square bana do", lambda i: i.aspect_ratio == "1:1"),
    ("1080p me export karo", lambda i: i.resolution == 1080),
    # ---- memory / undo -----------------------------------------------------------------------------------
    ("pichla wala dobara bana do", lambda i: i.title == "RONALDO" and i.target_duration == 15),
    ("pehle jaisa kar do", lambda i: i.title == "RONALDO" and i.target_duration == 15),
    ("same as before", lambda i: i.title == "RONALDO"),
    # ---- whole edits -------------------------------------------------------------------------------------
    ("mast sa edit kar do", lambda i: i.auto),
    ("isko reel bana do", lambda i: i.aspect_ratio == "9:16"),
    ("vlog bana do", lambda i: "vlog" in " ".join(i.recognized).lower() or i.genres),
    ("trip ka yaadgaar video", lambda i: bool(i.recognized)),
    # ---- found while using the app as a noob on trip footage (2026-10-08) ---------------------------------
    ("start me Goa Trip likh do", lambda i: i.title == "Goa Trip"),
    ("last me The End likh do", lambda i: i.end_text == "The End"),
    ("end me slow motion aur last me The End likh do", lambda i: i.slow_end and i.end_text == "The End"),
    ("zoom thoda kam karo", lambda i: "zoom" not in i.effects and "drift" in i.effects),
    ("music thoda kam karo", lambda i: i.music and i.music_volume is not None and i.music_volume < 0.5),  # same song, lower
    ("gaana thoda shaant wala lagao", lambda i: i.music and i.music_mood == "calm"),
    ("thoda smooth karo", lambda i: i.transition == "crossfade"),
    ("pehla clip hata do", lambda i: i.drop_clips == [1]),
    ("last wala video nikal do", lambda i: i.drop_clips == [-1]),
    ("color wapas lao", lambda i: i.color_preset is None and not i.color_pass and "mono" not in i.effects),
    # ---- follow-ups keep the edit ------------------------------------------------------------------------
    ("ab black and white kar do", lambda i: i.color_preset == "bw" and i.title == "RONALDO" and i.music),
    ("captions bhi daal do", lambda i: i.captions and i.title == "RONALDO" and i.target_duration == 15),
    ("thoda slow karo", lambda i: i.music and i.target_duration == 15),
]


@pytest.mark.parametrize("msg, check", CASES, ids=[c[0] for c in CASES])
def test_the_agent_understands_what_the_user_means(msg, check):
    it = understood(msg)
    assert it.recognized, f"nothing understood: {msg!r}"
    assert check(it), f"{msg!r} → {it.recognized}"
