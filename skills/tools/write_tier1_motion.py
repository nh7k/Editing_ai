"""One-time writer of the 11 motion / time Tier 1 specs (skills/tier1/<id>.yaml). The data below is hand-written;
after writing, the YAML files are the source of truth.

    backend/.venv/Scripts/python.exe skills/tools/write_tier1_motion.py
"""

from __future__ import annotations

from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parents[1] / "tier1"
VIDEO_MODES = ["whole", "segment", "between_times", "intermittent"]
WINDOW = {"mode": "between_times", "start": 1.0, "end": 3.0}
EASE = {"type": "choice", "choices": ["linear", "ease_in_out", "ease_out", "back", "spring", "bounce"],
        "default": "ease_in_out", "desc": "how the move eases"}
MEDIA3_MOVE = {"status": "mapped", "how": "MatrixTransformation whose matrix is the same eased keyframes per frame",
               "reason": "NOT TESTED on a device"}

SKILLS = [
    dict(id="zoom_in", seed=26, name="Zoom in", name_hi="Paas lao",
         description="A gradual zoom in (1 → 1+amount) over the whole video or a part, with an easing.",
         params={"amount": {"type": "number", "default": 0.15, "min": 0.03, "max": 0.6, "extract": "magnitude", "desc": "how far"},
                 "easing": EASE},
         modes=VIDEO_MODES, graph="zoompan-free keyframed scale+crop (camera_move.replay_filters with easing)",
         media3=MEDIA3_MOVE, stage="geometry", conflicts=["zoom_out"], cd=False,
         axes={"amount": ["0.08", "0.15", "0.3"], "easing": ["linear", "ease_in_out", "spring", "bounce"]},
         syn={"en": ["zoom in", "push in", "slow zoom", "zoom into", "get closer", "dolly in", "zoom effect"],
              "hinglish": ["paas lao", "dheere zoom", "zoom karo", "andar le jao", "zoom in karo", "kareeb lao", "zoom daalo"],
              "hi": ["ज़ूम इन", "पास लाओ", "ज़ूम करो"], "slang": ["camera andar ghusao"], "typos": ["zoomin", "zom in", "zoom inn"]},
         neg=["zoom mat lagao", "zoom mat karo", "bina zoom"],
         ex=[("zoom in slowly", "en", None), ("zoom in from 2 to 5 seconds", "en", {"_time": {"start": 2, "end": 5}}),
             ("ज़ूम इन करो", "hi", None), ("thoda zoom karo", "hinglish", {"amount": 0.075}),
             ("bahut zoom karo end me", "hinglish", {"amount": 0.24}), ("zom in pls", "typo", None),
             ("chehre ke paas jao", "vague", None), ("zoom in karo aur warm color", "multi", {"_also": ["warm"]})],
         test={"check": "scale_increases", "params": {"amount": 0.3, "easing": "linear"}, "time": WINDOW}),
    dict(id="zoom_out", seed=27, name="Zoom out", name_hi="Door karo", same_engine_as="zoom_in",
         description="A gradual zoom out (1+amount → 1).",
         params={"amount": {"type": "number", "default": 0.15, "min": 0.03, "max": 0.6, "extract": "magnitude", "desc": "how far"},
                 "easing": EASE},
         modes=VIDEO_MODES, graph="keyframed scale+crop", media3=MEDIA3_MOVE, stage="geometry", conflicts=["zoom_in"], cd=False,
         axes={"amount": ["0.08", "0.15", "0.3"], "easing": ["linear", "ease_in_out", "bounce"]},
         syn={"en": ["zoom out", "pull out", "pull back", "reveal", "zoom back", "dolly out", "wider"],
              "hinglish": ["door karo", "peeche jao", "zoom out karo", "door se dikhao", "camera peeche", "bahar ki taraf zoom", "poora dikhao dheere"],
              "hi": ["ज़ूम आउट", "पीछे हटाओ", "दूर करो"], "slang": ["reveal shot"], "typos": ["zoomout", "zom out", "zoom aut"]},
         neg=["zoom out mat karo"],
         ex=[("zoom out at the end", "en", {"_time": {"mode": "between_times"}}), ("pull back slowly", "en", None),
             ("ज़ूम आउट करो", "hi", None), ("zoom out karo", "hinglish", None), ("dheere dheere door karo", "hinglish", None),
             ("zom out", "typo", None), ("poora scene dikhao", "vague", None), ("zoom out aur fade out", "multi", {"_also": ["fade_black"]})],
         test={"check": "scale_decreases", "params": {"amount": 0.3, "easing": "linear"}, "time": WINDOW}),
    dict(id="punch_in", seed=28, name="Punch in", name_hi="Jhatka zoom",
         description="A quick zoom hit (to `scale`) that eases back, on beats, words, cuts or given times.",
         params={"scale": {"type": "number", "default": 1.2, "min": 1.05, "max": 1.28, "extract": "level", "desc": "how far"}},
         modes=["whole", "at_time", "at_beats", "on_words", "on_scene_change", "intermittent"],
         graph="scale with a per-frame bump expression + crop", media3=MEDIA3_MOVE, stage="geometry", conflicts=[], cd=False,
         axes={"scale": ["1.1", "1.2", "1.28"], "on": ["beats", "words", "cuts"]},
         syn={"en": ["punch in", "punch zoom", "zoom hit", "quick zoom", "snap zoom", "impact zoom", "jump zoom"],
              "hinglish": ["jhatka zoom", "beat par zoom", "jhatke se zoom", "fatak se zoom", "punch karo", "zoom ka jhatka", "dhak se zoom"],
              "hi": ["झटका ज़ूम", "पंच ज़ूम", "झटके से ज़ूम"], "slang": ["dhamaka zoom"], "typos": ["punchin", "panch zoom", "punch inn"]},
         neg=["punch mat karo", "jhatka mat do"],
         ex=[("punch in on every beat", "en", {"_time": {"mode": "at_beats"}}), ("punch zoom at 3 seconds", "en", {"_time": {"mode": "at_time", "at": 3}}),
             ("झटका ज़ूम लगाओ", "hi", None), ("har cut pe jhatka zoom", "hinglish", {"_time": {"mode": "on_scene_change"}}),
             ("beat par zoom karo", "hinglish", {"_time": {"mode": "at_beats"}}), ("punchin", "typo", None),
             ("thoda energy daalo zoom se", "vague", None), ("punch in aur flash", "multi", {"_also": ["flash"]})],
         test={"check": "punch_at_times", "params": {"scale": 1.25}, "time": {"mode": "at_time", "at": 2.0}}),
    dict(id="ken_burns", seed=29, name="Ken Burns", name_hi="Photo animate karo",
         description="Slow pan + zoom (meant for photos; works on video too). direction: in, out, left, right, up, down.",
         params={"direction": {"type": "choice", "choices": ["in", "out", "left", "right", "up", "down"], "default": "in",
                               "extract": "direction", "desc": "where it drifts"},
                 "amount": {"type": "number", "default": 0.2, "min": 0.05, "max": 0.5, "extract": "magnitude", "desc": "how far"}},
         modes=VIDEO_MODES, graph="keyframed scale + translate (linear)", media3=MEDIA3_MOVE, stage="geometry",
         conflicts=["zoom_in", "zoom_out"], cd=False, axes={"direction": ["in", "out", "left", "right"], "amount": ["0.1", "0.2", "0.35"]},
         syn={"en": ["ken burns", "animate the photo", "slow pan and zoom", "photo motion", "pan and zoom", "documentary zoom", "move the still"],
              "hinglish": ["photo ko hilao", "photo animate karo", "photo me motion", "photo pe ken burns", "tasveer chalao", "photo dheere zoom", "still ko move karo"],
              "hi": ["फोटो एनिमेट करो", "केन बर्न्स", "तस्वीर चलाओ"], "slang": ["photo me jaan daalo"], "typos": ["ken burn", "kenburns", "ken barns"]},
         neg=["ken burns mat lagao"],
         ex=[("add a ken burns effect", "en", None), ("ken burns to the right", "en", {"direction": "right"}),
             ("फोटो एनिमेट करो", "hi", None), ("photo animate karo", "hinglish", None), ("photo pe ken burns left me", "hinglish", {"direction": "left"}),
             ("ken burn", "typo", None), ("photos boring lag rahi hain", "vague", None),
             ("ken burns aur music", "multi", {"_also": ["add_music"]})],
         test={"check": "scale_increases", "params": {"direction": "in", "amount": 0.3}, "time": WINDOW}),
    dict(id="pan", seed=30, name="Pan", name_hi="Side me sarkao",
         description="The frame slides left / right / up / down over time.",
         params={"direction": {"type": "choice", "choices": ["left", "right", "up", "down"], "default": "right",
                               "extract": "direction", "desc": "direction"},
                 "speed": {"type": "number", "default": 1.0, "min": 0.3, "max": 3.0, "extract": "magnitude", "desc": "how far"}},
         modes=VIDEO_MODES, graph="scale up + crop with x(t) / y(t)", media3=MEDIA3_MOVE, stage="geometry", conflicts=[], cd=False,
         axes={"direction": ["left", "right", "up", "down"], "speed": ["slow", "normal", "fast"]},
         syn={"en": ["pan", "pan left", "pan right", "slide the frame", "camera pan", "move sideways", "tilt up"],
              "hinglish": ["side me sarkao", "left right ghumao", "pan karo", "camera ghumao side", "daaye sarkao", "baaye le jao", "upar le jao camera"],
              "hi": ["पैन करो", "बगल में सरकाओ", "कैमरा घुमाओ"], "slang": ["camera chalao side"], "typos": ["pann", "pan rite", "paan karo"]},
         neg=["pan mat karo"],
         ex=[("pan right", "en", {"direction": "right"}), ("slow pan to the left", "en", {"direction": "left"}),
             ("कैमरा बाएँ पैन करो", "hi", None), ("left right ghumao", "hinglish", None), ("daaye sarkao", "hinglish", {"direction": "right"}),
             ("pann left", "typo", {"direction": "left"}), ("thoda camera chalao", "vague", None),
             ("pan karo aur zoom in", "multi", {"_also": ["zoom_in"]})],
         test={"check": "pans", "params": {"direction": "right", "speed": 1.5}}),
    dict(id="shake", seed=31, name="Camera shake", name_hi="Hilao",
         description="Handheld / earthquake shake.",
         params={"intensity": {"type": "number", "default": 1.0, "min": 0.3, "max": 3.0, "extract": "magnitude", "desc": "how strong"}},
         modes=["whole", "segment", "between_times", "intermittent", "at_beats"],
         graph="crop with sin/cos offsets + scale back", media3=MEDIA3_MOVE, stage="geometry", conflicts=[], cd=False,
         axes={"intensity": ["light", "normal", "strong"]},
         syn={"en": ["shake", "camera shake", "earthquake effect", "shaky cam", "handheld look", "screen shake", "rumble"],
              "hinglish": ["hilao", "jhatke do", "video hilao", "shake karo", "bhukamp wala", "hilta hua", "screen hila do"],
              "hi": ["हिलाओ", "झटके दो", "भूकंप जैसा"], "slang": ["dhamaal shake"], "typos": ["shak", "sheke", "shaek"]},
         neg=["shake mat karo", "mat hilao"],
         ex=[("add camera shake", "en", None), ("shake on the beat drop", "en", None), ("स्क्रीन हिलाओ", "hi", None),
             ("thoda shake daal do", "hinglish", {"intensity": 0.5}), ("bahut zor se hilao", "hinglish", {"intensity": 1.6}),
             ("sheke effect", "typo", None), ("dhamake wali feel", "vague", None), ("shake aur flash", "multi", {"_also": ["flash"]})],
         test={"check": "jitters", "params": {"intensity": 2.0}, "time": WINDOW}),
    dict(id="speed_up", seed=32, name="Speed up", name_hi="Tez karo",
         description="Faster playback (factor x), picture and sound, for the whole video or a part.",
         params={"factor": {"type": "number", "default": 2.0, "min": 1.1, "max": 4.0, "extract": "multiplier", "desc": "how much faster"}},
         modes=VIDEO_MODES, graph="setpts / atempo per segment", media3={"status": "mapped", "how": "EditedMediaItem.setSpeed / SpeedChangeEffect"},
         stage="time", conflicts=["slow_motion"], cd=True, axes={"factor": ["1.5x", "2x", "3x"]},
         syn={"en": ["speed up", "faster", "fast forward", "2x speed", "timelapse", "make it quicker", "double speed"],
              "hinglish": ["tez karo", "jaldi chalao", "fast karo", "speed badhao", "2x kar do", "tezi se chalao", "fatafat chalao"],
              "hi": ["तेज़ करो", "जल्दी चलाओ", "स्पीड बढ़ाओ"], "slang": ["bullet train speed", "slow lag raha hai"], "typos": ["speedup", "fast kro", "spead up"]},
         neg=["speed mat badhao", "fast mat karo"],
         ex=[("speed it up 2x", "en", {"factor": 2.0}), ("fast forward from 2 to 5 sec", "en", {"_time": {"start": 2, "end": 5}}),
             ("तेज़ करो", "hi", None), ("video jaldi chalao", "hinglish", None), ("3x kar do", "hinglish", {"factor": 3.0}),
             ("spead up", "typo", None), ("bahut slow lag raha hai", "vague", None),
             ("2x speed aur music", "multi", {"factor": 2.0, "_also": ["add_music"]})],
         test={"check": "faster", "params": {"factor": 2.0}, "time": WINDOW}),
    dict(id="slow_motion", seed=33, name="Slow motion", name_hi="Dheema karo",
         description="Slower playback (factor < 1), picture and sound (pitch kept), for the whole video or a part.",
         params={"factor": {"type": "number", "default": 0.5, "min": 0.25, "max": 0.9, "extract": "multiplier", "desc": "speed (0.5 = half)"}},
         modes=VIDEO_MODES, graph="setpts / atempo per segment", media3={"status": "mapped", "how": "SpeedChangeEffect(factor)"},
         stage="time", conflicts=["speed_up"], cd=True, axes={"factor": ["0.75x", "0.5x", "0.25x"]},
         syn={"en": ["slow motion", "slow mo", "slomo", "slow down", "half speed", "slower", "slow-mo"],
              "hinglish": ["dheema karo", "slow motion me chalao", "dheere chalao", "slow karo", "aahista chalao", "slow mo kar do", "dheere dheere chalao"],
              "hi": ["धीमा करो", "स्लो मोशन", "धीरे चलाओ"], "slang": ["matrix wala slow", "quarter speed", "aadhi speed"], "typos": ["slow motin", "slowmo", "slo mo"]},
         neg=["slow mat karo", "slow motion nahi"],
         ex=[("slow motion at the end", "en", {"_time": {"mode": "between_times"}}), ("quarter speed", "en", None),
             ("स्लो मोशन कर दो", "hi", None), ("slow mo kar do", "hinglish", None), ("aadhi speed pe chalao", "hinglish", {"factor": 0.5}),
             ("slow motin", "typo", None), ("dramatic sa dikhe", "vague", None),
             ("slow motion aur black and white", "multi", {"_also": ["grayscale"]})],
         test={"check": "slower", "params": {"factor": 0.5}, "time": WINDOW}),
    dict(id="speed_ramp", seed=34, name="Speed ramp", name_hi="Tez phir slow",
         description="Each target shot plays its first half at normal speed and its second half faster (speed_up_later) or slower (slow_down_later).",
         params={"curve": {"type": "choice", "choices": ["speed_up_later", "slow_down_later"], "default": "speed_up_later", "desc": "ramp shape"},
                 "strength": {"type": "number", "default": 2.0, "min": 1.25, "max": 3.0, "extract": "multiplier", "desc": "speed change"}},
         modes=["whole", "segment", "between_times"], graph="split + two setpts/atempo halves + concat",
         media3={"status": "mapped", "how": "SpeedProvider with two speed regions"}, stage="time", conflicts=["reverse"], cd=True,
         axes={"curve": ["speed_up_later", "slow_down_later"], "strength": ["1.5", "2", "3"]},
         syn={"en": ["speed ramp", "ramp", "fast then slow", "slow then fast", "velocity edit", "speed change", "ramp the speed"],
              "hinglish": ["tez phir slow", "slow phir tez", "speed ramp karo", "raftaar badlo", "velocity edit banao", "ramp lagao", "speed upar neeche"],
              "hi": ["तेज़ फिर धीमा", "स्पीड रैंप", "रफ़्तार बदलो"], "slang": ["velocity wala"], "typos": ["sped ramp", "speedramp", "speed rmp"]},
         neg=["ramp mat karo"],
         ex=[("add a speed ramp", "en", None), ("slow then fast", "en", None), ("स्पीड रैंप लगाओ", "hi", None),
             ("tez phir slow karo", "hinglish", None), ("velocity edit banao", "hinglish", None), ("speedramp", "typo", None),
             ("action jaisa speed", "vague", None), ("speed ramp aur beat sync", "multi", {"_also": ["beat_sync"]})],
         test={"check": "ramped", "params": {"curve": "speed_up_later", "strength": 2.0}, "time": {"mode": "segment", "index": 1}}),
    dict(id="reverse", seed=35, name="Reverse", name_hi="Ulta chalao",
         description="Play backwards (picture and sound). Whole video: last shot first. A part: those shots backwards in place.",
         params={},
         modes=["whole", "segment", "between_times"], graph="reverse / areverse per segment (≤ 10 s pieces)",
         media3={"status": "server_only", "reason": "Media3 Transformer cannot decode backwards"}, stage="time",
         conflicts=["speed_ramp"], cd=False, axes={"scope": ["whole", "one_shot", "boomerang"]},
         syn={"en": ["reverse", "play backwards", "rewind effect", "backwards", "reverse the clip", "rewind", "play it in reverse"],
              "hinglish": ["ulta chalao", "ulta kar do video", "peeche ki taraf chalao", "rewind karo", "ulti video", "reverse karo", "ulta play"],
              "hi": ["उल्टा चलाओ", "रिवर्स करो", "पीछे की तरफ़"], "slang": ["time machine wala"], "typos": ["revers", "rivers karo", "reverce"]},
         neg=["reverse mat karo", "ulta mat chalao"],
         ex=[("play it backwards", "en", None), ("reverse from 1 to 3 seconds", "en", {"_time": {"start": 1, "end": 3}}),
             ("उल्टा चलाओ", "hi", None), ("ulta chalao video", "hinglish", None), ("pehla shot reverse karo", "hinglish", None),
             ("reverce", "typo", None), ("waqt ko peeche le jao", "vague", None), ("reverse karo aur slow motion", "multi", {"_also": ["slow_motion"]})],
         test={"check": "plays_backwards", "time": {"mode": "segment", "index": 0}}),
    dict(id="freeze_frame", seed=36, name="Freeze frame", name_hi="Frame rok do",
         description="Hold the frame at `at` for `duration` seconds (the sound pauses), then continue.",
         params={"at": {"type": "number", "min": 0, "max": 36000, "unit": "s", "extract": "time_point", "required": True, "desc": "when"},
                 "duration": {"type": "number", "default": 1.5, "min": 0.3, "max": 10, "unit": "s", "extract": "seconds", "desc": "how long"}},
         modes=["whole"], graph="one frame (trim end_frame=1) + tpad clone, silent sound",
         media3={"status": "mapped", "how": "a still EditedMediaItem (frame grab) with setDurationUs"}, stage="time", conflicts=[], cd=True,
         axes={"duration": ["0.5s", "1.5s", "3s"], "with": ["plain", "flash", "zoom"]},
         syn={"en": ["freeze frame", "freeze", "hold the frame", "pause the picture", "still frame", "stop the frame", "freeze it"],
              "hinglish": ["frame rok do", "ruk jao", "yahan freeze karo", "video rok do yahan", "tasveer rok do", "frame pakad lo", "ruk jaye video"],
              "hi": ["फ्रेम रोक दो", "रुक जाओ", "फ़्रीज़ करो"], "slang": ["photo jaisa ruk jaye"], "typos": ["freez frame", "frize", "freeze fram"]},
         neg=["freeze mat karo"],
         ex=[("freeze frame at 3 seconds", "en", {"at": 3.0}), ("hold the frame at 2 sec for 2 seconds", "en", {"at": 2.0, "duration": 2.0}),
             ("3 सेकंड पर फ्रेम रोक दो", "hi", {"at": 3.0}), ("4 sec pe frame rok do", "hinglish", {"at": 4.0}),
             ("5 second par ruk jaye video", "hinglish", {"at": 5.0}), ("freez frame at 1 sec", "typo", {"at": 1.0}),
             ("jab main koodun tab ruk jaye", "vague", None), ("2 sec pe freeze aur flash", "multi", {"at": 2.0, "_also": ["flash"]})],
         test={"check": "frozen", "params": {"at": 2.0, "duration": 1.5}}),
]


def main() -> None:
    for s in SKILLS:
        examples = []
        for prompt, lang, extra in s["ex"]:
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
            "id": s["id"], "seed": s["seed"], "category": "motion", "name": s["name"], "name_hi": s["name_hi"],
            "description": s["description"], **({"same_engine_as": s["same_engine_as"]} if "same_engine_as" in s else {}),
            "params": s["params"], "time_modes": s["modes"], "builder": f"motion.{s['id']}", "graph": s["graph"],
            "media3": s["media3"], "stage": s["stage"], "conflicts": s["conflicts"],
            "cost": "medium" if s["id"] in ("reverse", "speed_ramp") else "cheap",
            "licence": "own code (engines/motion.py easings); FFmpeg filters (server process)",
            "changes_duration": s["cd"], "needs": [], "variant_axes": s["axes"], "synonyms": s["syn"],
            "negations": s["neg"], "examples": examples, "test": s["test"],
        }
        path = OUT / f"{s['id']}.yaml"
        path.write_text("# written by skills/tools/write_tier1_motion.py — edit this file directly from now on\n"
                        + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
        print(path.name)


if __name__ == "__main__":
    main()
