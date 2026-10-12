"""H. Audio — music, ducking, volume (exact dB), mute (all or a part), fades, loudness (exact LUFS), denoise,
voice clarity, beat sync, whoosh, echo / reverb, replace the sound, export the sound.

Levels are numbers, not adjectives: "volume +6 dB" changes the measured loudness by 6 dB (the renderer measures
the mix and corrects it — renderer.correct_loudness), "-14 LUFS" is checked on the file.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ..plan import EditPlan
from .engine import ToolCtx, tool
from .timeline import ToolError, remap_timed, split_at
from .timewin import When


def _audio(plan: EditPlan, **kw: Any) -> EditPlan:
    data = plan.to_json()
    data["audio"].update(kw)
    return EditPlan.model_validate(data)


def _library(ctx: ToolCtx) -> list[Path]:
    from ..agents.audio import list_music

    out: list[Path] = []
    for d in ctx.music_dirs:
        out += list_music(d)
    return out


def _track(ctx: ToolCtx, name: str | None, mood: str | None) -> Path:
    from ..agents.audio import pick_track
    from ..music_library import resolve

    if name:
        p = resolve(name, ctx.music_dirs)
        if p is None:
            # "Kesariya" → a file whose name contains the words
            want = name.lower().replace(" ", "")
            p = next((t for t in _library(ctx) if want in t.stem.lower().replace(" ", "").replace("_", "")), None)
        if p is None:
            raise ToolError(f"no song called '{name}' — upload it in Sounds first")
        return p
    # the user's own song first (the one picked in Sounds, else the newest upload) — like the director; before, the
    # skill took a library track and ignored the uploaded song
    for d in ctx.music_dirs:
        sel = d / "selected.json"
        if sel.exists():
            try:
                chosen = resolve(json.loads(sel.read_text(encoding="utf-8")).get("name") or "", ctx.music_dirs)
            except ValueError:
                chosen = None
            if chosen is not None:
                return chosen
        if d.name == "music" and d.parent.parent.name == "projects" and d.is_dir():  # no upload yet: no folder
            own = sorted((x for x in d.iterdir() if x.suffix.lower() in (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac")),
                         key=lambda x: x.stat().st_mtime, reverse=True)
            if own:
                return own[0]
    p = pick_track(_library(ctx), mood)
    if p is None:
        raise ToolError("there is no music in the library yet — upload a song in Sounds")
    return p


@tool("add_music")
def add_music(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    t = _track(ctx, p.get("track"), p.get("mood"))
    speech = bool(ctx.words()) if ctx.analysis else False
    duck = speech if p["duck"] == "auto" else p["duck"] == "on"
    vol = float(p["volume"]) if p.get("volume") is not None else (0.25 if speech else 0.6)
    new = _audio(plan, music=t.name, music_volume=vol, music_start=float(p["start"]), ducking=duck)
    ctx.notes.append(f"music: {t.stem} at {vol:.0%}" + (", ducked under the voice" if duck else "")
                     + (f", from {p['start']:g}s into the song" if p["start"] else ""))
    return new


@tool("duck_music")
def duck_music(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    if not plan.audio.music:
        raise ToolError("there is no music to duck — add music first")
    ctx.notes.append(f"music drops {p['amount']:g} dB while someone speaks")
    return _audio(plan, ducking=True, duck_amount_db=float(p["amount"]))


@tool("volume")
def volume(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    g = float(p["gain_db"])
    if when.whole:
        if p["what"] == "music":
            if not plan.audio.music:
                raise ToolError("there is no music — add music first")
            v = min(1.0, max(0.0, plan.audio.music_volume * 10 ** (g / 20)))
            ctx.notes.append(f"music level {plan.audio.music_volume:.2f} → {v:.2f} ({g:+g} dB)")
            return _audio(plan, music_volume=round(v, 4))
        if p["what"] == "voice":
            v = min(3.0, max(0.0, plan.audio.voice_volume * 10 ** (g / 20)))
            ctx.notes.append(f"the video's own sound {g:+g} dB (against the music)")
            return _audio(plan, voice_volume=round(v, 4))
        total = plan.audio.gain_db + g
        ctx.notes.append(f"whole mix {g:+g} dB (measured and corrected after the render; louder than -9 LUFS "
                         "is capped — it would only clip)")
        return _audio(plan, gain_db=round(max(-30.0, min(20.0, total)), 2), exact_loudness=True)
    data = plan.to_json()
    for a, b in when.windows:
        data["audio"]["volume_ranges"].append({"start": round(a, 3), "end": round(b, 3), "gain_db": g})
    ctx.notes.append(f"the video's own sound {g:+g} dB ({when.describe()})")
    return EditPlan.model_validate(data)


@tool("mute")
def mute(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    if when.whole:
        ctx.notes.append("the video's own sound is off" + (" (the music stays)" if plan.audio.music else ""))
        return _audio(plan, mute=True)
    data = plan.to_json()
    for a, b in when.windows:
        data["audio"]["volume_ranges"].append({"start": round(a, 3), "end": round(b, 3), "gain_db": -60.0})
    ctx.notes.append(f"sound off {when.describe()}")
    return EditPlan.model_validate(data)


@tool("audio_fade")
def audio_fade(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    total = plan.total_duration()
    fi = float(p["fade_in"]) if p["where"] in ("in", "both") else plan.audio.fade_in
    fo = float(p["fade_out"]) if p["where"] in ("out", "both") else plan.audio.fade_out
    fi, fo = min(fi, total / 2), min(fo, total / 2)
    ctx.notes.append(f"sound fades in {fi:g}s, out {fo:g}s")
    return _audio(plan, fade_in=round(fi, 3), fade_out=round(fo, 3))


@tool("normalize_loudness")
def normalize_loudness(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    t = float(p["target_lufs"])
    ctx.notes.append(f"loudness {t:g} LUFS, measured on the finished mix and corrected (true peak ≤ -2 dBFS)")
    return _audio(plan, target_lufs=t, gain_db=0.0, exact_loudness=True)


def noise_floor(src: Path) -> float | None:
    """The clip's background level (linear, 0..1): the 10th percentile of 50 ms RMS values — the quiet bits
    between phrases. None when the clip has no sound."""
    import subprocess

    import numpy as np

    from ..ffmpeg_utils import ffmpeg_bin

    raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, timeout=300).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(float) / 32768.0
    if len(x) < 1600:
        return None
    n = len(x) // 800
    rms = np.sqrt((x[: n * 800].reshape(n, 800) ** 2).mean(axis=1))
    rms = rms[rms > 1e-5]
    return float(np.percentile(rms, 10)) if len(rms) else None


@tool("denoise")
def denoise(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    floors = [f for f in (noise_floor(ctx.sources[c]) for c in {s.source for s in plan.clips}) if f]
    if not floors:
        raise ToolError("this video has no sound to clean")
    # gate just above the noisiest clip's floor (+8 dB): it closes in the gaps, never on the voice
    thr = round(min(0.3, max(floors) * 2.5), 4)
    ctx.notes.append(f"background noise reduced ({p['amount']}: FFmpeg afftdn + a gate at {20 * math.log10(thr):.0f} dBFS, "
                     f"measured noise floor {20 * math.log10(max(floors)):.0f} dBFS)")
    return _audio(plan, denoise=p["amount"], gate_threshold=thr)


@tool("voice_clarity")
def voice_clarity(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    ctx.notes.append("speech EQ: rumble cut 90 Hz, less mud 280 Hz, presence +4 dB at 3.2 kHz, de-ess")
    return _audio(plan, voice_eq="clarity")


@tool("echo_reverb")
def echo_reverb(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    ctx.notes.append(f"echo / room {p['amount']:.0%}")
    return _audio(plan, reverb=float(p["amount"]))


@tool("sfx_whoosh")
def sfx_whoosh(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    tl = plan.timeline()
    if when.instants:
        times = when.instants
    else:
        times = [e.start for e in tl[1:]]
        if not times:
            raise ToolError("there is no cut for a whoosh — give a time (e.g. 'at 3 sec')")
    data = plan.to_json()
    for t in times:
        data["audio"]["sfx"].append({"kind": "whoosh", "at": round(t, 3), "volume": float(p["volume"])})
    ctx.notes.append(f"whoosh at {len(times)} point(s)")
    return EditPlan.model_validate(data)


@tool("replace_audio")
def replace_audio(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    t = _track(ctx, p.get("track"), p.get("mood"))
    ctx.notes.append(f"the video's own sound replaced by {t.stem} (full level)")
    return _audio(plan, mute=True, music=t.name, music_volume=1.0, ducking=False, music_start=float(p["start"]))


@tool("extract_audio")
def extract_audio(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    data = plan.to_json()
    if p["format"] not in data["export"]["extras"]:
        data["export"]["extras"].append(p["format"])
    ctx.notes.append(f"the finished sound also saved as {p['format'].upper()}")
    return EditPlan.model_validate(data)


@tool("beat_sync")
def beat_sync(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    """Move every cut onto the nearest beat of the music (each shot gets a little longer or shorter, inside
    what its clip has). Without cuts: cut the shots on every Nth beat."""
    if not plan.audio.music:
        raise ToolError("beat sync needs music — add music first")
    beats = ctx.beats() if ctx.beats else song_beats(plan, ctx)
    if not beats:
        raise ToolError("no beats found in the music")
    beats = beats[::max(1, int(p["every"]))]
    from .invariants import source_duration

    tl = plan.timeline()
    if len(tl) == 1:  # one long shot: cut it on the beats so the picture changes with the music
        for b in reversed(beats):
            if 0.5 < b < plan.total_duration() - 0.5:
                try:
                    plan = split_at(plan, b)
                except ToolError:
                    continue
        ctx.notes.append(f"cut on {len(plan.timeline()) - 1} beats (every {p['every']})")
        return plan
    data = plan.to_json()
    order = sorted(range(len(data["clips"])), key=lambda k: data["clips"][k]["order"])
    moved = 0
    # walk the cuts left to right; shifting cut i changes shot i's length, later cuts move with it
    shift = 0.0
    for e in tl[:-1]:
        if plan.overlap_after(e.index) > 0:
            continue
        cut = e.end + shift
        b = min(beats, key=lambda x: abs(x - cut))
        delta = b - cut
        if abs(delta) < 0.02 or abs(delta) > float(p["max_shift"]):
            continue
        c = data["clips"][order[e.index]]
        new_out = c["out"] + delta * c["speed"]
        dur = source_duration(ctx.sources[c["source"]])
        if c["reverse"] or new_out > dur - 0.02 or new_out - c["in"] < 0.3:
            continue
        c["out"] = round(new_out, 3)
        shift += delta
        moved += 1
    ctx.notes.append(f"{moved} of {len(tl) - 1} cuts moved onto a beat (by ≤ {p['max_shift']:g}s)")
    return EditPlan.model_validate(remap_timed(plan, data))


def song_beats(plan: EditPlan, ctx: ToolCtx) -> list[float]:
    """The music's beats in OUTPUT seconds (the song may start later in the track: music_start)."""
    from ..song import analyze_song

    t = _track(ctx, plan.audio.music, None)
    prof = analyze_song(t, ctx.gen_dir, ctx.gen_dir.parent / "analysis")
    if prof is None:
        return []
    return [round(b - plan.audio.music_start, 3) for b in prof.beats if b >= plan.audio.music_start]

