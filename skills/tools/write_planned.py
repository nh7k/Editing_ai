"""Writes skills/registry/planned.yaml: Tier 3 skills that are not built yet (or blocked), each saying what it needs.
Planned / blocked skills are never matched for an edit (skill_registry._index skips them)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
P = [
    ("freeze_frame", "motion", "Freeze frame", "hold one frame for N s (needs a segment-split op in the cutter)", "cheap", ["freeze frame", "pause the frame"], ["frame rok do", "yaha ruk jaye"], "own code (FFmpeg tpad/loop)", "planned"),
    ("time_remap", "motion", "Time remap curve", "arbitrary speed curve per shot (generalises speed_ramp)", "medium", ["time remap", "speed curve"], ["speed curve banao"], "own code", "planned"),
    ("bounce_loop", "motion", "Bounce loop (boomerang)", "forward + reverse loop of a short moment", "cheap", ["boomerang", "bounce loop"], ["boomerang banao"], "own code", "planned"),
    ("parallax", "motion", "Parallax (2.5D)", "needs a depth / person mask per frame; heavy on CPU", "heavy", ["parallax", "2.5d effect"], ["3d jaisa photo"], "would use PP-HumanSeg (Apache-2.0)", "planned"),
    ("stabilize", "motion", "Stabilize", "vidstab two-pass (our FFmpeg build has libvidstab, GPL build: server only)", "medium", ["stabilize", "remove shake", "steady"], ["hilna band karo", "stable karo"], "FFmpeg vidstab (GPL build, server-only)", "planned"),
    ("split_screen", "structure", "Split screen", "two clips side by side / top-bottom", "medium", ["split screen", "side by side"], ["do video ek saath"], "own code (FFmpeg hstack/vstack)", "planned"),
    ("picture_in_picture", "structure", "Picture in picture", "a second clip small in a corner", "medium", ["picture in picture", "pip"], ["chhoti window me dusra video"], "own code (FFmpeg overlay)", "planned"),
    ("collage", "structure", "Grid / collage", "2x2 / 3x3 grid of clips", "medium", ["collage", "grid"], ["collage banao"], "own code (FFmpeg xstack)", "planned"),
    ("intro_outro", "structure", "Intro / outro card", "branded opening / closing card", "cheap", ["intro card", "outro card", "end card"], ["intro daalo", "outro lagao"], "own code", "planned"),
    ("broll_insert", "structure", "B-roll insertion", "cover talking parts with other clips at keywords", "medium", ["b-roll", "broll"], ["beech me dusre clips"], "own code", "planned"),
    ("censor_box", "overlay", "Blur / pixelate box", "blur or pixelate a region (face, number plate): needs a box param + tracking", "medium", ["censor", "blur the face", "pixelate box"], ["chehra blur karo", "number plate chhupao"], "own code (FFmpeg boxblur/pixelize with crop+overlay)", "planned"),
    ("progress_bar", "overlay", "Progress bar", "a bar at the top that fills as the video plays", "cheap", ["progress bar"], ["upar line chalti rahe"], "own code (FFmpeg drawbox with t)", "planned"),
    ("countdown", "overlay", "Countdown", "3-2-1 or a timer on screen", "cheap", ["countdown", "timer"], ["ulti ginti"], "own code (ASS)", "planned"),
    ("lower_third", "text", "Lower third / name tag", "name + title bar at the bottom", "cheap", ["lower third", "name tag"], ["neeche naam ki patti"], "own code (ASS + drawbox)", "planned"),
    ("callout_arrow", "overlay", "Arrow / highlight box callout", "an arrow or a box pointing at something", "cheap", ["arrow", "highlight box", "callout"], ["teer lagao", "box banao"], "own code (generated PNG)", "planned"),
    ("light_leak", "overlay", "Light leak / film burn", "self-generated warm leaks over the picture", "cheap", ["light leak", "film burn"], ["roshni ki lehar"], "own generated overlays", "planned"),
    ("bokeh", "overlay", "Bokeh particles", "self-generated soft circles", "cheap", ["bokeh"], ["dhundhli roshni ke gole"], "own generated overlays", "planned"),
    ("lottie_overlay", "overlay", "Lottie animation overlay", "server: rlottie (MIT + bundled attributions); phone: lottie-android (Apache-2.0). python-lottie is AGPL: never", "medium", ["lottie", "animated sticker"], ["animated sticker lagao"], "rlottie / lottie-android", "planned"),
    ("subscribe_button", "overlay", "Like / subscribe animation", "self-made animation (no third-party assets)", "cheap", ["subscribe button", "like button"], ["subscribe ka button"], "own assets", "planned"),
    ("logo_watermark", "overlay", "Image logo watermark", "user's PNG logo in a corner", "cheap", ["logo", "image watermark"], ["mera logo lagao"], "user asset", "planned"),
    ("gradient_text", "text", "Gradient-filled text", "ASS cannot fill text with a gradient; needs a mask overlay pass", "medium", ["gradient text"], ["rangeen text"], "own code", "planned"),
    ("emoji_captions", "text", "Emoji in captions", "emoji must be image stickers (ASS draws them monochrome: tested 2026-10-09)", "cheap", ["emoji captions"], ["captions me emoji"], "OS emoji font", "planned"),
    ("eq_voice", "audio", "Voice EQ / clarity", "presence boost + low cut on speech", "cheap", ["eq", "voice clarity"], ["awaaz clear karo"], "own code (FFmpeg equalizer)", "planned"),
    ("compressor", "audio", "Compressor", "even out loud and quiet speech", "cheap", ["compressor", "compress the voice"], ["awaaz ek jaisi"], "own code (FFmpeg acompressor)", "planned"),
    ("echo_reverb", "audio", "Echo / reverb", "echo or room reverb on the voice", "cheap", ["echo", "reverb"], ["goonj daalo"], "own code (FFmpeg aecho)", "planned"),
    ("sfx_at_cuts", "audio", "Sound effects at cuts", "whoosh / hit sounds on cuts: needs a self-made or CC0 sound pack", "cheap", ["sound effects", "whoosh sound"], ["whoosh ki awaaz"], "assets must be own / CC0", "planned"),
    ("audio_reactive", "audio", "Audio-reactive visuals", "picture pulses with the bass (beat pulse exists; amplitude-driven is new)", "medium", ["audio reactive", "pulse with the music"], ["gaane ke saath hile"], "own code", "planned"),
    ("voice_isolation", "audio", "Voice isolation (stems)", "adefossez/demucs (MIT) server job, minutes per minute on CPU", "heavy", ["isolate the voice", "remove the music from the clip"], ["sirf awaaz rakho"], "demucs MIT (adefossez fork)", "planned"),
    ("upscale", "enhance", "Upscale", "Real-ESRGAN (BSD-3) / ncnn-vulkan (MIT): optional server job, GPU recommended", "heavy", ["upscale", "4k", "enhance quality"], ["quality badhao", "hd karo"], "Real-ESRGAN BSD-3 / MIT", "planned"),
    ("frame_interpolation", "enhance", "Smooth slow motion (interpolation)", "Practical-RIFE (MIT): optional server job", "heavy", ["smooth slow motion", "interpolate frames"], ["makkhan jaisa slowmo"], "Practical-RIFE MIT", "planned"),
    ("background_removal", "enhance", "Background removal / green screen", "rembg with birefnet (MIT) or u2net (Apache-2.0), never the default BRIA model; RVM is GPL", "heavy", ["remove background", "green screen"], ["background hatao"], "rembg MIT + birefnet MIT", "planned"),
    ("deflicker", "enhance", "Deflicker", "FFmpeg deflicker for timelapses", "cheap", ["deflicker"], ["chamak kam karo"], "own code (FFmpeg deflicker)", "planned"),
    ("hdr_to_sdr", "enhance", "HDR to SDR tone mapping", "zscale+tonemap (our build has libzimg)", "medium", ["hdr to sdr", "tone map"], ["hdr theek karo"], "own code (FFmpeg zscale)", "planned"),
    ("skin_smoothing", "enhance", "Skin smoothing", "beauty filter: needs a policy / ethics decision and a face parsing model", "heavy", ["skin smoothing", "beauty filter"], ["chehra saaf karo"], "BLOCKED: needs a human decision", "blocked"),
    ("highlight_detection", "auto", "Highlight detection as a skill", "exists inside the cutter (best moments, hook); a separate skill API is planned", "cheap", ["highlights", "best moments"], ["best moments nikalo"], "own code", "planned"),
]
STAGE = {"motion": "geometry", "structure": "structure", "overlay": "overlay", "text": "text", "audio": "audio",
         "enhance": "effect", "auto": "structure", "color": "color"}
skills = []
for sid, cat, name, why, cost, en, hg, lic, kind in P:
    skills.append({"id": sid, "tier": 3, "category": cat, "name": name, "description": why,
                   "synonyms": {"en": en, "hinglish": hg}, "params": {}, "time_modes": ["whole"],
                   "impl": {"kind": kind, "reason": why}, "stage": STAGE[cat], "conflicts": [], "cost": cost,
                   "media3": "not designed yet", "licence": lic, "preview": "n/a",
                   "examples": [f"add {en[0]}", hg[0], f"{en[0]} please", f"use {en[-1]}", f"{en[0]} on the intro"],
                   "status": "blocked" if kind == "blocked" else "planned"})
(ROOT / "skills" / "registry" / "planned.yaml").write_text(
    "# Tier 3: not built yet (or blocked). Each says what it needs. Planned skills are never matched for an edit.\n"
    + yaml.safe_dump({"skills": skills}, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
print(len(skills))
