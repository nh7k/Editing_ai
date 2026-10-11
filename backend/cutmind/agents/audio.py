"""Audio agent: music choice from the local royalty-free folder, levels, ducking, voice cleanup."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..ffmpeg_utils import extract_audio_wav
from ..lyrics import song_words
from ..music_library import music_dirs, project_songs, resolve, selected_song
from ..plan import AudioSettings
from ..song import analyze_song
from .analyzer import beat_grid
from .base import AgentContext, BaseAgent, Feedback

AUDIO_DECISIONS = {"song feel", "song in front", "lyrics as text"}  # whole-edit choices of this agent
MUSIC_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac"}


class AudioDecision(BaseModel):
    use_music: bool
    mood: Literal["upbeat", "calm"] = "upbeat"
    music_volume: float = Field(0.25, ge=0.0, le=1.0)
    ducking: bool = True
    voice_cleanup: bool = False


def list_music(music_dir: Path) -> list[Path]:
    if not music_dir.exists():
        return []
    return sorted(p for p in music_dir.iterdir() if p.suffix.lower() in MUSIC_EXTS and p.is_file())


def pick_track(tracks: list[Path], mood: str | None) -> Path | None:
    if not tracks:
        return None
    if mood:
        for t in tracks:
            if mood in t.stem.lower():
                return t
    return tracks[0]


def music_beats(track: Path, tmp_wav: Path, cache_dir: Path) -> list[float]:
    """Beat grid of a library track, computed once and kept on disk (librosa took ~50 s on the first call of a
    job on the test laptop, every job)."""
    st = track.stat()
    key = hashlib.sha1(f"{track.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]
    cache = cache_dir / f"beats_{key}.json"
    if cache.exists():
        try:
            return [float(x) for x in json.loads(cache.read_text(encoding="utf-8"))]
        except (ValueError, TypeError):
            pass
    _tempo, beats = beat_grid(extract_audio_wav(track, tmp_wav, sr=22050))
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(beats), encoding="utf-8")
    return beats


class AudioAgent(BaseAgent):
    name = "audio"
    system_prompt = (
        "You are the Audio agent of a video editor. Decide whether to add background music (from a local "
        "royalty-free library), its mood (upbeat|calm), its volume (0-1; keep it low, ~0.15-0.3, when people speak), "
        "whether to duck music under speech, and whether to clean up the voice. Reply with JSON only."
    )
    decision_model = AudioDecision

    def task_payload(self, ctx: AgentContext) -> dict[str, Any]:
        tracks = [p.name for p in list_music(ctx.settings.music_dir)]
        return {
            "prompt": ctx.prompt,
            "speech_present": bool(ctx.analysis and ctx.analysis.any_speech),
            "available_tracks": tracks,
            "requested": {"music": ctx.intent.music, "mood": ctx.intent.music_mood,
                          "voice_cleanup": ctx.intent.voice_cleanup} if ctx.intent else {},
        }

    def _choose_track(self, ctx: AgentContext, mood: str | None) -> Path | None:
        """The song for this edit: one picked for this edit in the app → the project's selected song → the newest
        song the user uploaded → the library track for the mood."""
        dirs = music_dirs(ctx.settings, ctx.project_id)
        wanted = ctx.options.get("music_track")
        if wanted and (p := resolve(str(wanted), dirs)) is not None:
            return p
        if ctx.project_id:
            sel = selected_song(ctx.settings, ctx.project_id)
            if sel and (p := resolve(sel, dirs)) is not None:
                return p
            # the user uploaded a song to this project: that is the music they want — but the soundtrack of a
            # reference video only when they ask to edit like the reference
            # (the soundtrack of a liked / reference video is used only by Copy an Edit / "edit like the reference")
            mine = [s for s in project_songs(ctx.settings, ctx.project_id)
                    if not re.search(r"_(sound|copy)(_\d+)?$", s.stem)]
            if mine:
                return mine[0]
        return pick_track(list_music(ctx.settings.music_dir), mood)

    def _finalize(self, ctx: AgentContext, use_music: bool, mood: str | None, volume: float, ducking: bool,
                  cleanup: bool, feedback: list[Feedback] | None) -> dict[str, Any]:
        intent = ctx.intent
        assert intent is not None
        speech = bool(ctx.analysis and ctx.analysis.any_speech)
        settings = AudioSettings(voice_cleanup=cleanup, beat_sync=intent.beat_sync, mute=intent.mute,
                                 fade_in=1.0 if intent.audio_fade else 0.0, fade_out=1.0 if intent.audio_fade else 0.0,
                                 # loudness is normalised at the end, so "louder/quieter" moves the target level
                                 target_lufs=intent.target_lufs if intent.target_lufs is not None and intent.loudness == "normal"
                                 else {"normal": -16.0, "louder": -11.0, "quieter": -23.0}[intent.loudness],
                                 bass_boost=6.0 if intent.bass_boost else 0.0)
        ctx.music_beats = []
        ctx.song = ctx.song_base = None
        ctx.decisions = [d for d in ctx.decisions if d["decision"] not in AUDIO_DECISIONS]  # a rerun replaces them
        if use_music:
            track = self._choose_track(ctx, mood)
            if track is None:
                ctx.log(self.name, "warn", f"music requested but no tracks in {ctx.settings.music_dir.name}/")
            else:
                settings.music = track.name
                if intent.music_volume is not None:
                    settings.music_volume = intent.music_volume
                elif speech:
                    settings.music_volume = round(min(volume, 0.18 if intent.voice_boost else 0.35), 3)
                else:
                    settings.music_volume = round(max(volume, 0.5 if not intent.mute else 0.9), 3)
                settings.ducking = bool((ducking or intent.voice_boost or intent.ducking) and speech and not intent.mute)
                work = (ctx.work_dir or Path(".")) / "song"
                cache = ctx.settings.data_dir / "cache"
                ctx.song_track = track  # the effects agent reads its kick drum (beatmap.py)
                try:
                    ctx.song = analyze_song(track, work, cache)
                    ctx.music_beats = list(ctx.song.beats)
                except Exception as e:  # noqa: BLE001 — a song librosa can't read still plays, just without a feel
                    ctx.log(self.name, "warn", f"could not analyse {track.name}: {e}")
                    tmp = work / f"music_{track.stem}.wav"
                    tmp.parent.mkdir(parents=True, exist_ok=True)
                    ctx.music_beats = music_beats(track, tmp, cache)
                feel = f", {ctx.song.feel} feel {ctx.song.tempo:.0f} bpm" + (f", drop at {ctx.song.drop:.1f}s" if ctx.song.drop
                                                                             else "") if ctx.song else ""
                ctx.log(self.name, "info", f"music: {track.name} vol={settings.music_volume} ducking={settings.ducking}, "
                                           f"{len(ctx.music_beats)} beats{feel}")
                if ctx.song:
                    ctx.decide("song feel", track.name, f"{ctx.song.feel} ({ctx.song.tempo:.0f} bpm, {ctx.song.onset_rate:.1f} "
                               "hits/s) — cut length, motion and text animation follow the song's energy", "song_driven")
        if intent.restore_audio:
            # "audio nahi aa raha": the clip's own sound back at full level, any music clearly under it
            settings.mute, settings.voice_volume = False, 1.0
            if settings.music and speech:
                settings.music_volume = min(settings.music_volume, 0.3)  # people talk: the song goes under them
            ctx.decide("sound back", "whole edit", "you could not hear the video: its own sound is unmuted at normal "
                       "level" + (" and the music is lowered under the voices" if settings.music and speech else ""),
                       "audio_mix")
        elif (settings.music and not speech and not intent.mute and not intent.voice_boost and ctx.project_id
                and any(p.name == settings.music for p in project_songs(ctx.settings, ctx.project_id))):
            settings.voice_volume = 0.35
            settings.music_volume = max(settings.music_volume, 0.9)
            ctx.decide("song in front", settings.music, "your own song leads; the clip's own sound (crowd, wind) is "
                       "kept low under it", "song_driven")
        ctx.lyrics = []
        if settings.music and intent.kinetic_text and (intent.lyrics or not intent.kinetic_words):
            track = resolve(settings.music, music_dirs(ctx.settings, ctx.project_id))
            if track is not None:
                try:
                    found = song_words(track, (ctx.work_dir or Path(".")) / "song", ctx.settings.data_dir / "cache",
                                       only_cached=not intent.lyrics)  # asked: work them out; else only if known
                except Exception as e:  # noqa: BLE001
                    ctx.log(self.name, "warn", f"lyrics: {e}")
                    found = None
                if found and len(found) >= 6:
                    ctx.lyrics = found
                    ctx.decide("lyrics as text", f"{len(found)} sung words", "the words of the song appear as they are "
                               "sung", "song_driven")
                elif intent.lyrics:
                    ctx.log(self.name, "warn", "no clear sung words found in this song — using the title words instead")
        if intent.voice_boost and not intent.mute:
            settings.voice_volume = 1.8
            settings.voice_cleanup = True
        for fb in feedback or []:
            if fb.check == "audio_levels" and "music too loud" in fb.detail:
                settings.music_volume = round(settings.music_volume * 0.6, 3)
            if fb.check == "music_present" and settings.music:
                settings.music_volume = round(min(1.0, settings.music_volume * 1.5), 3)
        return settings.model_dump()

    def rules(self, ctx: AgentContext, feedback: list[Feedback] | None) -> dict[str, Any]:
        it = ctx.intent
        assert it is not None
        return self._finalize(ctx, it.music, it.music_mood, 0.25, True, it.voice_cleanup, feedback)

    def from_decision(self, ctx: AgentContext, decision: BaseModel, feedback: list[Feedback] | None) -> dict[str, Any]:
        d = AudioDecision.model_validate(decision)
        return self._finalize(ctx, d.use_music, d.mood, d.music_volume, d.ducking, d.voice_cleanup, feedback)
