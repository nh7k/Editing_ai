"""One-time writer of the delivery Tier 1 specs (scene_detect, export_preset) and the 4 skills added in
TIER1_REVIEW (stabilize, loop_boomerang, thumbnail, srt_export). Hand-written data; the YAML files are the source
of truth after.

    backend/.venv/Scripts/python.exe skills/tools/write_tier1_delivery.py
"""

from __future__ import annotations

from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parents[1] / "tier1"

SKILLS = [
    dict(id="scene_detect", seed=99, category="delivery", name="Scene detection", name_hi="Scene alag karo",
         desc="Cut the shots wherever the picture changes scene (PySceneDetect content detector, measured per clip).",
         params={"sensitivity": {"type": "choice", "choices": ["normal"], "default": "normal", "desc": "detector setting"}},
         modes=["whole"], graph="analysis (PySceneDetect) → segment splits", media3={"status": "mapped", "how": "server finds the cuts; the phone splits the items"},
         stage="structure", cost="medium", cd=False, needs=["scenes"], licence="own code; PySceneDetect (BSD-3)",
         axes={"use": ["split_only", "split_and_transition"]},
         syn={"en": ["scene detection", "detect scenes", "split into scenes", "find the scenes", "auto split", "cut at scene changes", "scene cuts"],
              "hinglish": ["scenes alag karo", "scene dhoondo", "auto split karo", "scene ke hisaab se kaato", "har scene alag", "scene change pe cut", "scenes pehchano"],
              "hi": ["सीन अलग करो", "सीन ढूँढो", "हर सीन अलग"], "slang": ["auto kaat do scenes"], "typos": ["sceen detect", "scene detction", "seen alag"]},
         neg=["scene mat todo"],
         ex=[("detect the scenes", "en", None), ("split the clip at scene changes", "en", None), ("सीन अलग करो", "hi", None),
             ("scenes alag karo", "hinglish", None), ("har scene alag kar do", "hinglish", None), ("sceen detect", "typo", None),
             ("lamba video hai tukde kar do", "vague", None), ("scenes alag karo aur crossfade", "multi", {"_also": ["crossfade"]})],
         test={"check": "cuts_at_scenes", "media": "scenes"}),
    dict(id="export_preset", seed=100, category="delivery", name="Export for a platform", name_hi="Instagram ke liye",
         desc="Size, frame rate and bitrate for a platform (specs checked 2026-10-09, third-party guides): Reels / Shorts 1080x1920 30 fps; WhatsApp Status 720p, ≤ 30 s (safe value; guides disagree).",
         params={"platform": {"type": "choice", "choices": ["instagram_reels", "youtube_shorts", "whatsapp_status", "youtube", "linkedin", "instagram_feed"],
                              "default": "instagram_reels", "extract": "platform", "desc": "platform"},
                 "quality": {"type": "choice", "choices": ["high", "light"], "default": "high", "desc": "1080p or a lighter 720p"}},
         modes=["whole"], graph="canvas size / fps + libx264 crf + maxrate, AAC 128k", media3={"status": "mapped", "how": "Transformer with Presentation + VideoEncoderSettings (bitrate)"},
         stage="export", cost="cheap", cd=False, needs=[], licence="own code; FFmpeg + libx264 (GPL build, server process only)",
         axes={"platform": ["instagram_reels", "youtube_shorts", "whatsapp_status", "youtube", "linkedin"], "quality": ["high", "light"]},
         syn={"en": ["export", "export for instagram", "save for youtube", "for whatsapp", "export settings", "upload ready", "platform export"],
              "hinglish": ["export karo", "save karo", "instagram ke liye", "whatsapp ke liye", "youtube quality", "status ke liye export", "upload ke liye ready karo"],
              "hi": ["एक्सपोर्ट करो", "सेव करो", "इंस्टाग्राम के लिए"], "slang": ["final nikal do"], "typos": ["exprot", "insta ke liya", "export kro"]},
         neg=["export mat karo"],
         ex=[("export for instagram reels", "en", {"platform": "instagram_reels"}), ("save it for youtube shorts", "en", {"platform": "youtube_shorts"}),
             ("इंस्टाग्राम के लिए एक्सपोर्ट करो", "hi", {"platform": "instagram_reels"}), ("whatsapp status ke liye export karo", "hinglish", {"platform": "whatsapp_status"}),
             ("youtube quality me save karo", "hinglish", {"platform": "youtube"}), ("exprot insta", "typo", {"platform": "instagram_reels"}),
             ("ab final nikal do", "vague", None), ("insta ke liye export aur captions", "multi", {"platform": "instagram_reels", "_also": ["auto_captions"]})],
         test={"check": "platform_specs", "params": {"platform": "instagram_reels", "quality": "light"}}),
    dict(id="stabilize", seed=101, category="motion", name="Stabilise", name_hi="Hilna band karo",
         desc="Steadier handheld footage: FFmpeg deshake (LGPL; vid.stab is GPL and is not used), edges cropped slightly.",
         params={"strength": {"type": "number", "default": 1.0, "min": 0.5, "max": 3.0, "extract": "magnitude", "desc": "how much"}},
         modes=["whole", "segment", "between_times"], graph="deshake + crop + scale", media3={"status": "server_only", "reason": "needs motion analysis of every frame"},
         stage="geometry", cost="medium", cd=False, needs=[], licence="own code; FFmpeg deshake (LGPL part of FFmpeg)",
         axes={"strength": ["light", "normal", "strong"]},
         syn={"en": ["stabilize", "stabilise", "steady", "remove shake", "fix the shaky video", "smooth the camera", "anti shake"],
              "hinglish": ["hilna band karo", "video stable karo", "shake hatao", "kampan hatao", "camera hil raha hai theek karo", "stable banao", "jhatke hatao"],
              "hi": ["हिलना बंद करो", "स्थिर करो", "शेक हटाओ"], "slang": ["gimbal jaisa"], "typos": ["stablize", "stabilse", "stable kro"]},
         neg=["stabilize mat karo"],
         ex=[("stabilize the video", "en", None), ("remove the camera shake", "en", None), ("वीडियो स्थिर करो", "hi", None),
             ("video stable karo", "hinglish", None), ("camera hil raha hai theek karo", "hinglish", None), ("stablize", "typo", None),
             ("chalte hue shoot kiya tha", "vague", None), ("stable karo aur slow motion", "multi", {"_also": ["slow_motion"]})],
         test={"check": "steadier", "media": "shaky"}),
    dict(id="loop_boomerang", seed=103, category="motion", name="Boomerang loop", name_hi="Boomerang",
         desc="The clip forward, then backwards (x times): the Boomerang loop. Short edits only (≤ 20 s).",
         params={"times": {"type": "integer", "default": 1, "min": 1, "max": 4, "extract": "count", "desc": "how many back-and-forths"}},
         modes=["whole"], graph="segments + reversed copies", media3={"status": "server_only", "reason": "Media3 cannot decode backwards"},
         stage="time", cost="medium", cd=True, needs=[], licence="own code; FFmpeg reverse (server process)",
         axes={"times": ["1", "2", "3"]},
         syn={"en": ["boomerang", "loop back and forth", "forward and backward", "ping pong loop", "boomerang effect", "loop it", "rewind loop"],
              "hinglish": ["boomerang banao", "aage peeche chalao", "ulta seedha loop", "boomerang jaisa", "aage jaaye phir wapas", "loop karo", "insta boomerang"],
              "hi": ["बूमरैंग", "आगे पीछे चलाओ", "उल्टा सीधा लूप"], "slang": ["insta wala loop"], "typos": ["boomrang", "bumerang", "boomerange"]},
         neg=["boomerang mat karo"],
         ex=[("make it a boomerang", "en", None), ("boomerang 2 times", "en", {"times": 2}), ("बूमरैंग बनाओ", "hi", None),
             ("boomerang banao", "hinglish", None), ("aage peeche chalao", "hinglish", None), ("boomrang", "typo", None),
             ("insta jaisa loop", "vague", None), ("boomerang aur music", "multi", {"_also": ["add_music"]})],
         test={"check": "boomerang", "setup": [{"id": "trim", "params": {"start": 0.0, "end": 3.0}}]}),
    dict(id="thumbnail", seed=104, category="delivery", name="Thumbnail", name_hi="Cover photo",
         desc="A cover image (JPG) from a moment of the edit, next to the video.",
         params={"at": {"type": "number", "min": 0, "max": 36000, "unit": "s", "extract": "time_point", "desc": "which moment (default a third in)"}},
         modes=["whole"], graph="one frame of the final video → JPG", media3={"status": "mapped", "how": "MediaMetadataRetriever.getFrameAtTime"},
         stage="export", cost="cheap", cd=False, needs=[], licence="own code; FFmpeg (server process)", axes={"moment": ["start", "third", "best"]},
         syn={"en": ["thumbnail", "cover image", "cover photo", "poster frame", "make a thumbnail", "video cover", "preview image"],
              "hinglish": ["cover photo banao", "thumbnail chahiye", "cover image do", "thumbnail banao", "photo nikalo cover ke liye", "poster frame do", "video ka cover"],
              "hi": ["थंबनेल", "कवर फोटो", "कवर इमेज"], "slang": ["dp jaisa cover"], "typos": ["thumnail", "thumbnial", "cover foto"]},
         neg=["thumbnail mat banao"],
         ex=[("make a thumbnail", "en", None), ("cover image from 3 seconds", "en", {"at": 3.0}), ("थंबनेल बनाओ", "hi", None),
             ("cover photo banao", "hinglish", None), ("2 sec pe thumbnail", "hinglish", {"at": 2.0}), ("thumnail", "typo", None),
             ("youtube ke liye cover", "vague", None), ("thumbnail aur mp3", "multi", {"_also": ["extract_audio"]})],
         test={"check": "thumbnail_file", "params": {"at": 2.0}}),
    dict(id="srt_export", seed=105, category="delivery", name="Captions as .srt", name_hi="Subtitle file",
         desc="The captions also saved as an .srt subtitle file (YouTube accepts it; accessibility).",
         params={"format": {"type": "choice", "choices": ["srt"], "default": "srt", "desc": "file type"}},
         modes=["whole"], graph="caption items → SubRip text", media3={"status": "mapped", "how": "a sidecar file (no video work)"},
         stage="export", cost="cheap", cd=False, needs=["speech"], licence="own code", axes={"format": ["srt"]},
         syn={"en": ["srt", "subtitle file", "export subtitles", "caption file", "save the captions", "srt file", "download subtitles"],
              "hinglish": ["subtitle file do", "srt banao", "captions ki file", "subtitle alag file", "srt chahiye", "caption download", "subtitle file nikalo"],
              "hi": ["सबटाइटल फ़ाइल", "एसआरटी", "कैप्शन की फ़ाइल"], "slang": ["youtube wali subtitle file"], "typos": ["str file", "subtitel file", "srtt"]},
         neg=["srt mat banao"],
         ex=[("export the subtitles as srt", "en", None), ("give me a subtitle file", "en", None), ("सबटाइटल फ़ाइल दो", "hi", None),
             ("srt banao", "hinglish", None), ("captions ki file do", "hinglish", None), ("subtitel file", "typo", None),
             ("youtube pe subtitles daalne hain", "vague", None), ("captions lagao aur srt bhi", "multi", {"_also": ["auto_captions"]})],
         test={"check": "srt_file", "media": "talk", "setup": [{"id": "auto_captions"}]}),
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
            "id": s["id"], "seed": s["seed"], "category": s["category"], "name": s["name"], "name_hi": s["name_hi"],
            "description": s["desc"], "params": s["params"], "time_modes": s["modes"], "builder": f"delivery.{s['id']}",
            "graph": s["graph"], "media3": s["media3"], "stage": s["stage"], "conflicts": [], "cost": s["cost"],
            "licence": s["licence"], "changes_duration": s["cd"], "needs": s["needs"], "variant_axes": s["axes"],
            "synonyms": s["syn"], "negations": s["neg"], "examples": examples, "test": s["test"],
        }
        (OUT / f"{s['id']}.yaml").write_text("# written by skills/tools/write_tier1_delivery.py — edit this file directly from now on\n"
                                             + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
        print(s["id"])


if __name__ == "__main__":
    main()
