"""Specialist registry + AgentRouter.

~170 specialist roles, every one backed by real code (`impl` names the function / filter that does the work).
They are NOT 170 LLM calls: on a CPU-only laptop each LLM call costs 10-30 s, so the work is done by the five
planning agents (Director, Analyzer, Audio, Cutter, Color, Effects) + Reviewer, which apply the specialists the
router selected. The router picks the 5-25 specialists a request needs; the rest never run.

Routing is real, not decorative: it decides e.g. whether speech-to-text runs (`ctx.need_transcript`), and the
live activity panel shows exactly the selected list.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .fx_catalog import ALL_FX, LUT_LOOKS, TEXT_ANIMATIONS
from .intent import Intent

Need = Callable[[Intent], bool]


@dataclass(frozen=True)
class Specialist:
    id: str
    name: str
    category: str
    impl: str              # where the work happens
    needs: Need            # does this request need it?
    available: bool = True
    unavailable_reason: str = ""


def _always(_: Intent) -> bool:
    return True


def _cuts(i: Intent) -> bool:
    return bool(i.target_duration or i.fast_cuts or i.remove_silence or i.remove_fillers or i.remove_idle or i.auto
                or i.order != "original" or i.timed_effects)


_CORE: list[Specialist] = [
    Specialist("conversation", "Conversation Understanding", "conversation", "coach.understand", _always),
    Specialist("intent_parser", "Intent Extractor (Hinglish)", "intent", "intent.parse_intent", _always),
    Specialist("prompt_compiler", "Prompt Compiler", "prompt", "coach.solid_prompt", _always),
    Specialist("planner", "Director / Planner", "planning", "agents.director + workflow", _always),
    Specialist("memory_keeper", "Memory Keeper", "memory", "memory.Memory", _always),
    Specialist("media_probe", "Media Probe", "media_analysis", "ffmpeg_utils.probe", _always),
    Specialist("visual_analyzer", "Visual Analyzer (sharpness/motion)", "media_analysis", "analyzer.visual_stats", _always),
    Specialist("audio_analyzer", "Audio Analyzer (loudness)", "audio_analysis", "ffmpeg_utils.measure_loudness", _always),
    Specialist("color_grader", "Colour Grader + exposure matching", "color", "agents.color", _always),
    Specialist("audio_mixer", "Audio Mixer (loudness normalisation)", "audio_mixing", "renderer.finish (loudnorm)", _always),
    Specialist("timeline_builder", "Timeline Builder", "timeline", "plan.EditPlan.timeline", _always),
    Specialist("renderer", "Renderer (parallel segments)", "rendering", "renderer.render", _always),
    Specialist("quality_gate", "Quality Gate (decode, streams, size)", "quality_control", "reviewer: file_plays/audio_stream", _always),
    Specialist("reviewer", "Reviewer", "reviewer", "agents.reviewer", _always),
    Specialist("lesson_writer", "Lesson Writer", "lessons", "director.record → db.add_lesson", _always),
    Specialist("error_recovery", "Error Recovery (fix loop)", "error_recovery", "workflow.fix", _always),
    Specialist("exporter", "MP4 Exporter", "export", "renderer.finish", _always),
]

_COND: list[Specialist] = [
    Specialist("scene_detector", "Scene Detector", "scene_detection", "analyzer.detect_scenes (PySceneDetect)",
               lambda i: i.fast_cuts or i.auto or i.order in ("best", "smart")),
    Specialist("clip_selector", "Clip Selector", "clip_selection", "cutter.fit", _cuts),
    Specialist("transcriber", "Transcriber (faster-whisper)", "transcript", "analyzer.transcribe",
               lambda i: i.captions or i.remove_fillers or i.remove_silence or i.word_stickers or _cuts(i)),
    Specialist("silence_detector", "Silence Remover", "silence", "cutter.speech_pieces", lambda i: i.remove_silence),
    Specialist("filler_remover", "Filler-word Remover", "silence", "cutter.speech_pieces (fillers)", lambda i: i.remove_fillers),
    Specialist("idle_remover", "Frozen-part Remover", "clip_selection", "analyzer.detect_idle + cutter", lambda i: i.remove_idle),
    Specialist("caption_writer", "Caption Writer", "caption", "effects.caption_items", lambda i: i.captions),
    Specialist("subtitle_stylist", "Subtitle Stylist", "subtitle_styling", "renderer ASS styles",
               lambda i: i.captions or i.text_animation != "none"),
    Specialist("word_sticker_artist", "Word Stickers (said → emoji pop-up)", "effects", "stickers.pick + renderer stickers",
               lambda i: i.word_stickers),
    Specialist("title_designer", "Title Designer", "caption", "effects (title)", lambda i: bool(i.title)),
    Specialist("watermark_artist", "Watermark", "caption", "effects (watermark)", lambda i: bool(i.watermark)),
    Specialist("pacing_editor", "Pacing Editor (fast cuts)", "pacing", "cutter.chunk_piece", lambda i: i.fast_cuts),
    Specialist("beat_matcher", "Beat Matcher", "pacing", "cutter (beat-synced chunks)", lambda i: i.beat_sync),
    Specialist("story_arranger", "Story Arranger (clip order)", "story_structure", "cutter.smart_order",
               lambda i: i.order != "original"),
    Specialist("hook_finder", "Hook Finder", "story_structure", "cutter.hook_first", lambda i: i.auto),
    Specialist("auto_editor", "Auto Editor (beginner mode)", "planning", "director.autopilot", lambda i: i.auto),
    Specialist("music_supervisor", "Music Supervisor", "music", "agents.audio (pick_track + beat grid)", lambda i: i.music),
    Specialist("ducker", "Music Ducking", "audio_mixing", "renderer sidechaincompress", lambda i: i.music),
    Specialist("bass_engineer", "Bass Engineer", "audio_mixing", "renderer bass filter", lambda i: i.bass_boost),
    Specialist("voice_cleaner", "Voice Cleaner", "voice", "renderer highpass + afftdn", lambda i: i.voice_cleanup),
    Specialist("mute_operator", "Mute", "audio_mixing", "renderer volume=0", lambda i: i.mute),
    Specialist("audio_fader", "Audio Fades", "audio_mixing", "renderer afade", lambda i: i.audio_fade),
    Specialist("loudness_target", "Loudness Target", "audio_mixing", "audio agent target_lufs", lambda i: i.loudness != "normal"),
    Specialist("reframer", "Reframer (9:16 / 1:1 / 16:9)", "timeline", "renderer.reframe_filter", lambda i: bool(i.aspect_ratio)),
    Specialist("resizer", "Resolution", "export", "plan.Canvas.size", lambda i: bool(i.resolution)),
    Specialist("rotator", "Rotate", "effects", "renderer.orientation_filters", lambda i: bool(i.rotate)),
    Specialist("flipper", "Mirror / Flip", "effects", "renderer.orientation_filters", lambda i: i.flip != "none"),
    Specialist("reverser", "Reverse Playback", "effects", "renderer reverse/areverse", lambda i: i.reverse_playback),
    Specialist("slow_motion", "Slow Motion (FFmpeg speed)", "effects", "cutter speed 0.5", lambda i: i.slow_motion),
    Specialist("fps_converter", "Frame Rate", "export", "renderer fps", lambda i: bool(i.fps)),
    Specialist("brightness", "Brightness / Gamma", "color", "color agent", lambda i: bool(i.brightness) or i.gamma != 1.0),
    Specialist("style_designer", "Pro Look Designer (gradient overlays)", "effects", "styles.apply_style",
               lambda i: bool(i.style) or i.variations > 1),
    Specialist("variation_ranker", "Variation Ranker", "reviewer", "director._variations", lambda i: i.variations > 1),
    Specialist("fx_scheduler", "Timed-FX Scheduler", "timeline", "cutter.split_at_output_times + effects",
               lambda i: bool(i.timed_effects)),
    Specialist("subject_tracker", "Person / Face Tracker (YOLOX-nano, YuNet)", "computer_vision", "tracking.track_clip",
               lambda i: any(e in ("follow", "person_zoom", "spotlight") for e in i.effects) or bool(i.tracked_text)
               or any(t.effect in ("follow", "person_zoom", "spotlight") for t in i.timed_effects)),
    Specialist("label_tracker", "Text that follows a person", "caption", "effects._tracked_text + ASS move tags",
               lambda i: bool(i.tracked_text)),
    Specialist("text_designer", "Text Designer (fonts, colours, presets)", "subtitle_styling", "text_styles.apply_look",
               lambda i: bool(i.text_style or i.text_color)),
    Specialist("colour_pass", "Colour Pass (B&W rhythm)", "color", "effects._editorial_effects color_pass",
               lambda i: i.color_pass),
    Specialist("velocity_editor", "Velocity Moves (stutter, ramp)", "pacing", "cutter.velocity_moves", lambda i: i.speed_moves),
    Specialist("impact_hitter", "Impact Hits (zoom blur)", "effects", "effects._editorial_effects impact_hits",
               lambda i: i.impact_hits),
    Specialist("kinetic_typographer", "Kinetic Typography", "subtitle_styling", "effects._kinetic", lambda i: i.kinetic_text),
    Specialist("gif_exporter", "GIF Exporter", "export", "renderer.export_extras", lambda i: i.export_gif),
    Specialist("mp3_exporter", "MP3 Exporter", "export", "renderer.export_extras", lambda i: i.export_mp3),
]


def _fx_specialists() -> list[Specialist]:
    out: list[Specialist] = []
    for f in ALL_FX:
        if f.category in ("motion", "video_effect"):
            out.append(Specialist(f"fx_{f.id}", f"{f.name} FX", "effects", f"fx_catalog:{f.id}",
                                  lambda i, e=f.id: e in i.effects or any(t.effect == e for t in i.timed_effects)))
        elif f.category == "transition":
            out.append(Specialist(f"tr_{f.id}", f"{f.name} transition", "transitions", f"xfade:{f.xfade or f.id}",
                                  lambda i, e=f.id: i.transition == e))
    for look, (name, _d, _k) in LUT_LOOKS.items():
        out.append(Specialist(f"lut_{look}", f"{name} LUT", "color", f"luts:{look}.cube", lambda i, e=look: i.color_preset == e))
    for anim, (desc, _k) in TEXT_ANIMATIONS.items():
        out.append(Specialist(f"text_{anim}", f"Text animation: {desc}", "subtitle_styling", f"renderer._text_animation:{anim}",
                              lambda i, e=anim: i.text_animation == e))
    return out


# Capabilities this CPU-only build deliberately does not ship (see CPU_MODE.md). Listed so the router can say so.
_GPU_ONLY: list[Specialist] = [
    Specialist("video_generator", "AI Video Generation", "video_generation", "-", lambda i: False, False,
               "needs a large GPU model (Wan / LTX-Video / HunyuanVideo); disabled without a GPU"),
    Specialist("image_generator", "AI Image Generation", "image_generation", "-", lambda i: False, False,
               "Stable Diffusion-class models are too slow on this CPU; disabled"),
    Specialist("broll_generator", "AI B-roll", "broll", "-", lambda i: False, False, "depends on video generation"),
    Specialist("frame_interpolator", "AI Frame Interpolation (RIFE)", "effects", "-", lambda i: False, False,
               "GPU model; slow motion uses FFmpeg speed change instead"),
    Specialist("ai_upscaler", "AI Upscaler (Real-ESRGAN)", "enhancement", "-", lambda i: False, False,
               "minutes per second of video on CPU; resolution uses FFmpeg scaling instead"),
]

REGISTRY: list[Specialist] = [*_CORE, *_COND, *_fx_specialists(), *_GPU_ONLY]
BY_ID = {s.id: s for s in REGISTRY}


def route(intent: Intent) -> list[Specialist]:
    """The specialists this request needs (available ones only), core first."""
    return [s for s in REGISTRY if s.available and s.needs(intent)]


def registry_summary() -> dict[str, object]:
    cats: dict[str, int] = {}
    for s in REGISTRY:
        cats[s.category] = cats.get(s.category, 0) + 1
    return {"total": len(REGISTRY), "available": sum(s.available for s in REGISTRY), "by_category": cats,
            "unavailable": [{"id": s.id, "name": s.name, "reason": s.unavailable_reason} for s in REGISTRY if not s.available]}
