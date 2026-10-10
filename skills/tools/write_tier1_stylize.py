"""One-time writer of the 11 stylize / overlay Tier 1 specs. Hand-written data; the YAML files are the source of truth after.

    backend/.venv/Scripts/python.exe skills/tools/write_tier1_stylize.py
"""

from __future__ import annotations

from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parents[1] / "tier1"
VIDEO_MODES = ["whole", "segment", "between_times", "intermittent"]
WINDOW = {"mode": "between_times", "start": 1.0, "end": 3.0}
MAG = lambda d=1.0, lo=0.3, hi=3.0: {"type": "number", "default": d, "min": lo, "max": hi, "extract": "magnitude", "desc": "how strong"}  # noqa: E731
SHADER = {"status": "custom_shader", "how": "a GlEffect fragment shader port — NOT TESTED"}
REGION = {"type": "choice", "choices": ["face", "center", "top", "bottom", "left", "right", "top_left", "top_right", "bottom_left", "bottom_right"],
          "default": "center", "extract": "region", "desc": "where"}

SKILLS = [
    dict(id="glitch", seed=65, name="Glitch", name_hi="Hang jaisa", desc="Digital glitch: jittering RGB split + noise bursts.",
         params={"intensity": MAG()}, modes=VIDEO_MODES + ["at_beats"], graph="rgbashift with jitter + noise", media3=SHADER,
         axes={"intensity": ["light", "normal", "heavy"]}, check="differs_in_window",
         syn={"en": ["glitch", "glitch effect", "digital glitch", "glitchy", "corrupted look", "datamosh", "error effect"],
              "hinglish": ["hang hua jaisa", "glitch lagao", "toota hua screen", "glitch wala effect", "digital effect do", "kharab tv jaisa", "atakta hua video"],
              "hi": ["ग्लिच", "हैंग जैसा", "टूटी स्क्रीन"], "slang": ["gaming wala glitch"], "typos": ["glich", "gltch", "glitchh"]}),
    dict(id="vhs_retro", seed=66, name="VHS retro", name_hi="Purana camera", desc="Retro tape: colour bleed, noise, scanlines, washed colours.",
         params={"intensity": MAG()}, modes=VIDEO_MODES, graph="chromashift + vintage curves + noise + drawgrid", media3=SHADER,
         axes={"intensity": ["light", "normal"]}, check="differs_in_window",
         syn={"en": ["vhs", "vhs effect", "retro tape", "camcorder look", "90s tape", "old video look", "tape effect"],
              "hinglish": ["purana camera", "vhs lagao", "90s wala look", "purani cassette jaisa", "handycam jaisa", "retro tape look", "purani shaadi ki video jaisa"],
              "hi": ["पुराना कैमरा", "वीएचएस", "पुरानी कैसेट जैसा"], "slang": ["dad ki handycam"], "typos": ["vhs effct", "vsh", "vhs efect"]}),
    dict(id="rgb_split", seed=67, name="RGB split", name_hi="Rang alag alag", desc="Chromatic aberration: red and blue pulled apart.",
         params={"amount": MAG()}, modes=VIDEO_MODES + ["at_beats"], graph="rgbashift", media3=SHADER,
         axes={"amount": ["light", "normal", "heavy"]}, check="channels_apart",
         syn={"en": ["rgb split", "chromatic aberration", "colour split", "rgb shift", "channel split", "aberration", "colour fringe"],
              "hinglish": ["rang alag alag", "rgb split lagao", "rang khiske hue", "lal neela alag", "color shift karo", "rang ki parchhai", "chromatic do"],
              "hi": ["रंग अलग अलग", "आरजीबी स्प्लिट", "रंग खिसके"], "slang": ["3d glasses wala"], "typos": ["rgb splt", "rbg split", "chromatik"]}),
    dict(id="flash", seed=68, name="Flash", name_hi="Chamak", desc="A white flash at cuts, beats or given times.",
         params={"intensity": {**MAG(1.0, 0.3, 1.0)}}, modes=["whole", "at_time", "at_beats", "on_scene_change", "intermittent"],
         graph="eq brightness bumps at the times", media3={"status": "mapped", "how": "Brightness effect keyed per frame — NOT TESTED"},
         axes={"on": ["cuts", "beats", "time"]}, check="flash_peaks",
         syn={"en": ["flash", "white flash", "camera flash", "flash on the beat", "flash at cuts", "bright flash", "photo flash"],
              "hinglish": ["chamak", "flash lagao", "safed chamak", "beat pe flash", "camera ki chamak", "chamakna", "flash do cut pe"],
              "hi": ["चमक", "फ़्लैश", "सफ़ेद चमक"], "slang": ["paparazzi flash"], "typos": ["flsh", "flash lgao", "flah"]}),
    dict(id="light_leak", seed=69, name="Light leak", name_hi="Roshni ka leak", desc="A moving warm glow (procedural, own maths) washes over the picture.",
         params={"color": {"type": "color", "default": "#FF7A18", "extract": "color", "desc": "colour"},
                 "strength": MAG(1.0, 0.3, 2.0), "duration": {"type": "number", "default": 2.0, "min": 0.5, "max": 10, "unit": "s", "extract": "seconds", "desc": "how long"}},
         modes=["whole", "between_times", "at_time", "on_scene_change"], graph="gradients (radial, moving) + screen blend", media3=SHADER,
         axes={"color": ["orange", "pink", "gold"], "length": ["1s", "2s", "4s"]}, check="warm_glow",
         syn={"en": ["light leak", "light leaks", "film burn", "warm glow", "lens leak", "flare", "sun leak"],
              "hinglish": ["roshni ka leak", "light leak lagao", "garam roshni", "film burn wala", "roshni ki lehar", "chamakti roshni", "sunehri roshni"],
              "hi": ["रोशनी का लीक", "लाइट लीक", "गर्म रोशनी"], "slang": ["dreamy wali roshni"], "typos": ["lite leak", "light leek", "lightleak"]}),
    dict(id="mirror_effect", seed=70, name="Mirror", name_hi="Aaina", desc="Mirror the picture: left onto right (h), top onto bottom (v), or four-way.",
         params={"axis": {"type": "choice", "choices": ["h", "v", "both"], "default": "h", "extract": "mirror_axis", "desc": "which way"}},
         modes=VIDEO_MODES, graph="geq (mirrored coordinates)", media3=SHADER, axes={"axis": ["h", "v", "both"]}, check="mirrored",
         syn={"en": ["mirror effect", "mirror", "symmetric", "kaleidoscope", "mirrored image", "reflection effect", "symmetry"],
              "hinglish": ["aaina", "mirror effect do", "dono taraf same", "symmetric banao", "aaine jaisa", "ulta seedha same", "chaar taraf mirror"],
              "hi": ["आईना", "मिरर इफ़ेक्ट", "दोनों तरफ़ एक जैसा"], "slang": ["trippy mirror"], "typos": ["miror", "mirror efect", "aina effect"]}),
    dict(id="pixelate_censor", seed=71, name="Pixelate (censor)", name_hi="Chehra chhupao",
         desc="A pixelated box over an area (or the face found there) for a time window.",
         params={"region": REGION, "strength": MAG(1.0, 0.5, 3.0)}, modes=["whole", "between_times", "segment"],
         graph="crop → scale down / up (neighbour) → overlay", media3={"status": "mapped", "how": "Crop + low-res scale on a second layer — NOT TESTED"},
         axes={"region": ["face", "center", "corner"], "blocks": ["fine", "coarse"]}, check="censored_pixelate",
         syn={"en": ["pixelate", "censor", "mosaic", "hide the face", "pixel blur", "blur the face", "pixelate the number plate"],
              "hinglish": ["chehra chhupao", "pixel kar do", "mosaic lagao", "number plate chhupao", "censor karo", "dabba bana do chehre pe", "pehchaan na aaye"],
              "hi": ["चेहरा छुपाओ", "पिक्सेल कर दो", "मोज़ेक लगाओ"], "slang": ["blur wala dabba"], "typos": ["pixlate", "censer", "mozaic"]}),
    dict(id="blur_box_censor", seed=72, name="Blur box (censor)", name_hi="Chhupa do",
         desc="A blurred box over an area (or the face found there) for a time window.", same="pixelate_censor",
         params={"region": REGION, "strength": MAG(1.0, 0.5, 3.0)}, modes=["whole", "between_times", "segment"],
         graph="crop → boxblur → overlay", media3={"status": "mapped", "how": "Crop + GaussianBlur on a second layer — NOT TESTED"},
         axes={"region": ["face", "center", "corner"], "blur": ["soft", "strong"]}, check="censored_blur",
         syn={"en": ["blur box", "blur the area", "blur out", "censor with blur", "hide with blur", "blur the logo", "blur this part"],
              "hinglish": ["chhupa do", "blur box lagao", "ye hissa blur karo", "logo blur karo", "dhundhla dabba", "naam chhupa do", "us jagah blur"],
              "hi": ["छुपा दो", "ब्लर बॉक्स", "यह हिस्सा धुंधला"], "slang": ["dhundh wala dabba"], "typos": ["blurbox", "blur boxx", "chupa do"]}),
    dict(id="shape_highlight", seed=73, name="Highlight shape", name_hi="Circle / arrow lagao",
         desc="A box, ring or arrow (own drawing) pointing at an area for a while.",
         params={"shape": {"type": "choice", "choices": ["box", "ring", "arrow"], "default": "ring", "desc": "shape"},
                 "region": REGION, "color": {"type": "color", "default": "#FFD60A", "extract": "color", "desc": "colour"},
                 "angle": {"type": "number", "default": 0, "min": -180, "max": 180, "desc": "arrow direction (degrees)"}},
         modes=["whole", "between_times", "at_time"], graph="drawbox / generated PNG (Pillow) overlay with pop-in", media3={"status": "mapped", "how": "BitmapOverlay"},
         axes={"shape": ["box", "ring", "arrow"], "color": ["yellow", "red"]}, check="shape_drawn",
         syn={"en": ["highlight", "circle it", "add an arrow", "point at", "draw a box", "circle this", "arrow pointing"],
              "hinglish": ["circle lagao", "arrow lagao", "yahan dikhao", "gol ghera banao", "teer lagao", "dabba banao", "is cheez pe nishaan"],
              "hi": ["गोला लगाओ", "तीर लगाओ", "यहाँ दिखाओ"], "slang": ["youtuber wala circle"], "typos": ["circel lagao", "arow", "hilight"]}),
    dict(id="sticker_lottie", seed=74, name="Animated sticker", name_hi="Sticker lagao",
         desc="An animated emoji sticker (pops in, fades out). Server: our emoji renderer; Lottie files: phone only (lottie-android, Apache-2.0).",
         params={"emoji": {"type": "string", "default": "🔥", "extract": "emoji", "desc": "emoji"},
                 "position": {"type": "choice", "choices": ["top_left", "top_right", "bottom_left", "bottom_right", "center"], "default": "top_right",
                              "extract": "position", "desc": "where"},
                 "size": {"type": "number", "default": 0.22, "min": 0.08, "max": 0.5, "desc": "size (share of the short side)"}},
         modes=["whole", "between_times", "at_time"], graph="emoji PNG (colour emoji font) + scale/fade animation overlay",
         media3={"status": "mapped", "how": "lottie-android LottieDrawable → BitmapOverlay frames (NOT TESTED)"},
         axes={"emoji": ["🔥", "❤️", "😂", "🌹"], "corner": ["top_right", "bottom_left"]}, check="sticker_shown",
         syn={"en": ["sticker", "add a sticker", "emoji sticker", "animated sticker", "add an emoji", "put an emoji", "lottie"],
              "hinglish": ["sticker lagao", "emoji lagao", "animation lagao", "sticker daalo", "dil wala sticker", "aag wala emoji", "emoji chipkao"],
              "hi": ["स्टिकर लगाओ", "इमोजी लगाओ", "एनिमेशन लगाओ"], "slang": ["fire emoji daalo"], "typos": ["stiker", "emogi", "sticer"]}),
    dict(id="countdown_timer", seed=75, name="Countdown", name_hi="Ulti ginti",
         desc="Big numbers counting down (N … 1), one per second, popping in.",
         params={"from": {"type": "integer", "default": 3, "min": 2, "max": 10, "extract": "count_from", "desc": "start number"},
                 "at": {"type": "number", "default": 0, "min": 0, "max": 36000, "unit": "s", "extract": "time_point", "desc": "when"},
                 "size": {"type": "integer", "default": 180, "min": 60, "max": 400, "desc": "size"},
                 "color": {"type": "color", "default": "#FFFFFF", "extract": "color", "desc": "colour"}},
         modes=["whole", "between_times"], graph="ASS text per second (pop)", media3={"status": "mapped", "how": "TextOverlay per number"},
         axes={"from": ["3", "5", "10"]}, check="countdown_shows",
         syn={"en": ["countdown", "count down", "timer", "3 2 1", "countdown timer", "count from 5", "countdown numbers"],
              "hinglish": ["ulti ginti", "countdown lagao", "timer lagao", "3 2 1 karo", "ginti dikhao", "ulta ginna", "countdown chalao"],
              "hi": ["उलटी गिनती", "काउंटडाउन", "टाइमर लगाओ"], "slang": ["rocket launch wala"], "typos": ["countdwn", "count dwon", "timr"]}),
]

EX = {
    "glitch": [("add a glitch effect", "en", None), ("glitch from 1 to 3 seconds", "en", {"_time": {"start": 1, "end": 3}}), ("ग्लिच लगाओ", "hi", None),
               ("glitch lagao", "hinglish", None), ("beat pe glitch karo", "hinglish", {"_time": {"mode": "at_beats"}}), ("glich effect", "typo", None),
               ("video thoda kharab sa dikhe", "vague", None), ("glitch aur rgb split", "multi", {"_also": ["rgb_split"]})],
    "vhs_retro": [("vhs effect", "en", None), ("90s camcorder look", "en", None), ("पुरानी कैसेट जैसा", "hi", None), ("vhs lagao", "hinglish", None),
                  ("purani shaadi ki video jaisa banao", "hinglish", None), ("vsh effect", "typo", None), ("nostalgia wala camera", "vague", None),
                  ("vhs aur grain", "multi", {"_also": ["film_grain"]})],
    "rgb_split": [("rgb split", "en", None), ("chromatic aberration on the drop", "en", None), ("रंग अलग अलग करो", "hi", None),
                  ("rgb split lagao", "hinglish", None), ("rang khiske hue dikhao", "hinglish", None), ("rbg split", "typo", None),
                  ("3d jaisa rang", "vague", None), ("rgb split aur shake", "multi", {"_also": ["shake"]})],
    "flash": [("white flash at every cut", "en", {"_time": {"mode": "on_scene_change"}}), ("flash at 2 seconds", "en", {"_time": {"mode": "at_time", "at": 2}}),
              ("सफ़ेद चमक लगाओ", "hi", None), ("beat pe flash", "hinglish", {"_time": {"mode": "at_beats"}}), ("har cut pe chamak", "hinglish", None),
              ("flsh", "typo", None), ("paparazzi jaisa", "vague", None), ("flash aur punch zoom", "multi", {"_also": ["punch_in"]})],
    "light_leak": [("add a light leak", "en", None), ("pink light leak at the start", "en", {"color": "#FF2D92"}), ("लाइट लीक लगाओ", "hi", None),
                   ("roshni ka leak lagao", "hinglish", None), ("film burn wala effect", "hinglish", None), ("lite leak", "typo", None),
                   ("sapne jaisi roshni", "vague", None), ("light leak aur warm", "multi", {"_also": ["warm"]})],
    "mirror_effect": [("mirror effect", "en", None), ("kaleidoscope", "en", {"axis": "both"}), ("आईना इफ़ेक्ट", "hi", None),
                      ("dono taraf same karo", "hinglish", None), ("upar neeche mirror", "hinglish", {"axis": "v"}), ("miror", "typo", None),
                      ("trippy sa banao", "vague", None), ("mirror aur slow motion", "multi", {"_also": ["slow_motion"]})],
    "pixelate_censor": [("pixelate the face", "en", {"region": "face"}), ("mosaic the top right corner", "en", {"region": "top_right"}),
                        ("चेहरा छुपाओ", "hi", None), ("number plate chhupao", "hinglish", None), ("pixel kar do neeche wala hissa", "hinglish", {"region": "bottom"}),
                        ("pixlate", "typo", None), ("pehchaan na aaye", "vague", None), ("chehra chhupao aur mute", "multi", {"_also": ["mute"]})],
    "blur_box_censor": [("blur out the logo in the corner", "en", None), ("blur this part 2 to 4 seconds", "en", {"_time": {"start": 2, "end": 4}}),
                        ("यह हिस्सा धुंधला करो", "hi", None), ("naam chhupa do blur se", "hinglish", None), ("logo blur karo", "hinglish", None),
                        ("blurbox", "typo", None), ("ye dikhna nahi chahiye", "vague", None), ("blur box aur captions", "multi", {"_also": ["auto_captions"]})],
    "shape_highlight": [("circle this", "en", None), ("add an arrow pointing at the top right", "en", {"shape": "arrow", "region": "top_right"}),
                        ("यहाँ गोला लगाओ", "hi", None), ("circle lagao", "hinglish", None), ("teer lagao yahan", "hinglish", {"shape": "arrow"}),
                        ("circel lagao", "typo", None), ("yahan dhyan jaye", "vague", None), ("arrow aur zoom", "multi", {"_also": ["zoom_in"]})],
    "sticker_lottie": [("add a fire sticker", "en", None), ("heart emoji in the top left", "en", {"position": "top_left"}),
                       ("स्टिकर लगाओ", "hi", None), ("emoji lagao 😂", "hinglish", {"emoji": "😂"}), ("dil wala sticker daalo", "hinglish", None),
                       ("stiker", "typo", None), ("thoda fun daalo", "vague", None), ("sticker aur music", "multi", {"_also": ["add_music"]})],
    "countdown_timer": [("add a countdown", "en", None), ("count down from 5", "en", {"from": 5}), ("उलटी गिनती दिखाओ", "hi", None),
                        ("3 2 1 karo", "hinglish", {"from": 3}), ("10 se ulti ginti", "hinglish", {"from": 10}), ("countdwn", "typo", None),
                        ("rocket launch jaisa", "vague", None), ("countdown aur flash", "multi", {"_also": ["flash"]})],
}
NEG = {"glitch": ["glitch mat karo"], "vhs_retro": ["vhs mat lagao"], "rgb_split": ["rgb split mat karo"], "flash": ["flash mat karo"],
       "light_leak": ["light leak mat lagao"], "mirror_effect": ["mirror mat karo"], "pixelate_censor": ["pixelate mat karo"],
       "blur_box_censor": ["blur box mat lagao"], "shape_highlight": ["circle mat lagao"], "sticker_lottie": ["sticker mat lagao"],
       "countdown_timer": ["countdown mat lagao"]}
TESTS = {
    "glitch": {"check": "differs_in_window", "params": {"intensity": 1.5}, "time": WINDOW},
    "vhs_retro": {"check": "differs_in_window", "params": {"intensity": 1.0}, "time": WINDOW},
    "rgb_split": {"check": "channels_apart", "params": {"amount": 2.0}, "time": WINDOW},
    "flash": {"check": "flash_peaks", "time": {"mode": "at_time", "at": 2.0}},
    "light_leak": {"check": "warm_glow", "time": WINDOW},
    "mirror_effect": {"check": "mirrored", "params": {"axis": "h"}, "time": WINDOW},
    "pixelate_censor": {"check": "censored_pixelate", "params": {"region": "bottom_right", "strength": 1.5}, "time": WINDOW,
                        "note": "bottom right: the test picture's textured checkerboard (a flat area cannot show blocks)"},
    "blur_box_censor": {"check": "censored_blur", "params": {"region": "bottom_right", "strength": 1.5}, "time": WINDOW},
    "shape_highlight": {"check": "shape_drawn", "params": {"shape": "ring", "region": "center"}, "time": WINDOW},
    "sticker_lottie": {"check": "sticker_shown", "params": {"emoji": "🔥", "position": "top_right"}, "time": WINDOW},
    "countdown_timer": {"check": "countdown_shows", "params": {"from": 3, "at": 1.0}},
}


def main() -> None:
    for s in SKILLS:
        examples = []
        for prompt, lang, extra in EX[s["id"]]:
            e: dict = {"prompt": prompt, "lang": lang}
            extra = dict(extra or {})
            if "_also" in extra:
                e["also"] = extra.pop("_also")
            if "_time" in extra:
                e["time"] = extra.pop("_time")
            if extra:
                e["params"] = extra
            examples.append(e)
        doc = {
            "id": s["id"], "seed": s["seed"], "category": "stylize", "name": s["name"], "name_hi": s["name_hi"],
            "description": s["desc"], **({"same_engine_as": s["same"]} if "same" in s else {}),
            "params": s["params"], "time_modes": s["modes"], "builder": f"stylize.{s['id']}", "graph": s["graph"],
            "media3": s["media3"], "stage": "effect" if s["id"] in ("glitch", "vhs_retro", "rgb_split", "flash", "mirror_effect") else "overlay",
            "conflicts": [], "cost": "medium" if s["id"] in ("pixelate_censor", "blur_box_censor") else "cheap",
            "licence": "own code; FFmpeg filters (server process); shapes drawn with Pillow (MIT-CMU); emoji font: Noto Color Emoji (OFL) on the server",
            "changes_duration": False, "needs": ["faces"] if s["id"] in ("pixelate_censor", "blur_box_censor") else [],
            "variant_axes": s["axes"], "synonyms": s["syn"], "negations": NEG[s["id"]], "examples": examples, "test": TESTS[s["id"]],
        }
        (OUT / f"{s['id']}.yaml").write_text("# written by skills/tools/write_tier1_stylize.py — edit this file directly from now on\n"
                                             + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
        print(s["id"])


if __name__ == "__main__":
    main()
