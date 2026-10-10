"""Training data for the Hinglish → English translator (fine-tuned on Google Colab, see finetune_translator.ipynb).

Each example: a casual Hindi / Hinglish / English request  →  the clean English instruction(s) the CutMind editing
brain understands. Built from hand-written phrasings per editing command, spelling variants, filler words and 1–3
commands per request. Every target is checked against the real parser (it must be understood). The benchmark and the
held-out sentences (cutmind/translator_bench.py, tests) are kept OUT of training so the score after training is honest.

    python training/make_hinglish_dataset.py      → training/data/train.jsonl, training/data/eval.jsonl
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "backend"))
from cutmind.intent import parse_intent  # noqa: E402
from cutmind.translator_bench import CASES as BENCH  # noqa: E402

# held-out words: never in training (they measure if the model generalises to words it was not shown)
HELD_OUT_WORDS = ("ujla", "piche ki taraf", "neeli", "kone ", "kone,", "gungunati", "feeke", "khada video",
                  "paas se dikhao chehra", "kinare thode andhere", "dhundhla", "ulta chala do", "roshan")

# English instruction → ways people say it
UNITS: dict[str, list[str]] = {
    "Fast cuts.": ["jaldi jaldi cut karo", "fast cuts lagao", "tez editing karo", "scene jaldi jaldi badalne chahiye",
                   "cuts fast rakho", "quick cuts", "make the cuts faster", "snappy edit karo", "ek shot zyada der na ruke"],
    "Slow motion.": ["slow motion karo", "slow mo daal do", "dheere dheere chalao", "video dheema karo",
                     "slow down the video", "thoda slow chalao", "slowmo effect"],
    "Cut on the beat.": ["beat pe cut karo", "gaane ki beat ke saath cut", "music ke taal pe cuts", "sync to the beat",
                         "har cut beat pe aaye", "taal ke hisaab se kaato"],
    "Zoom in effect.": ["zoom karo", "zoom in karo", "andar ki taraf zoom", "thoda zoom daalo", "zoom in please",
                        "video pe zoom effect"],
    "Shake effect.": ["screen hilao", "camera shake daalo", "video hilna chahiye", "jhatke wala effect",
                      "shaky camera", "camera ko hilao"],
    "Pulse effect.": ["beat pe zoom punch", "har beat pe jhatka", "beat ke saath zoom ho", "bass pe screen uchhle",
                      "zoom punch on every beat"],
    "Glitch effect.": ["glitch effect daalo", "toota hua screen effect", "digital kharabi jaisa effect", "glitchy look"],
    "Flash effect.": ["white flash daalo", "safed chamak", "camera flash jaisa effect", "flash effect"],
    "Old movie black and white look.": ["purani film jaisa", "old movie jaisa black and white", "purane zamane ki film",
                                        "vintage black and white movie look", "old film look do", "1950 wali film jaisa"],
    "Black and white.": ["black and white kar do", "rang hata do sab grey", "b&w bana do", "kala safed video",
                         "make it black and white", "bina rang ka video"],
    "Warm color.": ["warm colour do", "garam rang", "sunehra look", "golden tone", "peela sa warm look", "warm tones"],
    "Cool color.": ["cool tone do", "thanda rang", "neela sa tone", "blue tone", "cold colours"],
    "Vivid color.": ["rang gehre karo", "colours tez karo", "zyada rangeen", "colours pop karne chahiye", "vibrant bana do"],
    "Faded film look.": ["rang halke karo", "colours dull kar do", "faded look", "muted colours", "rang kam kar do",
                         "fika fika sa look"],
    "Cinematic color.": ["cinematic bana do", "film jaisa look", "movie jaisa dikhe", "hollywood look", "dramatic look do"],
    "Brighter.": ["thoda bright karo", "roshni badhao", "ujala karo", "video kala lag raha hai", "andhera hai thoda",
                  "brightness badhao", "make it brighter"],
    "Darker.": ["thoda dark karo", "roshni kam karo", "bahut bright hai", "make it darker", "andhera sa karo"],
    "Add captions.": ["captions lagao", "subtitle daalo", "jo bol raha hu wo likh do", "bolne wale shabd screen pe",
                      "add subtitles", "captions chahiye"],
    "Remove the captions.": ["captions hata do", "subtitle mat lagao", "no captions", "caption nahi chahiye"],
    "Remove silences.": ["chup wale hisse hatao", "jahan koi nahi bol raha wo kaat do", "silence hata do",
                         "khamoshi wale part nikal do", "remove the silent parts", "dead air hatao"],
    "Remove filler words.": ["um aa hata do", "atakna hatao", "matlab matlab bolna kaat do", "remove filler words",
                             "aa ee wale shabd hatao"],
    "Clean up the audio.": ["awaaz saaf karo", "aawaz clear karo", "background noise hatao", "shor hata do",
                            "hawa ki awaaz hatao", "mic ki khar khar hatao", "clean the audio", "noise remove karo"],
    "Boost the voice.": ["meri awaaz tez karo", "voice badhao", "awaaz zyada sunai de", "boost the voice",
                         "bolna clear aur tez ho"],
    "Add upbeat music.": ["josh wala gaana", "party music lagao", "upbeat music daalo", "energetic gaana chahiye",
                          "dhamakedar song"],
    "Add calm music.": ["shaant gaana lagao", "soft music", "lofi lagao", "calm music daalo", "relaxing song"],
    "No music.": ["gaana mat lagao", "bina music ke", "music nahi chahiye", "no background music"],
    "Mute the original sound.": ["video ki awaaz band karo", "original sound hatao", "clip ki awaaz mat rakho",
                                 "mute karo video ko"],
    "Blur the background.": ["background blur karo", "peeche ka dhundla karo", "blur the background"],
    "Speed ramp.": ["speed ramp daalo", "pehle slow phir fast", "speed badalte raho"],
    "9:16 vertical.": ["reel size me bana do", "9:16 karo", "instagram reel format", "vertical video", "shorts ke liye",
                       "phone ke liye seedha video"],
    "16:9 landscape.": ["youtube size", "16:9 karo", "landscape video", "leta hua video", "wide format"],
    "Fade transitions.": ["fade transition lagao", "dheere se scene badle", "smooth transition", "crossfade daalo"],
    "Vignette effect.": ["vignette lagao", "corners dark karo", "kinare kale karo", "dark edges"],
    "Film grain effect.": ["film grain daalo", "grainy look", "daane daar film"],
    "Auto edit: you decide everything else.": ["mast sa edit kar do", "badhiya bana do", "tum khud decide karo",
                                               "jo accha lage wo karo", "make it awesome", "apne hisaab se edit karo"],
    "Reverse order.": ["clips ulte order me", "reverse order", "aakhri clip pehle"],
    "Play the video backwards.": ["video ulta chalao", "reverse playback", "peeche ki or chalao", "rewind jaisa chalao"],
    "Person zoom effect.": ["chehre pe zoom", "face pe close up", "us bande pe zoom karo", "close up on the face"],
    "Keep the text in front of the person.": ["text aage lao", "caption person ke aage rakho",
                                              "text in front of the person"],
    "Text behind the person.": ["text person ke peeche", "naam bande ke peeche likho", "text behind the person"],
    "No black and white.": ["black and white mat karna", "b&w nahi chahiye", "rang wala hi rakho, black and white nahi"],
    "No zoom in.": ["zoom mat karna", "zoom nahi chahiye", "no zoom please"],
}
# commands with a value
PARAM_UNITS = [
    ("{n} seconds.", ["{n} second ka video", "{n} sec ka bana do", "{n} seconds long", "{n} second tak trim karo"]),
    ("Strong zoom in for the first {k} seconds.", ["shuru ke {k} second me bahut zoom", "pehle {k} sec zor se zoom",
                                                  "starting {k} seconds me bada zoom"]),
    ("Black and white for the last {k} seconds.", ["aakhri {k} second black and white", "last {k} sec b&w"]),
    ("Focus on the person in {c} shirt, blur the rest.", ["{c} shirt wale pe focus karo baaki blur",
                                                          "sirf {c} t-shirt wala saaf dikhe baaki blur",
                                                          "{c} kapde wale ko focus karo, baaki sab blur"]),
    ("{cw} captions.", ["captions {c} rang me", "{c} colour ke subtitles", "subtitle {c} rakho"]),
]
COLORS = {"laal": "red", "red": "red", "peela": "yellow", "yellow": "yellow", "hara": "green", "green": "green",
          "blue": "blue", "neela": "blue", "safed": "white", "white": "white", "kala": "black", "black": "black"}
FILLERS_PRE = ["", "", "", "bhai ", "yaar ", "please ", "bhai please ", "suno ", "ek kaam karo ", "isko "]
FILLERS_POST = ["", "", "", " please", " yaar", " na", " bhai", " jaldi"]
JOINERS = [" aur ", ", ", " phir ", " and ", ", aur "]
NOT_EDITING = ["mera kutta cute hai", "aaj mausam accha hai", "tum kaise ho", "kal milte hai", "hello", "thanks bhai",
               "ye video meri trip ka hai", "maine ye kal shoot kiya"]


def spell(s: str, rng: random.Random) -> str:
    """Hinglish spelling noise: aa↔a, ee↔i, z↔j, oo↔u, h dropped."""
    swaps = [("aa", "a"), ("ee", "i"), ("oo", "u"), ("z", "j"), ("w", "v"), ("kh", "k")]
    for a, b in swaps:
        if a in s and rng.random() < 0.25:
            s = s.replace(a, b, 1)
    return s


def example(rng: random.Random) -> tuple[str, str]:
    parts, targets = [], []
    for _ in range(rng.choice([1, 1, 2, 2, 3])):
        if rng.random() < 0.25:
            tmpl, says = rng.choice(PARAM_UNITS)
            n, k = rng.choice([10, 15, 20, 30, 45, 60]), rng.choice([2, 3, 4, 5])
            cw = rng.choice(list(COLORS))
            target = tmpl.format(n=n, k=k, c=COLORS[cw], cw=COLORS[cw].capitalize())
            said = rng.choice(says).format(n=n, k=k, c=cw)
        else:
            target, says = rng.choice(list(UNITS.items()))
            said = rng.choice(says)
        if target in targets:
            continue
        targets.append(target)
        parts.append(spell(said, rng))
    text = rng.choice(FILLERS_PRE) + rng.choice(JOINERS).join(parts) + rng.choice(FILLERS_POST)
    return text.strip(), " ".join(targets)


def build(n: int = 9000, seed: int = 7) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    bench = {b[0].lower() for b in BENCH}
    seen: set[str] = set()
    rows: list[dict] = []
    for target in list(UNITS) + [p[0] for p in PARAM_UNITS]:
        assert "{" in target or parse_intent(target).recognized, f"the parser doesn't understand '{target}'"
    while len(rows) < n:
        text, target = example(rng)
        low = text.lower()
        if low in seen or low in bench or any(w in low for w in HELD_OUT_WORDS):
            continue
        if not parse_intent(target).recognized:
            continue
        seen.add(low)
        rows.append({"input": text, "output": target})
    for t in NOT_EDITING:
        rows += [{"input": t, "output": "-"}] * 4  # not an editing request: the model answers "-"
    rng.shuffle(rows)
    cut = int(len(rows) * 0.95)
    return rows[:cut], rows[cut:]


if __name__ == "__main__":
    train, ev = build()
    out = ROOT / "data"
    out.mkdir(exist_ok=True)
    for name, rows in (("train", train), ("eval", ev)):
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"train {len(train)}  eval {len(ev)}  -> {out}")
    for r in train[:8]:
        print(f"  {r["input"]}  ->  {r["output"]}")
    assert not re.search("|".join(map(re.escape, HELD_OUT_WORDS)), " ".join(r["input"].lower() for r in train))
