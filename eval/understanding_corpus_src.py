"""Writes eval/understanding_corpus.yaml — the v2 corpus (docs/UNDERSTANDING_REVIEW.md, Phase 7).

Three parts, reported separately:
  handwritten   eval/intent_corpus.yaml (420, written earlier) + NEW below (relative, multi-instruction with
                unsupported parts, negation / magnitude, time words, non-edit turns, unsupported, Devanagari,
                voice-style run-ons). Every 4th of each group is held-out.
  generated     every skill's synonyms with machine noise (tools/variants.py misspellings + filler words) — tests
                spelling robustness only: the matcher has SEEN these phrases (never the headline number).

Item kinds and what is checked:
  single       expect: skill id (top-1 / top-3)
  multi        expect_all: skill ids that must be applied; unsupported: how many parts cannot be done
               (2026-10-11: four labels corrected from audio_fade to fade_black — "fade in / fade out" means the
               picture fade by the documented decision — and "sabke chehre blur" to the face blur skill)
  relative     context.recent_edits + expect skill + direction of a parameter (up / down / same / remove)
  non_edit     a greeting / question: no edit must start
  unsupported  no skill can do it: must answer with the closest skills, never apply anything
"""

from __future__ import annotations

import random
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MONO = {"marker_time": 4.3, "effects_present_at_time": [{"type": "grade", "label": "black and white", "start": 3.0, "end": 5.5}]}
ZOOM_RECENT = [{"id": "zoom_in", "params": {"amount": 0.15}, "time": {"mode": "between_times", "start": 2.0, "end": 4.0}}]
WARM_RECENT = [{"id": "warm", "params": {"amount": 0.5}, "time": None}]
SPEED_RECENT = [{"id": "speed_up", "params": {"factor": 1.5}, "time": None}]
VOL_RECENT = [{"id": "volume", "params": {"gain_db": 6.0, "what": "mix"}, "time": None}]
BLUR_RECENT = [{"id": "blur", "params": {"radius": 6}, "time": None}]
SAT_RECENT = [{"id": "saturation", "params": {"amount": 1.35}, "time": None}]

RELATIVE = [
    ("aur thoda", ZOOM_RECENT, "zoom_in", "amount", "up"), ("thoda aur zoom", ZOOM_RECENT, "zoom_in", "amount", "up"),
    ("kam karo", ZOOM_RECENT, "zoom_in", "amount", "down"), ("itna nahi, halka", ZOOM_RECENT, "zoom_in", "amount", "down"),
    ("bahut zyada ho gaya", WARM_RECENT, "warm", "amount", "down"), ("aur warm", WARM_RECENT, "warm", "amount", "up"),
    ("thoda kam garam", WARM_RECENT, "warm", "amount", "down"), ("aur tez", SPEED_RECENT, "speed_up", "factor", "up"),
    ("itna fast nahi", SPEED_RECENT, "speed_up", "factor", "down"), ("aur zor se", VOL_RECENT, "volume", "gain_db", "up"),
    ("awaaz thodi kam karo ab", VOL_RECENT, "volume", "gain_db", "down"), ("aur blur", BLUR_RECENT, "blur", "radius", "up"),
    ("blur kam", BLUR_RECENT, "blur", "radius", "down"), ("rang thoda aur", SAT_RECENT, "saturation", "amount", "up"),
    ("more", ZOOM_RECENT, "zoom_in", "amount", "up"), ("less please", WARM_RECENT, "warm", "amount", "down"),
    ("a bit more", SAT_RECENT, "saturation", "amount", "up"), ("aur jyada", BLUR_RECENT, "blur", "radius", "up"),
    ("थोड़ा और", ZOOM_RECENT, "zoom_in", "amount", "up"), ("थोड़ा कम", WARM_RECENT, "warm", "amount", "down"),
    ("isko hata do", ZOOM_RECENT, "zoom_in", "", "remove"), ("ye wala effect hatao", WARM_RECENT, "warm", "", "remove"),
    ("pichla wala hata do", BLUR_RECENT, "blur", "", "remove"), ("undo the last one", SAT_RECENT, "saturation", "", "remove"),
    ("dobara karo", ZOOM_RECENT, "zoom_in", "", "same"), ("wahi dobara", WARM_RECENT, "warm", "", "same"),
    ("same again", BLUR_RECENT, "blur", "", "same"), ("ek baar aur", SPEED_RECENT, "speed_up", "", "same"),
    ("full kar do", SAT_RECENT, "saturation", "amount", "up"), ("bilkul halka kar do", ZOOM_RECENT, "zoom_in", "amount", "down"),
    ("double karo", VOL_RECENT, "volume", "gain_db", "up"), ("aadha karo", BLUR_RECENT, "blur", "radius", "down"),
    ("zyada ho gaya thoda kam", SAT_RECENT, "saturation", "amount", "down"), ("aur thoda sa please", WARM_RECENT, "warm", "amount", "up"),
    ("kam kar de yaar", SPEED_RECENT, "speed_up", "factor", "down"), ("thoda zyada", VOL_RECENT, "volume", "gain_db", "up"),
    ("aur halka", BLUR_RECENT, "blur", "radius", "down"), ("increase it", ZOOM_RECENT, "zoom_in", "amount", "up"),
    ("reduce it", SAT_RECENT, "saturation", "amount", "down"), ("tone it down", WARM_RECENT, "warm", "amount", "down"),
]

# (prompt, skills that must be applied, number of parts nobody can do)
MULTI = [
    ("warm karo, captions lagao aur mere chehre ko jawan dikhao", ["warm", "auto_captions"], 1),
    ("zoom karo aur dragon wala AI video bana do", ["zoom_in"], 1),
    ("music lagao, black and white karo, 3d animation daalo, slow motion aur 4k upscale", ["add_music", "grayscale", "slow_motion"], 2),
    ("silence hatao, captions yellow, background hatao aur fade out", ["remove_silence", "caption_style", "fade_black"], 1),
    ("vertical banao, music lagao, mera voice change karo ladki jaisa", ["aspect_9_16", "add_music"], 1),
    ("glitch daalo, shake bhi, aur ek naya scene generate karo", ["glitch", "shake"], 1),
    ("30 sec ka karo, warm tone, captions, logo lagao aur ai voiceover", ["fit_to_duration", "warm", "auto_captions", "watermark_logo"], 1),
    ("crossfade lagao, contrast badhao, translate to tamil", ["crossfade", "contrast"], 1),
    ("speed 2x, music, aur face ko cartoon bana do", ["speed_up", "add_music"], 1),
    ("sepia, vignette, film grain aur meri height badha do", ["sepia", "vignette", "film_grain"], 1),
    ("zoom in, flash, whoosh sound, aur sky ko pink kar do", ["zoom_in", "flash", "sfx_whoosh"], 1),
    ("captions lagao aur noise hatao aur script likh do mere liye", ["auto_captions", "denoise"], 1),
    ("square karo, cool tone, blur karo aur object remove karo", ["aspect_1_1", "cool", "blur"], 1),
    ("fade in fade out, music, vhs look aur lip sync theek karo", ["fade_black", "add_music", "vhs_retro"], 1),
    ("black and white, slow motion, vignette", ["grayscale", "slow_motion", "vignette"], 0),
    ("vertical, captions, music, 15 sec", ["aspect_9_16", "auto_captions", "add_music", "fit_to_duration"], 0),
    ("trim 2 se 10 sec, warm karo, music lagao, fade out, logo", ["trim", "warm", "add_music", "fade_black", "watermark_logo"], 0),
    ("silence hatao, jump cuts, captions, music aur ducking", ["remove_silence", "jump_cut_tighten", "auto_captions", "add_music", "duck_music"], 0),
    ("zoom, shake, glitch, flash aur rgb split", ["zoom_in", "shake", "glitch", "flash", "rgb_split"], 0),
    ("cinematic look, letterbox, slow zoom in aur film grain", ["cinematic_look", "letterbox", "zoom_in", "film_grain"], 0),
    ("music lagao, captions daalo, warm karo, logo lagao, square banao aur 20 sec ka karo",
     ["add_music", "auto_captions", "warm", "watermark_logo", "aspect_1_1", "fit_to_duration"], 0),
    ("noise hatao, awaaz badhao, captions aur hindi me dubbing karo", ["denoise", "volume", "auto_captions"], 1),
    ("vintage look, vignette, slow motion, aur purane zamane ki awaaz bana do robot jaisi", ["vintage_faded", "vignette", "slow_motion"], 1),
    ("reel bana do vertical, flash har cut pe, music aur ek AI host jo bole", ["aspect_9_16", "flash", "add_music"], 1),
    ("crossfade, fade in, fade out aur sabke chehre blur karo automatically", ["crossfade", "fade_black", "blur_box_censor"], 0),
    ("trim 0 se 30, speed 1.5x, cool tone, music aur thumbnail bana do", ["trim", "speed_up", "cool", "add_music", "thumbnail"], 0),
    ("black and white, captions, aur video me mujhe udte hue dikhao", ["grayscale", "auto_captions"], 1),
    ("glitch, vhs, rgb split, aur isko nft bana do", ["glitch", "vhs_retro", "rgb_split"], 1),
    ("zoom out, shake, music aur crowd cheering ki awaaz daalo jo nahi hai", ["zoom_out", "shake", "add_music"], 1),
    ("silence hatao aur fillers hatao aur captions aur music aur 60 sec", ["remove_silence", "remove_fillers", "auto_captions", "add_music", "fit_to_duration"], 0),
]

NON_EDIT = ["hi", "hello bhai", "kaise ho", "thank you", "thanks yaar", "ye app kaise kaam karta hai", "kya kya kar sakte ho",
            "namaste", "good morning", "help", "mujhe samjhao export kaise karu", "ok", "accha", "👍", "😂😂",
            "tum kaun ho", "bas itna hi", "bye", "nice", "wow badhiya", "kya hua", "kitna time lagega",
            "मदद करो", "shukriya", "theek hai"]

UNSUPPORTED = ["meri height badha do", "isko 3d animation bana do", "naya video generate karo dragon ka", "face swap karo",
               "voice ko ladki jaisa kar do", "sky ko pink kar do", "is script ko likh do", "translate to japanese audio",
               "lip sync theek karo", "background me paris daal do", "object remove karo jo peeche hai",
               "mere dost ko video se hata do", "anime style bana do", "deepfake bana do", "8k me upscale karo",
               "video ko song me badal do", "car ka colour red karo sirf", "mera chashma hata do", "gaana khud bana do",
               "AI avatar bana do mera", "ye video viral kar do", "followers badha do", "isse instagram pe post kar do",
               "hindi me dub karo", "baal kale kar do"]

DEVANAGARI = [("ज़ूम करो", "zoom_in"), ("गाना लगाओ", "add_music"), ("कैप्शन लगाओ", "auto_captions"), ("ब्लैक एंड व्हाइट करो", "grayscale"),
              ("धीमा करो वीडियो", "slow_motion"), ("तेज़ करो", "speed_up"), ("आवाज़ बंद करो", "mute"), ("शोर हटाओ", "denoise"),
              ("गर्म रंग करो", "warm"), ("ठंडा रंग", "cool"), ("चमक दो", "flash"), ("हिलाओ वीडियो", "shake"),
              ("धुंधला करो", "blur"), ("लोगो लगाओ", "watermark_logo"), ("वर्टिकल करो", "aspect_9_16"), ("स्क्वेयर करो", "aspect_1_1"),
              ("सिनेमैटिक करो", "cinematic_look"), ("पहले जैसा करो", "restore_normal"), ("सफ़ेद स्क्रीन", "white_screen_card"),
              ("ग्लिच करो", "glitch"), ("चुप वाले हिस्से हटाओ", "remove_silence"), ("रंग बढ़ाओ", "saturation"),
              ("कंट्रास्ट बढ़ाओ", "contrast"), ("सीपिया करो", "sepia"), ("विंटेज करो", "vintage_faded"),
              ("काले में फेड करो", "fade_black"), ("क्रॉसफेड लगाओ", "crossfade"), ("आवाज़ बढ़ाओ", "volume")]

RUNONS = [("bhai dekho na ye video thoda boring lag raha hai to isme na thoda music daal do jo upbeat ho", "add_music"),
          ("haan to mai soch raha tha ki agar hum isko black and white kar de to kaisa lagega kar do", "grayscale"),
          ("matlab jo bhi bol raha hu na wo neeche likha aaye subtitle jaisa", "auto_captions"),
          ("ye jo beech me koi kuch nahi bol raha wo sab hata do please time waste hai", "remove_silence"),
          ("uh so like can you make it a bit zoomed in maybe slowly", "zoom_in"),
          ("acha suno isko na instagram reel jaisa lamba wala khada format me karo", "aspect_9_16"),
          ("ek kaam karo poora video thoda garam garam sunset wala colour de do", "warm"),
          ("are yaar awaaz bahut dheemi hai isko thoda badhao na", "volume"),
          ("ye last wala part bohot slow hai usko fast kar do thoda", "speed_up"),
          ("background me jo shor aa raha hai fan ka wo hata sakte ho kya", "denoise"),
          ("video thoda hil raha hai camera shake ki wajah se usko theek karo", "stabilize"),
          ("bhai end me na dheere dheere kaala ho jaye aisa kuch", "fade_black"),
          ("purani film jaisa bhura sa look chahiye mujhe", "sepia"),
          ("ek dum movie wala feel aana chahiye colour me", "cinematic_look"),
          ("jab main bolu tab gaana dheema ho jaye aur baaki time normal", "duck_music"),
          ("mere logo ko kone me chipka do chhota sa", "watermark_logo")]


def handwritten_new() -> list[dict]:
    out: list[dict] = []

    def put(group: str, items: list[dict]) -> None:
        for i, it in enumerate(items):
            it["group"] = group
            it["split"] = "heldout" if i % 4 == 3 else "dev"
            out.append(it)
    put("relative", [{"kind": "relative", "prompt": p, "context": {"recent_edits": r}, "expect": s, "param": k, "direction": d}
                     for p, r, s, k, d in RELATIVE])
    put("multi", [{"kind": "multi", "prompt": p, "expect_all": e, "unsupported": u} for p, e, u in MULTI])
    put("non_edit", [{"kind": "non_edit", "prompt": p} for p in NON_EDIT])
    put("unsupported", [{"kind": "unsupported", "prompt": p} for p in UNSUPPORTED])
    put("devanagari", [{"kind": "single", "prompt": p, "expect": s} for p, s in DEVANAGARI])
    put("runon", [{"kind": "single", "prompt": p, "expect": s} for p, s in RUNONS])
    return out


FILL = ["bhai", "please", "yaar", "zara", "jaldi", "plz", "ek kaam karo", "na", "abhi"]


def generated() -> list[dict]:
    """Every skill's synonyms (up to 9) with 1-2 machine misspellings and a filler word — seeded, reproducible."""
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    from cutmind.tools import spec
    from cutmind.tools.variants import variants

    rnd = random.Random(20261010)
    out = []
    for sid, s in sorted(spec.load().items()):
        syns = [p for lang in ("en", "hinglish", "slang") for p in s["synonyms"].get(lang, [])][:9]
        for p in syns:
            words = p.split()
            cand = [i for i, w in enumerate(words) if variants(w)]
            for i in rnd.sample(cand, k=min(len(cand), rnd.choice([1, 2]))):
                words[i] = rnd.choice(variants(words[i]))
            if rnd.random() < 0.5:
                words.insert(0, rnd.choice(FILL))
            out.append({"kind": "single", "group": "generated", "split": "generated", "prompt": " ".join(words),
                        "expect": sid, "source": p})
    return out


def main() -> None:
    old = yaml.safe_load((ROOT / "eval" / "intent_corpus.yaml").read_text(encoding="utf-8"))["items"]
    for it in old:
        it.setdefault("kind", "single")
        it.setdefault("group", "intent_v1")
        it.setdefault("split", "dev")  # the 2 original-bug items have no split: dev
    items = old + handwritten_new() + generated()
    out = ROOT / "eval" / "understanding_corpus.yaml"
    out.write_text(yaml.safe_dump({"written": "2026-10-10", "items": items}, allow_unicode=True, sort_keys=False),
                   encoding="utf-8")
    from collections import Counter

    print(len(items), "items", dict(Counter(i["group"] for i in items)), dict(Counter(i["split"] for i in items)))


if __name__ == "__main__":
    main()
