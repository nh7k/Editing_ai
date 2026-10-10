"""One-time writer of the 9 transition Tier 1 specs. Hand-written data; the YAML files are the source of truth after.

    backend/.venv/Scripts/python.exe skills/tools/write_tier1_transitions.py
"""

from __future__ import annotations

from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parents[1] / "tier1"
DUR = {"type": "number", "default": 0.6, "min": 0.15, "max": 2.0, "unit": "s", "extract": "seconds", "desc": "length"}
CUT = {"type": "integer", "min": 1, "max": 500, "extract": "cut_number", "desc": "which cut (default every cut)"}
DIRN = {"type": "choice", "choices": ["left", "right", "up", "down"], "default": "left", "extract": "direction", "desc": "direction"}
XF = "xfade={x} + acrossfade (tri)"
M3 = {"status": "custom_shader", "how": "a GlEffect over the overlap of two sequences (Composition) — NOT TESTED"}

SKILLS = [
    dict(id="crossfade", seed=17, name="Crossfade", name_hi="Dheere se badlo", params={"duration": DUR, "cut": CUT},
         graph=XF.format(x="fade"), media3={"status": "mapped", "how": "two overlapping sequences + alpha ramp (VideoCompositorSettings) — NOT TESTED"},
         conflicts=["fade_black", "fade_white", "wipe", "slide", "zoom_transition", "whip_pan", "iris_circle", "glitch_transition"],
         axes={"duration": ["0.3s", "0.6s", "1.2s"]},
         syn={"en": ["crossfade", "dissolve", "smooth transition", "blend the clips", "soft transition", "cross dissolve", "mix transition"],
              "hinglish": ["dheere se badlo", "smooth transition do", "mix hoke badle", "crossfade lagao", "dheere badle scene", "ghul ke badle", "aaram se badlo"],
              "hi": ["धीरे से बदलो", "क्रॉसफ़ेड", "घुल के बदले"], "slang": ["makkhan transition"], "typos": ["crosfade", "cross fad", "dissolv"]},
         neg=["crossfade mat lagao", "transition mat lagao"],
         ex=[("add crossfades between the clips", "en", None), ("1 second dissolve", "en", {"duration": 1.0}),
             ("धीरे से बदलो सीन", "hi", None), ("smooth transition do", "hinglish", None), ("crossfade lagao 2nd cut pe", "hinglish", None),
             ("crosfade", "typo", None), ("jhatke se na badle", "vague", None), ("crossfade aur music", "multi", {"_also": ["add_music"]})],
         test={"check": "blend_mid", "params": {"duration": 0.8}}),
    dict(id="fade_black", seed=18, name="Fade through black", name_hi="Kala fade",
         params={"duration": DUR, "cut": CUT,
                 "where": {"type": "choice", "choices": ["cuts", "start", "end", "start_end"], "default": "cuts",
                           "extract": "fade_where", "desc": "between shots or at the start / end"}},
         graph=XF.format(x="fadeblack") + "; fade in/out filters at the edges",
         media3={"status": "mapped", "how": "alpha/brightness ramp to black around the cut — NOT TESTED"},
         conflicts=["crossfade", "fade_white"], axes={"where": ["cuts", "start", "end", "start_end"], "duration": ["0.4s", "0.8s"]},
         syn={"en": ["fade to black", "fade through black", "fade in", "fade out", "fade in and out", "dip to black", "black fade"],
              "hinglish": ["kala fade", "andhera karke badlo", "fade lagao", "end me fade out", "shuru me fade in", "fade in fade out karo", "kale me badlo"],
              "hi": ["फेड इन", "फेड आउट", "काला फ़ेड"], "slang": ["movie wala fade"], "typos": ["fad out", "faed in", "fade blak"]},
         neg=["fade mat lagao"],
         ex=[("fade to black between shots", "en", {"where": "cuts"}), ("fade in at the start and fade out at the end", "en", {"where": "start_end"}),
             ("फेड इन फेड आउट", "hi", {"where": "start_end"}), ("end me fade out", "hinglish", {"where": "end"}),
             ("andhera karke badlo", "hinglish", None), ("faed out at end", "typo", {"where": "end"}), ("dheere se khatam ho", "vague", None),
             ("fade out aur music", "multi", {"_also": ["add_music"]})],
         test={"check": "dark_mid", "params": {"duration": 0.8}}),
    dict(id="fade_white", seed=19, name="Fade through white", name_hi="Safed fade", same_engine_as="fade_black",
         params={"duration": DUR, "cut": CUT}, graph=XF.format(x="fadewhite"),
         media3={"status": "mapped", "how": "brightness ramp to white around the cut — NOT TESTED"},
         conflicts=["crossfade", "fade_black"], axes={"duration": ["0.3s", "0.6s"]},
         syn={"en": ["fade to white", "white fade", "white flash fade", "dip to white", "flash transition", "white transition", "bright fade"],
              "hinglish": ["safed fade", "white flash fade", "safed me badlo", "chamak ke badle", "white transition do", "ujale me badlo", "flash wala badlav"],
              "hi": ["सफ़ेद फ़ेड", "सफ़ेद में बदलो", "चमक के बदले"], "slang": ["dream flash"], "typos": ["white fad", "whit fade", "safed fad"]},
         neg=["white fade mat lagao"],
         ex=[("fade through white", "en", None), ("white flash between shots", "en", None), ("सफ़ेद में बदलो", "hi", None),
             ("safed fade lagao", "hinglish", None), ("chamak ke badle scene", "hinglish", None), ("whit fade", "typo", None),
             ("sapne jaisa badlav", "vague", None), ("white fade aur slow motion", "multi", {"_also": ["slow_motion"]})],
         test={"check": "bright_mid", "params": {"duration": 0.8}}),
    dict(id="wipe", seed=20, name="Wipe", name_hi="Pardah transition", params={"direction": DIRN, "duration": DUR, "cut": CUT},
         graph=XF.format(x="wipeleft/right/up/down"), media3=M3, conflicts=["crossfade"],
         axes={"direction": ["left", "right", "up", "down"], "duration": ["0.4s", "0.8s"]},
         syn={"en": ["wipe", "wipe transition", "wipe left", "wipe right", "curtain transition", "line wipe", "wipe across"],
              "hinglish": ["side se mitao", "pardah transition", "wipe lagao", "pardah girao", "line se badle", "ek taraf se mitao", "wipe karke badlo"],
              "hi": ["वाइप", "पर्दा ट्रांज़िशन", "एक तरफ़ से मिटाओ"], "slang": ["curtain wala"], "typos": ["wipp", "wype", "wipe transtion"]},
         neg=["wipe mat lagao"],
         ex=[("wipe transition", "en", None), ("wipe to the right", "en", {"direction": "right"}), ("पर्दा ट्रांज़िशन लगाओ", "hi", None),
             ("pardah transition do", "hinglish", None), ("upar se wipe karo", "hinglish", {"direction": "up"}), ("wype", "typo", None),
             ("ek line chal ke badle", "vague", None), ("wipe aur whoosh", "multi", {"_also": ["sfx_whoosh"]})],
         test={"check": "split_mid", "params": {"direction": "left", "duration": 0.8}}),
    dict(id="slide", seed=21, name="Slide", name_hi="Sarkao", params={"direction": DIRN, "duration": DUR, "cut": CUT},
         graph=XF.format(x="slideleft/right/up/down"), media3=M3, conflicts=["crossfade"],
         axes={"direction": ["left", "right", "up", "down"]},
         syn={"en": ["slide", "slide transition", "slide in", "push transition", "slide left", "slide right", "swipe transition"],
              "hinglish": ["sarkao", "side se aaye", "slide karke badlo", "khisak ke aaye", "slide transition do", "dhakel ke badle", "swipe wala"],
              "hi": ["सरकाओ", "साइड से आए", "स्लाइड करो"], "slang": ["insta swipe"], "typos": ["slid", "sliide", "slyde"]},
         neg=["slide mat karo"],
         ex=[("slide transition", "en", None), ("slide in from the right", "en", {"direction": "right"}), ("साइड से आए", "hi", None),
             ("slide karke badlo", "hinglish", None), ("upar se sarkao", "hinglish", {"direction": "up"}), ("slyde", "typo", None),
             ("story ki tarah badle", "vague", None), ("slide transition aur music", "multi", {"_also": ["add_music"]})],
         test={"check": "split_mid", "params": {"direction": "left", "duration": 0.8}}),
    dict(id="zoom_transition", seed=22, name="Zoom transition", name_hi="Zoom karke badlo", params={"duration": DUR, "cut": CUT},
         graph=XF.format(x="zoomin"), media3=M3, conflicts=["crossfade"], axes={"duration": ["0.4s", "0.8s"]},
         syn={"en": ["zoom transition", "zoom through", "zoom cut", "zoom into the next", "punch transition", "zoom blur transition", "zoom between"],
              "hinglish": ["zoom karke badlo", "zoom wala transition", "zoom se badle", "andar ghus ke badle", "zoom transition do", "zoom kat", "zoom karke agla"],
              "hi": ["ज़ूम ट्रांज़िशन", "ज़ूम करके बदलो"], "slang": ["travel wala zoom"], "typos": ["zoom transtion", "zom transition", "zoom transision"]},
         neg=["zoom transition mat lagao"],
         ex=[("zoom transition", "en", None), ("zoom through to the next clip", "en", None), ("ज़ूम करके बदलो", "hi", None),
             ("zoom karke badlo", "hinglish", None), ("zoom wala transition do", "hinglish", None), ("zom transition", "typo", None),
             ("travel vlog jaisa transition", "vague", None), ("zoom transition aur beat sync", "multi", {"_also": ["beat_sync"]})],
         test={"check": "differs_mid", "params": {"duration": 0.8}}),
    dict(id="whip_pan", seed=23, name="Whip pan", name_hi="Jhatke se badlo",
         params={"direction": {**DIRN, "choices": ["left", "right"]}, "duration": {**DUR, "default": 0.35, "max": 0.8}, "cut": CUT,
                 "whoosh": {"type": "bool", "default": True, "desc": "add a whoosh sound"}},
         graph="xfade=slideleft/right + gblur (horizontal) over the overlap; a generated whoosh", media3=M3,
         conflicts=["crossfade"], axes={"direction": ["left", "right"], "whoosh": ["on", "off"]},
         syn={"en": ["whip pan", "whip transition", "swoosh transition", "fast pan transition", "whip", "smear transition", "speed pan"],
              "hinglish": ["jhatke se badlo", "whip lagao", "swoosh wala transition", "tez pan ke badle", "jhatak ke badle", "whoosh transition", "phatak se badle"],
              "hi": ["झटके से बदलो", "व्हिप पैन", "स्वूश ट्रांज़िशन"], "slang": ["fast cut wala"], "typos": ["wip pan", "whipp", "wip transition"]},
         neg=["whip mat lagao"],
         ex=[("whip pan between shots", "en", None), ("whip transition to the right", "en", {"direction": "right"}),
             ("झटके से बदलो", "hi", None), ("jhatke se badlo scene", "hinglish", None), ("whoosh transition do", "hinglish", None),
             ("wip pan", "typo", None), ("energetic travel cut", "vague", None), ("whip pan aur shake", "multi", {"_also": ["shake"]})],
         test={"check": "smeared_mid", "params": {"direction": "left", "duration": 0.5}}),
    dict(id="iris_circle", seed=24, name="Iris (circle)", name_hi="Gola khule",
         params={"mode": {"type": "choice", "choices": ["open", "close"], "default": "open", "desc": "opens or closes"},
                 "duration": DUR, "cut": CUT},
         graph=XF.format(x="circleopen/circleclose"), media3=M3, conflicts=["crossfade"], axes={"mode": ["open", "close"]},
         syn={"en": ["circle transition", "iris", "iris wipe", "circle open", "circle close", "round transition", "cartoon circle"],
              "hinglish": ["gola khule", "circle wala transition", "gol transition", "gola band ho", "cartoon jaisa gola", "iris lagao", "gol ghera"],
              "hi": ["गोला खुले", "सर्कल ट्रांज़िशन", "गोल ट्रांज़िशन"], "slang": ["that's all folks wala"], "typos": ["cirle transition", "irish", "circel"]},
         neg=["circle mat lagao"],
         ex=[("circle transition", "en", None), ("iris close", "en", {"mode": "close"}), ("गोला खुले", "hi", None),
             ("gola khule wala transition", "hinglish", None), ("cartoon jaisa gola band ho", "hinglish", {"mode": "close"}),
             ("cirle transition", "typo", None), ("purane cartoon jaisa", "vague", None), ("iris aur vintage", "multi", {"_also": ["vintage_faded"]})],
         test={"check": "split_mid", "params": {"mode": "open", "duration": 0.8}}),
    dict(id="glitch_transition", seed=25, name="Glitch transition", name_hi="Glitch wala cut",
         params={"duration": {**DUR, "default": 0.4, "max": 1.0}, "cut": CUT},
         graph="xfade=pixelize + rgbashift + noise over the overlap", media3=M3, conflicts=["crossfade"],
         axes={"duration": ["0.25s", "0.4s", "0.8s"]},
         syn={"en": ["glitch transition", "glitch cut", "digital transition", "pixel transition", "glitchy transition", "error transition", "data glitch"],
              "hinglish": ["glitch wala cut", "glitch transition do", "toot ke badle", "digital transition lagao", "pixel ho ke badle", "glitch karke badlo", "hang hoke badle"],
              "hi": ["ग्लिच ट्रांज़िशन", "टूट के बदले"], "slang": ["gaming wala cut"], "typos": ["glich transition", "glitch transtion", "gltch cut"]},
         neg=["glitch transition mat lagao"],
         ex=[("glitch transitions", "en", None), ("pixel transition", "en", None), ("ग्लिच ट्रांज़िशन लगाओ", "hi", None),
             ("glitch wala cut do", "hinglish", None), ("toot ke badle scene", "hinglish", None), ("glich transition", "typo", None),
             ("gaming video jaisa cut", "vague", None), ("glitch transition aur rgb split", "multi", {"_also": ["rgb_split"]})],
         test={"check": "torn_mid", "params": {"duration": 0.6}}),
]


def main() -> None:
    for s in SKILLS:
        examples = []
        for prompt, lang, extra in s["ex"]:
            e: dict = {"prompt": prompt, "lang": lang}
            extra = dict(extra or {})
            if "_also" in extra:
                e["also"] = extra.pop("_also")
            if extra:
                e["params"] = extra
            examples.append(e)
        doc = {
            "id": s["id"], "seed": s["seed"], "category": "transitions", "name": s["name"], "name_hi": s["name_hi"],
            "description": {"crossfade": "Blend from one shot into the next.",
                            "fade_black": "Dip to black between shots, or fade in / out at the start / end.",
                            "fade_white": "Dip to white between shots.",
                            "wipe": "A line wipes the next shot in (left / right / up / down).",
                            "slide": "The next shot slides in and pushes the old one out.",
                            "zoom_transition": "Zoom into the cut and land on the next shot.",
                            "whip_pan": "A fast sideways slide with motion blur (and a whoosh) — the travel-vlog cut.",
                            "iris_circle": "A circle opens on the next shot (or closes on the old one).",
                            "glitch_transition": "The picture breaks into pixels and torn RGB, then rebuilds."}[s["id"]]
            + " Each overlap makes the video that much shorter.",
            **({"same_engine_as": s["same_engine_as"]} if "same_engine_as" in s else {}),
            "params": s["params"], "time_modes": ["whole", "between_times"], "builder": f"transitions.{s['id']}",
            "graph": s["graph"], "media3": s["media3"], "stage": "structure", "conflicts": s["conflicts"],
            "cost": "cheap", "licence": "own code; FFmpeg xfade / gblur / rgbashift (server process); whoosh generated",
            "changes_duration": True, "needs": ["two_clips"], "variant_axes": s["axes"], "synonyms": s["syn"],
            "negations": s["neg"], "examples": examples, "test": s["test"],
        }
        (OUT / f"{s['id']}.yaml").write_text("# written by skills/tools/write_tier1_transitions.py — edit this file directly from now on\n"
                                             + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
        print(s["id"])


if __name__ == "__main__":
    main()
