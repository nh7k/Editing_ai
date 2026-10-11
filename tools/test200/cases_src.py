"""Writes tools/test200/cases.yaml — the PRE-REGISTERED cases (expectations written before any run) and freezes it
(cases.lock.json). Phrasings are written the way users talk (no skill ids), rotating style: English, Hinglish with
spelling variants, Devanagari, typos, slang, run-on voice style, magnitude words and negations.

python tools/test200/cases_src.py           (refuses to overwrite a frozen file; --refreeze after logging the change)
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
A = lambda kind, **kw: {"kind": kind, **kw}  # noqa: E731
OKW = ["APPLIED", "NOT_NEEDED", "COULD_NOT"]  # weak-oracle skills (said honestly is acceptable)
TWO = ["dark", "bright"]  # two clips → a cut between them at 6.0 s

# ---- S: one case per skill: (skill, phrase, fixture, extra fixtures, accepted assertions, accepted states) -------
S = [
    ("add_music", "isme koi gaana laga do background me", "speech_pauses", [], [A("music_added"), A("sound_changed")], None),
    ("aspect_16_9", "make it landscape 16:9 for youtube", "portrait", [], [A("aspect", ratio=16 / 9)], None),
    ("aspect_1_1", "square bana do insta post ke liye", "multishot", [], [A("aspect", ratio=1.0)], None),
    ("aspect_4_5", "4:5 portrait size chahiye", "multishot", [], [A("aspect", ratio=0.8)], None),
    ("aspect_9_16", "reel ke liye vertical kar do 9:16", "multishot", [], [A("aspect", ratio=9 / 16)], None),
    ("audio_fade", "end me awaaz dheere dheere band ho", "speech_music", [], [A("quieter", at=-0.3, min=3)], None),
    ("auto_captions", "jo bol raha hu uske subtitles daal do", "speech_pauses", [], [A("captions")], None),
    ("auto_enhance", "video bahut dull hai, isko thik se enhance kar do", "dark", [],
     [A("brighter"), A("more_contrast"), A("changed")], None),
    ("auto_reframe", "vertical me reframe karo aur subject ko follow karo", "multishot", [],
     [A("aspect", ratio=9 / 16)], None),
    ("beat_sync", "gaane ki beat pe cut karo", "music_beats", [], [A("changed"), A("shorter")], OKW),
    ("blur", "poori video thodi blur kar do", "speech_pauses", [], [A("blurrier")], None),
    ("blur_background_fill", "side ki kaali patti ki jagah blur background bhar do", "portrait", [], [A("changed")], OKW),
    ("blur_box_censor", "beech me ek blur box laga do jaise face chupana ho", "speech_pauses", [], [A("changed")], None),
    ("brighten_to_white", "screen ekdum safed sa white kar do", "speech_pauses", [], [A("brighter", k=4)], None),
    ("brightness", "थोड़ा ब्राइट करो", "dark", [], [A("brighter")], None),
    ("caption_style", None, "speech_pauses", [], [A("changed", at=1.5)], None),  # 2 turns, see below
    ("cinematic_look", "filmy cinematic look de do", "speech_pauses", [], [A("changed")], None),
    ("color_pop", "sirf laal rang rakho baaki sab black and white", "multishot", [], [A("less_sat")], None),
    ("contrast", "contrast bdhao thoda", "speech_pauses", [], [A("more_contrast")], None),
    ("cool", "thoda thanda neela tone do", "speech_pauses", [], [A("cooler")], None),
    ("countdown_timer", "shuru me 3 2 1 countdown dikhao", "speech_pauses", [], [A("changed", at=1.0)], None),
    ("crop", "video ko crop karo beech wala hissa rakho", "speech_pauses", [], [A("zoomed"), A("changed")], None),
    ("crossfade", "dono clips ke beech smooth crossfade daalo", "dark", ["bright"], [A("blend_at_cut")], None),
    ("delete_segment", "2 se 4 second wala part nikal do", "speech_pauses", [], [A("shorter", min=1.5)], None),
    ("denoise", "background ka shor kam karo awaaz saaf karo", "noisy_speech", [], [A("sound_changed")], None),
    ("duck_music", "jab main bolu tab music dheema ho jaye", "speech_music", [], [A("ducked"), A("sound_changed")], OKW),
    ("echo_reverb", "awaaz me echo daal do jaise hall me", "speech_pauses", [], [A("sound_changed")], None),
    ("export_preset", "youtube ke liye export settings laga do", "speech_pauses", [], [A("decodes")], None),
    ("extract_audio", "is video ka mp3 nikal ke do", "speech_pauses", [], [A("decodes")], None),
    ("extract_highlights", "best moments ki highlights bana do", "speech_pauses", [], [A("shorter")], OKW),
    ("fade_black", "end me fade to black kar do", "speech_pauses", [], [A("fade_end")], None),
    ("fade_white", "fade to white karo end pe", "speech_pauses", [], [A("brighter", at=-0.1, k=4)], None),
    ("film_grain", "purani film jaisa grain daalo", "speech_pauses", [], [A("changed")], None),
    ("fit_to_duration", "isko exactly 10 second ka kar do", "speech_pauses", [], [A("duration", target=10, tol=0.6)], None),
    ("flash", "beech me ek white flash daalo", "speech_pauses", [], [A("changed"), A("brighter")], OKW),
    ("freeze_frame", "3 second pe frame freeze kar do 2 second ke liye", "speech_pauses", [], [A("longer", min=1.0)], None),
    ("glitch", "glitch effect lagao", "speech_pauses", [], [A("changed")], None),
    ("glitch_transition", "clips ke beech glitch wala transition", "dark", ["bright"], [A("blend_at_cut")], None),
    ("grayscale", "blak and wite kro", "speech_pauses", [], [A("grey")], None),
    ("hook_first", "sabse accha part shuru me rakho", "speech_pauses", [], [A("starts_differently")], OKW),
    ("insert_broll", "beech me doosri clip b-roll ki tarah daalo", "speech_pauses", ["multishot"],
     [A("changed", at=4.0)], OKW),
    ("intro_outro", "shuru me ek intro card lagao", "speech_pauses", [], [A("longer"), A("changed", at=0.5)], None),
    ("iris_circle", "circle wala transition do clips ke beech", "dark", ["bright"], [A("blend_at_cut")], None),
    ("j_cut", "agli clip ki awaaz pehle shuru ho j cut", "dark", ["bright"], [A("sound_changed", at=5.5)], OKW),
    ("jump_cut_tighten", "jump cuts tight karo saare gap hata do", "speech_pauses", [], [A("shorter")], None),
    ("karaoke_captions", "karaoke style captions jo word by word highlight ho", "speech_pauses", [], [A("captions")], None),
    ("ken_burns", "photo jaisa slow zoom ken burns effect", "speech_pauses", [], [A("zoomed", at=-1.0), A("changed")], None),
    ("l_cut", "pichli clip ki awaaz thodi der aur chale l cut", "dark", ["bright"], [A("sound_changed", at=6.3)], OKW),
    ("letterbox", "upar neeche kaali patti cinematic bars", "speech_pauses", [], [A("darker"), A("changed")], None),
    ("light_leak", "light leak wala warm glow effect", "speech_pauses", [], [A("changed")], None),
    ("loop_boomerang", "boomerang bana do aage peeche", "short1s", [], [A("longer")], None),
    ("lower_third", "neeche naam ki patti lagao 'Anmol'", "speech_pauses", [], [A("text", text="anmol"), A("changed")], None),
    ("merge_clips", "saari clips ek saath jod do", "dark", ["bright"], [A("decodes")], None),
    ("mirror_effect", "mirror effect do", "speech_pauses", [], [A("changed")], None),
    ("montage_builder", "fast montage bana do chhote chhote shots ka", "speech_pauses", [], [A("shorter"), A("changed")], OKW),
    ("mute", "video ki awaaz band kar do", "speech_pauses", [], [A("muted")], None),
    ("normalize_loudness", "awaaz ka level normal karo sab barabar", "speech_pauses", [], [A("sound_changed")], OKW),
    ("pan", "camera left se right pan karo", "speech_pauses", [], [A("changed")], None),
    ("picture_in_picture", "doosri clip chhoti corner me dikhao", "speech_pauses", ["multishot"], [A("changed")], None),
    ("pixelate_censor", "beech wala hissa pixelate kar do", "speech_pauses", [], [A("changed")], None),
    ("progress_bar", "neeche progress bar dikhao", "speech_pauses", [], [A("changed")], None),
    ("punch_in", "beat pe punch in zoom karo", "music_beats", [], [A("changed"), A("zoomed")], OKW),
    ("remove_fillers", "um aa jaise filler words hata do", "speech_pauses", [], [A("shorter", min=0.1)], OKW),
    ("remove_silence", "silence hata do", "speech_pauses", [], [A("silence_removed"), A("shorter", min=1.0)], None),
    ("reorder_clips", "doosri clip pehle chalao", "dark", ["bright"], [A("starts_differently")], None),
    ("replace_audio", "original awaaz hata ke sirf music rakho", "speech_pauses", [], [A("sound_changed")], None),
    ("restore_normal", None, "speech_pauses", [], [A("unchanged")], None),  # 2 turns, see below
    ("reverse", "video ulta chala do reverse", "speech_pauses", [], [A("reversed")], None),
    ("rgb_split", "rgb split chromatic effect", "speech_pauses", [], [A("changed")], None),
    ("rotate_flip", "video ko 90 degree ghuma do", "speech_pauses", [], [A("aspect", ratio=9 / 16), A("changed")], None),
    ("saturation", "rang zyada gehre karo saturation badhao", "speech_pauses", [], [A("more_sat")], None),
    ("scene_detect", "scenes detect karke alag alag shots bana do", "multishot", [], [A("decodes")], OKW),
    ("sepia", "sepia tone purana sa", "speech_pauses", [], [A("sepia")], None),
    ("sfx_whoosh", "cut pe whoosh sound daalo", "dark", ["bright"], [A("sound_changed", at=5.9)], OKW),
    ("shake", "camera shake effect lagao", "speech_pauses", [], [A("changed")], None),
    ("shape_highlight", "beech me ek circle bana ke highlight karo", "speech_pauses", [], [A("changed")], None),
    ("sharpen", "video thodi sharp karo", "speech_pauses", [], [A("sharper")], None),
    ("slide", "slide transition daalo clips ke beech", "dark", ["bright"], [A("blend_at_cut")], None),
    ("slow_motion", "slow motion kar do", "speech_pauses", [], [A("longer", min=2.0)], None),
    ("speed_ramp", "speed ramp karo beech me tez phir normal", "speech_pauses", [], [A("shorter"), A("changed")], OKW),
    ("speed_up", "video 2x fast kar do", "speech_pauses", [], [A("shorter", min=5.0)], None),
    ("split", "5 second pe cut laga do", "speech_pauses", [], [A("same_length")], None),
    ("split_screen", "dono clips side by side split screen", "speech_pauses", ["multishot"], [A("changed")], None),
    ("srt_export", "subtitles ki srt file bana do", "speech_pauses", [], [A("decodes")], None),
    ("stabilize", "hilti hui video stable karo", "shaky", [], [A("changed")], None),
    ("sticker_lottie", "ek dil wala sticker lagao", "speech_pauses", [], [A("changed")], None),
    ("teal_orange", "teal orange look do hollywood jaisa", "speech_pauses", [], [A("changed")], None),
    ("text_glow_neon", "neon glow wala text 'PARTY' likho", "speech_pauses", [], [A("text", text="party")], None),
    ("text_overlay", "screen pe 'Hello Goa' likh do", "speech_pauses", [], [A("text", text="hello goa")], None),
    ("text_pop_in", "'WOW' text pop karke aaye", "speech_pauses", [], [A("text", text="wow")], None),
    ("text_slide", "'Day 1' text slide hoke aaye", "speech_pauses", [], [A("text", text="day 1")], None),
    ("text_typewriter", "typewriter jaisa text 'Loading' likho", "speech_pauses", [], [A("text", text="loading")], None),
    ("thumbnail", "is video ka thumbnail bana do", "speech_pauses", [], [A("decodes")], None),
    ("tilt", "video thoda tircha kar do", "speech_pauses", [], [A("changed")], None),
    ("title_card", "shuru me title card 'My Trip' daalo", "speech_pauses", [], [A("longer"), A("text", text="my trip")], None),
    ("trim", "pehle 8 second hi rakho baaki kaat do", "speech_pauses", [], [A("duration", target=8, tol=0.5)], None),
    ("vhs_retro", "vhs retro look do 90s wala", "speech_pauses", [], [A("changed")], None),
    ("vignette", "halka vignette lagao", "speech_pauses", [], [A("vignette")], None),
    ("vintage_faded", "vintage faded look", "speech_pauses", [], [A("changed")], None),
    ("voice_clarity", "meri awaaz thodi clear aur saaf karo", "speech_pauses", [], [A("sound_changed")], OKW),
    ("volume", "awaaz bahut zyada badha do", "speech_pauses", [], [A("louder")], None),
    ("warm", "thoda warm color karo", "speech_pauses", [], [A("warmer")], None),
    ("watermark_logo", "corner me mera logo watermark lagao", "speech_pauses", [], [A("changed")], OKW),
    ("whip_pan", "whip pan transition daalo", "dark", ["bright"], [A("blend_at_cut")], None),
    ("white_screen_card", "3 second pe 1 second ki safed screen daalo", "speech_pauses", [], [A("longer", min=0.7)], None),
    ("wipe", "wipe transition clips ke beech", "dark", ["bright"], [A("blend_at_cut")], None),
    ("zoom_in", "thoda zoom in karo", "speech_pauses", [], [A("zoomed", at=-0.5)], None),
    ("zoom_out", "zoom out effect do", "speech_pauses", [], [A("zoomed", at=0.3), A("changed", at=0.3)], None),
    ("zoom_transition", "zoom wala transition clips ke beech", "dark", ["bright"], [A("blend_at_cut")], None),
]
TWO_TURN = {
    "caption_style": [{"say": "captions laga do"}, {"say": "captions ka colour peela kar do"}],
    "restore_normal": [{"say": "black and white kar do"}, {"say": "normal kar do jaisa pehle tha"}],
}
FIRST_MESSAGE = {"warm", "grayscale", "auto_captions", "remove_silence", "aspect_9_16", "zoom_in", "mute",
                 "fade_black", "slow_motion", "vignette"}  # also sent as the FIRST message (no base version)
WAVE1_S = {"warm", "grayscale", "auto_captions", "remove_silence", "aspect_9_16", "zoom_in", "mute", "fade_black",
           "vignette", "trim", "crossfade", "text_overlay", "restore_normal", "add_music", "reverse", "blur",
           "speed_up", "brightness"}

REEL = ("Is video ko 15 second ka 9:16 reel bana do. Silence hata do, pehle 3 second me sabse achha part rakho, thoda "
        "zoom in lagao, captions lagao, warm filmy color do, halka vignette lagao, calm music lagao jo meri awaaz ke "
        "neeche dheema ho jaye, aur end me fade to black kar do.")
REEL_EXPECT = [
    {"instr": "15 sec", "any": [A("duration", target=15, tol=1.5)]},
    {"instr": "9:16", "any": [A("aspect", ratio=9 / 16)]},
    {"instr": "silence", "any": [A("silence_removed"), A("shorter", min=1.0)], "states": ["APPLIED", "NOT_NEEDED"]},
    {"instr": "captions", "any": [A("captions")]},
    {"instr": "warm", "any": [A("warmer")]},
    {"instr": "vignette", "any": [A("vignette")]},
    {"instr": "music", "any": [A("music_added"), A("sound_changed")]},
    {"instr": "fade end", "any": [A("fade_end")]},
]


def s_cases() -> list[dict]:
    out = []
    for n, (sid, phrase, fx, extra, asserts, states) in enumerate(S, 1):
        turns = TWO_TURN.get(sid) or [{"say": phrase}]
        exp = [{"instr": sid, "any": asserts, "states": states or ["APPLIED"]}]
        first = sid in FIRST_MESSAGE  # what a brand-new user gets: the phrase is the FIRST message (director path)
        out.append({"id": f"S{n:03d}", "cat": "S", "skill": sid, "fixture": fx, "extra_fixtures": extra,
                    "base": "none" if first else "chip", "first_message": first, "turns": turns, "expect": exp,
                    "wave": 1 if sid in WAVE1_S else (2 if n % 2 else 3),
                    "compare": "source" if first else ("base" if sid in TWO_TURN else "prev")})
    return out


def m_cases() -> list[dict]:
    ms = [
        ("speech_pauses", REEL, REEL_EXPECT), ("speech_music", REEL, REEL_EXPECT), ("portrait", REEL, REEL_EXPECT),
        ("speech_pauses", "warm karo, vignette lagao aur end me fade to black",
         [{"instr": "warm", "any": [A("warmer")]}, {"instr": "vignette", "any": [A("vignette")]},
          {"instr": "fade", "any": [A("fade_end")]}]),
        ("speech_pauses", "captions lagao, silence hatao aur thoda zoom in karo",
         [{"instr": "captions", "any": [A("captions")]}, {"instr": "silence", "any": [A("shorter", min=1.0)]},
          {"instr": "zoom", "any": [A("zoomed", at=-0.5), A("changed")]}]),
        ("multishot", "square bana do, black and white karo, aur awaaz band kar do",
         [{"instr": "square", "any": [A("aspect", ratio=1.0)]}, {"instr": "bw", "any": [A("grey")]},
          {"instr": "mute", "any": [A("muted")]}]),
        ("speech_pauses", "warm karo, vignette lagao aur mere chehre ko jawan dikhao",
         [{"instr": "warm", "any": [A("warmer")]}, {"instr": "vignette", "any": [A("vignette")]},
          {"instr": "younger face (unsupported)", "any": [], "states": ["NOT_UNDERSTOOD", "COULD_NOT", "NOT_NEEDED"]}]),
        ("speech_pauses", "4k upscale karo, sepia do aur 10 second ka bana do",
         [{"instr": "4k (unsupported)", "any": [], "states": ["NOT_UNDERSTOOD", "COULD_NOT", "NOT_NEEDED"]},
          {"instr": "sepia", "any": [A("sepia")]}, {"instr": "10 s", "any": [A("duration", target=10, tol=0.8)]}]),
        ("speech_pauses", "slow motion karo, contrast badhao, 'GOA' likho, face swap karo aur music lagao",
         [{"instr": "slow", "any": [A("longer")]}, {"instr": "contrast", "any": [A("more_contrast")]},
          {"instr": "text", "any": [A("text", text="goa")]},
          {"instr": "face swap (unsupported)", "any": [], "states": ["NOT_UNDERSTOOD", "COULD_NOT", "NOT_NEEDED"]},
          {"instr": "music", "any": [A("music_added"), A("sound_changed")]}]),
        ("dark", "bright karo aur saturation badhao aur sharpen karo",
         [{"instr": "bright", "any": [A("brighter")]}, {"instr": "sat", "any": [A("more_sat")]},
          {"instr": "sharp", "any": [A("sharper")]}]),
        ("speech_pauses", "9:16 karo, captions lagao, warm karo, music lagao",
         [{"instr": "9:16", "any": [A("aspect", ratio=9 / 16)]}, {"instr": "captions", "any": [A("captions")]},
          {"instr": "warm", "any": [A("warmer")]}, {"instr": "music", "any": [A("music_added"), A("sound_changed")]}]),
        ("speech_pauses", "मुझे 9:16 चाहिए, कैप्शन लगाओ और वीडियो थोड़ा ब्राइट करो",
         [{"instr": "9:16", "any": [A("aspect", ratio=9 / 16)]}, {"instr": "captions", "any": [A("captions")]},
          {"instr": "bright", "any": [A("brighter")]}]),
        ("speech_pauses", "bhai isko ekdum black n white kr de aur thoda blur bhi aur awaz kam",
         [{"instr": "bw", "any": [A("grey")]}, {"instr": "blur", "any": [A("blurrier")]},
          {"instr": "quieter", "any": [A("quieter")]}]),
        ("speech_pauses", "trim to 8 seconds, add a vignette, make it cooler",
         [{"instr": "8 s", "any": [A("duration", target=8, tol=0.6)]}, {"instr": "vignette", "any": [A("vignette")]},
          {"instr": "cool", "any": [A("cooler")]}]),
        ("speech_pauses", "zoom in karo lekin black and white mat karna, aur warm karo",
         [{"instr": "zoom", "any": [A("zoomed", at=-0.5), A("changed")]}, {"instr": "warm", "any": [A("warmer")]},
          {"instr": "NOT bw", "any": [A("more_sat", k=-1)], "states": ["APPLIED"]}]),
        ("dark", "pehle bright karo, phir contrast badhao, phir end me fade karo",
         [{"instr": "bright", "any": [A("brighter")]}, {"instr": "contrast", "any": [A("more_contrast")]},
          {"instr": "fade", "any": [A("fade_end")]}]),
        ("speech_pauses", "subtitles daalo, sepia karo, 'Hello' likho, aur reverse mat karna",
         [{"instr": "captions", "any": [A("captions")]}, {"instr": "sepia", "any": [A("sepia")]},
          {"instr": "text", "any": [A("text", text="hello")]}]),
        ("music_beats", "beat pe cut karo, fast karo aur glitch lagao",
         [{"instr": "fast", "any": [A("shorter")]}, {"instr": "glitch", "any": [A("changed")]}]),
        ("speech_pauses", "mute karo, gaana lagao, aur 12 second ka bana do",
         [{"instr": "mute", "any": [A("sound_changed")]}, {"instr": "music", "any": [A("music_added")]},
          {"instr": "12 s", "any": [A("duration", target=12, tol=0.8)]}]),
        ("speech_pauses", "make it vertical, add captions, AI generate a new background video",
         [{"instr": "vertical", "any": [A("aspect", ratio=9 / 16)]}, {"instr": "captions", "any": [A("captions")]},
          {"instr": "AI video gen (unsupported)", "any": [], "states": ["NOT_UNDERSTOOD", "COULD_NOT", "NOT_NEEDED"]}]),
        ("speech_pauses", "vignette halka sa, warm thoda sa, aur zoom bahut zyada",
         [{"instr": "vignette", "any": [A("vignette")]}, {"instr": "warm", "any": [A("warmer")]},
          {"instr": "zoom", "any": [A("zoomed", at=-0.5, min=1.1), A("changed")]}]),
        ("noisy_speech", "awaaz saaf karo, captions lagao aur silence hatao",
         [{"instr": "clean", "any": [A("sound_changed")]}, {"instr": "captions", "any": [A("captions")]},
          {"instr": "silence", "any": [A("shorter", min=1.0)]}]),
        ("speech_pauses", "warm karo aur vignette lagao aur fade in shuru me aur fade out end me",
         [{"instr": "warm", "any": [A("warmer")]}, {"instr": "vignette", "any": [A("vignette")]},
          {"instr": "fade in", "any": [A("fade_start")]}, {"instr": "fade out", "any": [A("fade_end")]}]),
        ("multishot", "4:5 karo, cool tone do, aur 'SALE' likho",
         [{"instr": "4:5", "any": [A("aspect", ratio=0.8)]}, {"instr": "cool", "any": [A("cooler")]},
          {"instr": "text", "any": [A("text", text="sale")]}]),
        ("speech_pauses", "isko 20 second ka kar do aur 5 second ka bhi",
         [{"instr": "contradiction 20 vs 5", "any": [A("duration", target=20, tol=1.0), A("duration", target=5, tol=0.8)],
           "states": ["APPLIED", "NOT_UNDERSTOOD", "COULD_NOT"]}]),
    ]
    return [{"id": f"M{n:03d}", "cat": "M", "fixture": fx, "base": "chip", "turns": [{"say": say}], "expect": exp,
             "wave": 1 if n in (1, 4, 7, 12, 25) else (2 if n % 2 else 3), "compare": "prev"}
            for n, (fx, say, exp) in enumerate(ms, 1)]


def t_cases() -> list[dict]:
    W = [{"instr": "warm", "any": [A("warmer")]}]
    ts = [
        ("speech_pauses", [{"say": "thoda warm karo"}, {"say": "aur thoda"}], W, "prev", []),
        ("speech_pauses", [{"say": "bahut warm karo"}, {"say": "zyada ho gaya thoda kam karo"}],
         [{"instr": "less warm", "any": [A("cooler", k=0.5)]}], "prev", []),
        ("speech_pauses", [{"say": "zoom in karo"}, {"say": "isko hata do"}],
         [{"instr": "undo zoom", "any": [A("unchanged")]}], "base", []),
        ("speech_pauses", [{"say": "black and white kar do"}, {"say": "pehle jaisa kar do"}],
         [{"instr": "restore", "any": [A("unchanged")]}], "base", []),
        ("speech_pauses", [{"say": "sepia karo"}, {"undo": True}], [{"instr": "undo", "any": [A("unchanged")]}],
         "base", []),
        ("speech_pauses", [{"say": "sepia karo"}, {"undo": True}, {"redo": True}],
         [{"instr": "redo", "any": [A("sepia")]}], "base", []),
        ("speech_pauses", [{"say": "violet authority look lagao", "style": "violet_authority"},
                           {"say": "violet authority hata do"}],
         [{"instr": "no violet", "any": [A("no_overlays")]}], "prev", [A("plan_style", style=None)]),
        ("speech_pauses", [{"say": "reel bana do", "variations": 3}, {"say": "captions laga do"}],
         [{"instr": "captions", "any": [A("captions")]}], "prev", []),
        ("speech_pauses", [{"say": "reel bana do", "variations": 3}, {"choose": 2}, {"say": "warm karo"}],
         [{"instr": "warm on chosen look", "any": [A("warmer")]}], "prev", []),
        ("speech_pauses", [{"say": "grain daalo"}, {"say": "naya edit, 9:16 reel bana do warm color me"}],
         [{"instr": "9:16", "any": [A("aspect", ratio=9 / 16)]}], "prev", []),
        ("speech_pauses", [{"say": "warm karo"}, {"say": "vignette lagao"}, {"say": "captions lagao"},
                           {"say": "thoda zoom"}, {"say": "contrast badhao"}, {"say": "sharpen karo"}],
         [{"instr": "6 edits stack", "any": [A("warmer")]}], "base", [A("same_length", tol=0.3)]),
        ("speech_pauses", [{"say": "blur karo"}, {"say": "dobara"}],
         [{"instr": "again", "any": [A("blurrier")]}], "prev", []),
        ("speech_pauses", [{"say": "2 sec pe zoom karo", "at": 2.0}, {"say": "wahi yahan bhi", "at": 8.0}],
         [{"instr": "same here", "any": [A("changed", at=8.6)]}], "prev", []),
        ("speech_pauses", [{"say": "captions laga do"}, {"say": "captions hata do"}],
         [{"instr": "no captions", "any": [A("unchanged", at=1.5)]}], "base", []),
        ("speech_pauses", [{"say": "music lagao"}, {"say": "music ki awaaz kam karo"}],
         [{"instr": "music lower", "any": [A("quieter", at=1.0, min=1.0), A("sound_changed")]}], "prev", []),
        ("speech_pauses", [{"say": "cool karo"}, {"say": "nahi warm karo"}],
         [{"instr": "warm wins", "any": [A("warmer")]}], "prev", []),
        ("speech_pauses", [{"say": "speed 2x"}, {"say": "slow karo thoda"}],
         [{"instr": "slower", "any": [A("longer")]}], "prev", []),
        ("speech_pauses", [{"say": "warm karo"}, {"say": "warm karo"}, {"say": "warm karo"}, {"say": "warm karo"},
                           {"say": "warm karo"}, {"say": "warm karo"}, {"say": "warm karo"}, {"say": "warm karo"},
                           {"say": "warm karo"}, {"say": "warm karo"}],
         [{"instr": "10 edits, no shrink", "any": [A("same_length", tol=0.3)]}], "base", [A("decodes")]),
        ("speech_pauses", [{"say": "purple look lagao", "style": "violet_authority"},
                           {"say": "purple video ko normal kar do"}],
         [{"instr": "normal", "any": [A("no_overlays")]}], "prev", [A("plan_style", style=None)]),
        ("speech_pauses", [{"say": "zoom in karo"}, {"say": "aur zyada"}],
         [{"instr": "more zoom", "any": [A("zoomed", at=-0.5, min=1.0), A("changed", at=-0.5)]}], "prev", []),
    ]
    return [{"id": f"T{n:03d}", "cat": "T", "fixture": fx, "base": "chip", "turns": turns, "expect": exp,
             "compare": cmp, "must": must, "wave": 1 if n in (1, 4, 7, 9, 19) else (2 if n % 2 else 3)}
            for n, (fx, turns, exp, cmp, must) in enumerate(ts, 1)]


def x_cases() -> list[dict]:
    xs = [
        ([{"say": "yaha zoom karo", "at": 3.0}], [{"instr": "zoom at 3", "any": [A("changed", at=3.8)]}],
         [A("unchanged", at=12.0)]),
        ([{"say": "black and white kar do"}, {"say": "yaha normal kar do", "at": 5.0}],
         [{"instr": "colour back at 5", "any": [A("more_sat", at=5.5)]}], []),
        ([{"say": "yaha WOW likh do", "at": 4.0}], [{"instr": "text at 4", "any": [A("text", text="wow")]}], []),
        ([{"say": "yahan blur karo", "playhead": 6.0}], [{"instr": "blur at playhead", "any": [A("blurrier", at=6.5)]}],
         []),
        ([{"say": "is jagah flash daalo", "at": 2.0}], [{"instr": "flash", "any": [A("changed", at=2.1)]}], []),
        ([{"say": "ye part hata do", "at": 4.0}], [{"instr": "cut", "any": [A("shorter", min=0.5)]}], []),
        ([{"say": "yaha screen white kar do nomal jasia tha", "at": 4.3}],
         [{"instr": "white/restore", "any": [A("changed", at=4.4), A("brighter", at=4.4)],
           "states": ["APPLIED", "NOT_UNDERSTOOD"]}], []),
        ([{"say": "yaha slow motion", "at": 3.0}], [{"instr": "slow", "any": [A("longer")]}], []),
        ([{"say": "sepia karo"}, {"say": "yaha se hata do", "at": 6.0}],
         [{"instr": "sepia off at 6", "any": [A("more_sat", at=6.5)]}], []),
        ([{"say": "yaha 1 sec ki white screen daalo", "at": 5.0}], [{"instr": "card", "any": [A("longer", min=0.7)]}], []),
        ([{"say": "zoom karo yaha", "playhead": 2.0}], [{"instr": "zoom", "any": [A("changed", at=2.6)]}], []),
        ([{"say": "yaha rose", "at": 1.0}], [{"instr": "sticker", "any": [A("changed", at=1.5)]},
                                             ], []),
    ]
    return [{"id": f"X{n:03d}", "cat": "X", "fixture": "speech_pauses", "base": "chip", "turns": t, "expect": e,
             "must": m, "wave": 1 if n in (1, 2, 6) else (2 if n % 2 else 3), "compare": "prev"}
            for n, (t, e, m) in enumerate(xs, 1)]


def a_cases() -> list[dict]:
    NU = ["NOT_UNDERSTOOD", "APPLIED", "COULD_NOT"]
    as_ = [
        ("viral bana do", [{"instr": "vague", "any": [A("changed")], "states": NU, "need_chips": True}], []),
        ("5 sec ka bhi aur 60 sec ka bhi bana do",
         [{"instr": "contradiction", "any": [A("duration", target=5, tol=0.8)], "states": NU}], []),
        ("isme se ek nayi AI video generate karo",
         [{"instr": "unsupported", "any": [], "states": ["NOT_UNDERSTOOD", "COULD_NOT"]}], [A("no_new_version")]),
        ("4k upscale kar do", [{"instr": "unsupported", "any": [], "states": ["NOT_UNDERSTOOD", "COULD_NOT"]}],
         [A("no_new_version")]),
        ("", [{"instr": "empty", "any": [], "states": ["NOT_UNDERSTOOD", "COULD_NOT", "NO_EDIT"], "need_chips": False}],
         [A("no_new_version")]),
        ("🔥🔥😂", [{"instr": "emoji", "any": [], "states": ["NO_EDIT", "NOT_UNDERSTOOD"], "need_chips": False}],
         [A("no_new_version")]),
        ("warm karo " + "bahut sundar video hai mera " * 180,
         [{"instr": "5000 chars", "any": [A("warmer")], "states": ["APPLIED", "NOT_UNDERSTOOD"]}], []),
        ("aaj mausam kaisa hai?", [{"instr": "off-topic", "any": [], "states": ["NO_EDIT", "NOT_UNDERSTOOD"],
                                    "need_chips": False}], [A("no_new_version")]),
        ("bakwas app hai tum log kuch nahi kar sakte",
         [{"instr": "rude", "any": [], "states": ["NO_EDIT", "NOT_UNDERSTOOD"], "need_chips": False}],
         [A("no_new_version")]),
        ("asdf qwerty zxcv", [{"instr": "gibberish", "any": [], "states": ["NOT_UNDERSTOOD"]}], [A("no_new_version")]),
        ("hello bhai", [{"instr": "greeting", "any": [], "states": ["NO_EDIT"], "need_chips": False}],
         [A("no_new_version")]),
        ("meri height badha do", [{"instr": "impossible", "any": [], "states": ["NOT_UNDERSTOOD", "COULD_NOT"]}],
         [A("no_new_version")]),
    ]
    return [{"id": f"A{n:03d}", "cat": "A", "fixture": "speech_pauses", "base": "chip", "turns": [{"say": s}],
             "expect": e, "must": m, "wave": 1 if n in (2, 3, 10, 11) else (2 if n % 2 else 3), "compare": "prev",
             "decodes": False}
            for n, (s, e, m) in enumerate(as_, 1)]


def u_cases() -> list[dict]:
    us = ["every one-tap chip (Auto edit, Arrange clips, Captions) runs and shows an answer",
          "3 variations then Use this on card 1: plan, timeline and the next edit follow card 1",
          "3 variations then Use this on card 2: plan, timeline and the next edit follow card 2",
          "3 variations then Use this on card 3: plan, timeline and the next edit follow card 3",
          "Effects panel Apply now (vignette) changes the video",
          "Effects panel Add to prompt (a transition) is understood as that transition",
          "Undo and redo buttons give back the exact versions",
          "Export downloads the current version",
          "Narrow phone width (375 px): a 422 choice shows chips; panels reachable",
          "A skill job's answer renders as readable text (not run-together)",
          "After Use this, the player does not show a stale cached video",
          "Overlays panel: Look hatao removes the gradient tracks"]
    return [{"id": f"U{n:03d}", "cat": "U", "fixture": "speech_pauses", "driver": "browser", "turns": [{"say": s}],
             "expect": [{"instr": s, "any": []}], "wave": 1 if n in (2, 9, 12) else (2 if n % 2 else 3)}
            for n, s in enumerate(us, 1)]


def r_cases() -> list[dict]:
    rs = [
        ("corrupt", [], {"upload_expect": [400, 415, 422]}),
        ("no_audio", [{"say": "warm karo"}], {"expect": [{"instr": "warm", "any": [A("warmer")]}]}),
        ("audio_only", [], {"upload_expect": [400, 415, 422, 201]}),
        ("vfr", [{"say": "warm karo"}], {"expect": [{"instr": "warm", "any": [A("warmer")]}]}),
        ("rotated", [{"say": "9:16 reel bana do"}], {"expect": [{"instr": "9:16", "any": [A("aspect", ratio=9 / 16)]}]}),
        ("k4", [{"say": "warm karo"}], {"expect": [{"instr": "warm", "any": [A("warmer")]}]}),
        ("fps60", [{"say": "slow motion karo"}], {"expect": [{"instr": "slow", "any": [A("longer")]}]}),
        ("short1s", [{"say": "zoom in karo"}], {"expect": [{"instr": "zoom", "any": [A("changed"), A("zoomed")]}]}),
        ("long5min", [{"say": "warm karo"}], {"expect": [{"instr": "warm", "any": [A("warmer")]}], "long": True}),
        ("speech_pauses", [{"say": "warm karo"}], {"expect": [{"instr": "warm", "any": [A("warmer")]}],
                                                   "extra_fixtures": ["speech_pauses"]}),
    ]
    out = []
    for n, (fx, turns, extra) in enumerate(rs, 1):
        c = {"id": f"R{n:03d}", "cat": "R", "fixture": fx, "base": "chip" if turns else "none", "turns": turns or
             [{"say": ""}], "expect": [], "wave": 1 if n in (1, 5) else 3, "compare": "prev"}
        c.update(extra)
        out.append(c)
    return out


def main() -> None:
    cases = s_cases() + m_cases() + t_cases() + x_cases() + a_cases() + u_cases() + r_cases()
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    path, lock = HERE / "cases.yaml", HERE / "cases.lock.json"
    if lock.exists() and "--refreeze" not in sys.argv:
        sys.exit("cases.yaml is frozen — log the change in docs/test200/ORACLE_CHANGES.md, then use --refreeze")
    text = yaml.safe_dump({"cases": cases}, allow_unicode=True, sort_keys=False, width=140)
    path.write_text(text, encoding="utf-8")
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    lock.write_text(json.dumps({"sha256": h, "cases": len(cases)}, indent=1), encoding="utf-8")
    by: dict[str, int] = {}
    for c in cases:
        by[c["cat"]] = by.get(c["cat"], 0) + 1
    print(len(cases), by, "wave1:", sum(c.get("wave") == 1 for c in cases), "sha", h[:12])


if __name__ == "__main__":
    main()
