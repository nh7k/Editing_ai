"""Prompt coach: rough Hinglish / desi wording → one clean English prompt the agents follow exactly.

"starting ki 3s me zoom ho phir zoom out, base ki tarah effect" becomes
"Zoom in for the first 3 seconds. Zoom out after 3 seconds. Bass boost. Add upbeat music. Sync to the beat."

The app shows this to the user ("Maine ye samjha") and sends it instead of the raw text. It is built from the
same deterministic parser the Director uses, and every sentence is worded so that parsing it again gives the
same edit (tests/unit/test_coach.py checks that round trip), so nothing is lost or invented on the way.
Instant: no model call.
"""

from __future__ import annotations

import re

from .fx_catalog import EFFECTS_BY_ID, LUT_LOOKS, TRANSITIONS_BY_ID
from .intent import Intent, describe_timed, parse_intent
from .memory import wants_my_style, wants_repeat
from .text_styles import COLOR_WORDS, TEXT_PRESETS

_COLOR = {"warm": "warm color", "cool": "cool color", "cinematic": "cinematic color", "bw": "black and white",
          "sepia": "sepia color", "vintage": "vintage color", "vivid": "vivid color"}
_ANIM = {"fade": "faded text", "pop": "pop text", "slide_up": "slide up text", "typewriter": "typewriter text",
         "bounce": "bouncy text", "karaoke": "karaoke captions", "zoom_in": "zoom in text", "zoom_out": "zoom out text",
         "spin_in": "spinning text", "flip_in": "flip text", "blur_in": "blur in text", "drop_in": "dropping text",
         "fly_left": "text flies in from the left", "fly_right": "text flies in from the right", "swing": "swinging text",
         "shake": "shaky text", "heartbeat": "heartbeat text", "flicker": "flickering text", "glow_pulse": "glowing pulse",
         "color_cycle": "rainbow text", "wave": "wavy text", "cascade": "letter by letter text", "stretch": "stretchy text"}
_STYLE = {"midnight_drift": "midnight drift look", "violet_authority": "violet authority look", "cyan_kinetic": "cyan kinetic look"}
_ROTATE = {90: "Rotate 90 degrees clockwise.", 180: "Turn it upside down.", 270: "Rotate counterclockwise."}
_FLIP = {"h": "Mirror it.", "v": "Flip it vertically.", "hv": "Mirror it. Flip it vertically."}


def _fx_name(effect: str) -> str:
    fx = EFFECTS_BY_ID.get(effect)
    return fx.name.lower() if fx else effect.replace("_", " ")


def solid_prompt(it: Intent, original: str = "") -> str:
    """English sentences for everything in `it`. Empty string when nothing was understood."""
    s: list[str] = []
    if original and wants_repeat(original):
        s.append("Same as before.")
    if original and wants_my_style(original):
        s.append("In my style.")
    if it.auto:
        s.append("Auto edit: you decide everything else.")
    if it.order == "smart":
        s.append("Arrange the clips in the right order.")
    elif it.order == "reverse":
        s.append("Reverse order.")
    elif it.order == "best":
        s.append("Best moments first.")
    if it.target_duration:
        s.append(f"Make it {it.target_duration:g} seconds long.")
    if it.aspect_ratio:
        s.append({"9:16": "9:16 vertical.", "1:1": "1:1 square.", "16:9": "16:9 landscape."}[it.aspect_ratio])
    if it.resolution:
        s.append(f"{it.resolution}p.")
    if it.color_preset:
        look = LUT_LOOKS.get(it.color_preset)
        s.append(f"{look[0].lower().replace('&', 'and')} look." if look else f"{_COLOR[it.color_preset]}.")
    if it.brightness > 0:
        s.append("Make it brighter.")
    elif it.brightness < 0:
        s.append("Make it darker.")
    if it.gamma != 1.0:
        s.append(f"Gamma {it.gamma:g}.")
    if it.remove_silence:
        s.append("Remove silences.")
    if it.remove_fillers:
        s.append("Remove filler words.")
    if it.remove_idle:
        s.append("Remove idle parts.")
    if it.fast_cuts:
        s.append("Fast cuts.")
    if it.slow_motion:
        s.append("Slow motion.")
    for e in it.effects:
        if e == "pulse" and it.bass_boost:
            continue
        s.append({"speed_ramp": "Speed ramp.", "blur_background": "Blur the background.",
                  "film_bw": "Old movie black and white look."}.get(e, f"{_fx_name(e)} effect."))
    for t in it.timed_effects:
        s.append(describe_timed(t)[0].upper() + describe_timed(t)[1:] + ".")
    if it.bass_boost:
        s.append("Bass boost.")
    if it.transition:
        tr = TRANSITIONS_BY_ID.get(it.transition)
        s.append(f"{tr.name.lower() if tr else it.transition} transitions.")
    if it.captions:
        s.append("Add captions.")
    if it.text_animation != "none":
        s.append(f"{_ANIM[it.text_animation]}.")
    if it.text_style:
        s.append(f"{TEXT_PRESETS[it.text_style].name.lower()} text style.")
    if it.text_color:
        word = next(k for k, v in COLOR_WORDS.items() if v == it.text_color)
        s.append(f"{word} text.")
    if it.track_target == "face":
        s.append("Target: face.")
    if it.tracked_text:
        s.append(f'Text "{it.tracked_text}" follows the person.')
    if it.focus:
        who = (f"the person in {next(k for k, v in COLOR_WORDS.items() if v == it.track_color)} shirt"
               if it.track_color else "the main person")
        s.append(f"Focus on {who}, blur the rest." if it.focus == "blur" else f"Focus on {who}.")
    if it.text_front:
        s.append("Keep the text in front of the person.")
    elif it.captions_behind:
        s.append("Captions behind the person.")
    elif it.text_behind:
        s.append("Text behind the person.")
    if it.slow_end:
        s.append("Slow motion at the end.")
    if it.use_reference:
        s.append("Edit it like the reference video.")
    if it.lyrics:
        s.append("Show the lyrics as text.")
    if it.use_my_song:
        s.append("Use my song.")
    if it.voice_boost:
        s.append("Boost the voice.")
    if it.music_volume is not None:
        s.append("Low background music." if it.music_volume < 0.3 else "Loud music.")
    if it.title:
        s.append(f'Title "{it.title}".')
    if it.watermark:
        s.append(f'Watermark "{it.watermark}".')
    if it.mute:
        s.append("Mute the original sound.")
    if it.restore_audio:
        s.append("Bring the sound back (unmute, normal level; the earlier song if the clips have no sound).")
    if it.pace_change:
        s.append("Slower pace, longer shots." if it.pace_change > 1 else "Faster pace, shorter shots.")
    if it.length_change:
        s.append("Make it shorter." if it.length_change < 1 else "Make it longer.")
    if it.drop_clips:
        names = {1: "first", 2: "second", 3: "third", 4: "fourth", -1: "last"}
        s.append("Leave out the " + " and ".join(names.get(k, f"#{k}") for k in it.drop_clips) + " clip.")
    if it.word_stickers:
        s.append("When something is named in the talking (a rose, a tree, chai…), pop up its sticker at that moment.")
    if it.end_text:
        s.append(f'Closing text "{it.end_text}" on the last seconds.')
    if it.restore_color:
        s.append("Original colours back (no black & white, no grade).")
    if it.text_scale:
        s.append("Bigger text." if it.text_scale > 1 else "Smaller text.")
    if it.no_music:
        s.append("No music.")
    if it.music:
        s.append(f"Add {it.music_mood + ' ' if it.music_mood else ''}music." if it.music_mood or not it.music_volume
                 else "Music level changed.")
    if it.beat_sync:
        s.append("Sync to the beat.")
    if it.voice_cleanup:
        s.append("Clean up the audio.")
    if it.loudness != "normal":
        s.append("Make it louder." if it.loudness == "louder" else "Make it quieter.")
    if it.audio_fade:
        s.append("Fade in and out the audio.")
    if it.rotate:
        s.append(_ROTATE[it.rotate])
    if it.flip != "none":
        s.append(_FLIP[it.flip])
    if it.reverse_playback:
        s.append("Play the video backwards.")
    if it.fps:
        s.append(f"{it.fps} fps.")
    if it.style:
        s.append(f"{_STYLE[it.style]}.")
    if it.variations > 1:
        s.append(f"{it.variations} versions.")
    if it.export_gif:
        s.append("Export a GIF.")
    if it.export_mp3:
        s.append("Export an MP3.")
    s += [{"captions": "Remove the captions.", "transition": "Remove the transitions.",
           "effects": "Remove the effects."}[f] for f in it.remove]
    implied = {"mono", "silhouette", "invert_mono", "film_bw"} if "bw" in it.avoid else set()
    if "zoom" in it.avoid:
        implied |= {"pulse", "punch", "impact", "drift"}
    for a in it.avoid:  # what the user said NOT to do
        if a in implied:
            continue
        s.append({"bw": "No black and white.", "text": "No text on screen.", "slow_motion": "No slow motion."}.get(
            a, f"No {_fx_name(a)}."))
    text = " ".join(x[0].upper() + x[1:] for x in s)
    return text


def understand(prompt: str, analysis: object = None, has_edit: bool = False) -> dict[str, object]:
    """What the app shows before an edit runs: the clean prompt, and the professional edit spec
    (what you said / what the editor will infer and why / what is still unknown)."""
    from .editorial import apply_spec, compile_spec, wants_editorial
    from .memory import is_follow_up, wants_repeat

    it = parse_intent(prompt)
    solid = solid_prompt(it, prompt)
    base = {"solid_prompt": solid or prompt, "understood": it.recognized, "changed": bool(solid) and solid != prompt,
            "auto": it.auto}
    if has_edit and (wants_repeat(prompt) or it.remove or is_follow_up(prompt, it)):
        # a change to the edit that is there: the brief says what changes — not a whole new edit the agents
        # won't make (that brief was misleading in the app)
        change = "The same edit as last time." if wants_repeat(prompt) else (solid or "")
        return {**base, "spec": None,
                "pro_brief": f"Change to your current edit: {change} Everything else stays as it is.".replace("  ", " ")}
    compiled = compile_spec(prompt, it, analysis) if wants_editorial(prompt, it) else None
    spec = compiled.to_dict() if compiled else None
    final = apply_spec(it, compiled) if compiled else it
    if final.auto and analysis is not None:
        # what the agents will really choose for THIS footage (pace, music, length), not a generic guess
        from types import SimpleNamespace

        from .agents.director import autopilot

        final = autopilot(SimpleNamespace(analysis=analysis, prompt=prompt), final)  # type: ignore[arg-type]
    return {**base, "spec": spec, "pro_brief": pro_brief(final, spec)}


def pro_brief(it: Intent, spec: dict | None) -> str:
    """The whole edit as a professional brief: what the user said PLUS what the editorial brain decided."""
    head = []
    if spec and spec.get("genres"):
        name = spec["genres"][0]["name"]
        head.append(name if name.lower().endswith("edit") else f"{name} edit")
    if spec and spec.get("platform"):
        head.append(f"for {spec['platform']['name']}")
    if it.aspect_ratio:
        head.append(it.aspect_ratio)
    if head and head[0].startswith("for "):
        head.insert(0, "Edit")  # "for Instagram Reels 9:16." read like a broken sentence
    s = [" ".join(head) + "." if head else ""]
    if it.auto:
        s.append("The editor picks music, pace and effects from your footage.")
    if it.hook_first:
        s.append("Open on the strongest moment.")
    if it.beat_sync and it.fast_cuts:
        s.append(f"Cut on the beat, about {it.cut_length or 1.0:g}s per shot.")
    elif it.fast_cuts:
        s.append("Fast cuts.")
    elif it.cut_length and it.cut_length >= 2:
        s.append(f"Let shots breathe, about {it.cut_length:g}s each.")
    body = [x for x in re.findall(r"[^.]+\.", solid_prompt(it)) if not x.strip().startswith(("Auto edit", "Sync to the beat",
                                                                                            "9:16", "16:9", "1:1"))]
    skip = set()
    if it.beat_sync and it.fast_cuts:
        skip.add("Fast cuts.")
    if it.speed_moves:
        skip.add("Speed ramp.")
    if it.kinetic_text:
        skip.add("Text behind the person.")
    s += [x.strip() for x in body if x.strip() not in skip]
    if it.color_pass:
        s.append("Some shots in old-movie black and white, never two in a row.")
    if it.kinetic_text:
        words = " / ".join(it.kinetic_words) if it.kinetic_words else "lyrics"
        s.append(f'Big "{words}" titles on the beat' + (", behind the person." if it.text_behind else "."))
    if it.speed_moves:
        s.append("A stutter on a loud moment and a speed ramp into the drop.")
    if it.impact_hits:
        s.append("Zoom-blur hits on the strongest cuts.")
    if it.flash_accents:
        s.append("White flash on the biggest moments.")
    if it.ending_peak:
        s.append("End on the biggest moment.")
    if it.target_lufs:
        s.append(f"Loudness {it.target_lufs:g} LUFS for social.")
    out = []
    for x in s:
        if x and x not in out:
            out.append(x)
    return " ".join(out)
