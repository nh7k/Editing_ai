"""python -m cutmind.translator_bench [model ...] — which small model turns Hinglish into English best for the editor.

Score = the edit the rule brain reads from the model's English is right (each case checks the fields that matter).
"rules" = no model, the raw Hinglish straight into the rules (the baseline).
"""

from __future__ import annotations

import sys
import time
from typing import Any, Callable

from .intent import parse_intent
from .translator import MODELS, Translator

CASES: list[tuple[str, Callable[[Any], bool]]] = [
    ("purane zamane ki TV jaisa dikhao", lambda i: bool({"old_film", "film_bw", "vhs", "scanlines"} & set(i.effects))
     or i.color_preset in ("vintage", "sepia", "bw")),
    ("aawaz thodi gungunati si hai saaf karo", lambda i: i.voice_cleanup),
    ("rang thode feeke kar do", lambda i: i.color_preset in ("faded_film", "pastel") or i.saturation < 1 if hasattr(i, "saturation")
     else i.color_preset in ("faded_film", "pastel")),
    ("jaldi jaldi scene badlo", lambda i: i.fast_cuts),
    ("video ko thoda dramatic bana do jaise movie trailer hota hai", lambda i: i.color_preset in ("cinematic", "teal_orange")
     or "letterbox" in i.effects),
    ("thoda paas se dikhao chehra", lambda i: bool({"zoom", "person_zoom"} & set(i.effects))),
    ("kinare thode andhere karo", lambda i: "vignette" in i.effects),
    ("phone wala khada video bana do", lambda i: i.aspect_ratio == "9:16"),
    ("josh bhara gaana daal do", lambda i: i.music and i.music_mood == "upbeat"),
    ("atak atak ke bolna aur um aa hatao", lambda i: i.remove_fillers),
    ("video ki awaaz band karke naya gaana lagao", lambda i: i.mute and i.music),
    ("sabko dhundhla karo bas laal shirt wale ko saaf dikhao", lambda i: i.focus is not None and i.track_color == "#EF4444"),
    ("black and white mat karna, rangeen hi rakhna", lambda i: "bw" in i.avoid or (i.color_preset != "bw" and not i.color_pass
                                                                                  and "mono" not in i.effects)),
    ("30 second ka reel bana do instagram ke liye", lambda i: i.aspect_ratio == "9:16" and i.target_duration == 30),
    ("video ulta chala do", lambda i: i.reverse_playback),
    ("thoda dheere chalao, slow motion jaisa", lambda i: i.slow_motion),
    ("background music halka rakhna, meri awaaz zyada sunai de", lambda i: i.voice_boost or (i.music_volume or 1) < 0.3),
    ("shuru ke 3 second me zor ka zoom", lambda i: any(t.effect == "zoom" and t.end == 3 for t in i.timed_effects)),
    ("har beat pe screen jhatka khaye", lambda i: bool({"pulse", "shake"} & set(i.effects))),
    ("video thoda roshan karo, bahut kala lag raha hai", lambda i: i.brightness > 0),
]


def run(name: str) -> dict[str, Any]:
    tr = None if name == "rules" else Translator(name)
    t0 = time.time()
    if tr is not None:
        tr.load()
    load_s = time.time() - t0
    ok, rows, times = 0, [], []
    for text, check in CASES:
        t1 = time.time()
        english = text if tr is None else tr.translate(text)
        times.append(time.time() - t1)
        try:
            good = bool(check(parse_intent(english or text)))
        except Exception:  # noqa: BLE001
            good = False
        ok += good
        rows.append((good, text, english))
    return {"model": name, "score": ok, "of": len(CASES), "load_s": round(load_s, 1),
            "avg_s": round(sum(times) / len(times), 2), "rows": rows}


if __name__ == "__main__":
    for name in sys.argv[1:] or ["rules", *MODELS]:
        r = run(name)
        print(f"== {r['model']}: {r['score']}/{r['of']} right, load {r['load_s']}s, {r['avg_s']}s per sentence", flush=True)
        for good, text, english in r["rows"]:
            print(f"   {'OK ' if good else 'XX '} {text[:45]:45s} -> {english[:80]}", flush=True)
