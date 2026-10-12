"""The Edit Plan: the single source of truth that agents write and the renderer executes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

AspectRatio = Literal["9:16", "1:1", "16:9", "4:5"]
ColorPreset = Literal["none", "warm", "cool", "cinematic", "vintage", "bw", "vivid", "sepia",
                      # generated 3D-LUT looks (cutmind/luts.py)
                      "teal_orange", "golden_hour", "moody_blue", "cyberpunk", "forest", "faded_film", "pastel",
                      "noir", "warm_film", "arctic"]
TextAnimation = Literal["none", "fade", "pop", "slide_up", "typewriter", "bounce", "karaoke",
                        "zoom_in", "zoom_out", "spin_in", "flip_in", "blur_in", "drop_in", "fly_left", "fly_right",
                        "swing", "shake", "heartbeat", "flicker", "glow_pulse", "color_cycle", "wave", "cascade",
                        "stretch"]


def _check_catalog(kind: str, value: str) -> str:
    from .fx_catalog import EFFECT_IDS, TRANSITION_IDS  # local import keeps plan.py dependency-free at import time

    allowed = EFFECT_IDS if kind == "effect" else TRANSITION_IDS
    if value not in allowed:
        raise ValueError(f"unknown {kind} '{value}' (see GET /fx for the catalogue)")
    return value


TransitionType = Annotated[str, AfterValidator(lambda v: _check_catalog("transition", v))]
EffectType = Annotated[str, AfterValidator(lambda v: _check_catalog("effect", v))]

PLAN_VERSION = "1.0"
MAX_REVERSE_SECONDS = 12.0
FADE_IN = -1   # transition.after value: fade from black at the very start
FADE_OUT = -2  # transition.after value: fade to black at the very end


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", validate_assignment=False)


class Canvas(_Model):
    aspect_ratio: AspectRatio = "16:9"
    resolution: Literal[360, 480, 720, 1080] = 720  # length of the SHORT side in pixels
    fps: int = Field(30, ge=12, le=60)
    reframe: Literal["crop", "blur_pad", "pad"] = "crop"  # pad = the whole picture with black bars
    rotate: Literal[0, 90, 180, 270] = 0          # clockwise, applied to every source before reframing
    flip: Literal["none", "h", "v", "hv"] = "none"  # mirror horizontally / vertically

    @property
    def size(self) -> tuple[int, int]:
        """(width, height) in pixels, always even."""
        short = self.resolution
        if self.aspect_ratio == "1:1":
            return short, short
        if self.aspect_ratio == "4:5":  # Instagram portrait post
            return short, int(round(short * 5 / 4 / 2)) * 2
        long_side = int(round(short * 16 / 9 / 2)) * 2
        return (long_side, short) if self.aspect_ratio == "16:9" else (short, long_side)


class ClipSegment(_Model):
    source: str = Field(min_length=1, description="clip id")
    in_: float = Field(alias="in", ge=0)
    out: float = Field(gt=0)
    order: int = Field(ge=0)
    speed: float = Field(1.0, ge=0.25, le=4.0)
    volume: float = Field(1.0, ge=0.0, le=2.0)
    reverse: bool = False  # play this segment backwards (video + audio)
    hold: bool = False     # freeze frame: show the frame at `in` for (out - in) seconds (the sound is silent)

    @model_validator(mode="after")
    def _check_range(self) -> "ClipSegment":
        if self.out - self.in_ < 0.2:
            raise ValueError(f"segment {self.source} [{self.in_}, {self.out}] must be at least 0.2s long")
        if self.reverse and self.out - self.in_ > MAX_REVERSE_SECONDS:
            # FFmpeg's reverse filter keeps every frame in RAM; long reversals are split into short pieces
            raise ValueError(f"reversed segments must be ≤{MAX_REVERSE_SECONDS:g}s of source (split longer ones)")
        return self

    @property
    def source_duration(self) -> float:
        return self.out - self.in_


class Sfx(_Model):
    """A generated sound effect at an output time (whoosh at cuts, flash pop)."""

    kind: Literal["whoosh", "pop"] = "whoosh"
    at: float = Field(ge=0)
    volume: float = Field(0.6, ge=0.0, le=2.0)


class VolumeRange(_Model):
    """The original sound's level over output start..end (gain_db -60 = muted)."""

    start: float = Field(ge=0)
    end: float = Field(gt=0)
    gain_db: float = Field(ge=-60.0, le=20.0)


class AudioSettings(_Model):
    music: str | None = None
    music_volume: float = Field(0.25, ge=0.0, le=1.0)
    ducking: bool = False
    duck_amount_db: float = Field(12.0, ge=0.0, le=30.0)
    voice_cleanup: bool = False
    target_lufs: float = Field(-16.0, ge=-30.0, le=-8.0)
    beat_sync: bool = False
    fade_in: float = Field(0.0, ge=0.0, le=5.0)   # audio fade at the very start (s)
    fade_out: float = Field(0.0, ge=0.0, le=5.0)  # audio fade at the very end (s)
    mute: bool = False                            # silence the original sound (music, if any, stays)
    music_start: float = Field(0.0, ge=0.0, le=3600.0)  # seconds into the song where the edit's music starts
    voice_volume: float = Field(1.0, ge=0.0, le=3.0)  # level of the video's own sound ("voice tej karo" = 1.8)
    bass_boost: float = Field(0.0, ge=0.0, le=12.0)  # dB of low-shelf boost on the final mix ("bass wala effect")
    # ---- Tier 1 audio tools (all neutral by default) ----
    gain_db: float = Field(0.0, ge=-30.0, le=20.0)    # exact level change of the final mix (measured, 2-pass)
    voice_eq: Literal["none", "clarity"] = "none"     # speech EQ: rumble cut, presence lift, de-harsh
    denoise: Literal["none", "light", "strong"] = "none"  # FFmpeg afftdn (LGPL) — no model file needed
    gate_threshold: float = Field(0.0, ge=0.0, le=0.5)  # denoise: a gate closes below this level (0 = no gate)
    reverb: float = Field(0.0, ge=0.0, le=1.0)        # echo / room (aecho), 0 = dry
    sfx: list[Sfx] = Field(default_factory=list, max_length=200)
    volume_ranges: list[VolumeRange] = Field(default_factory=list, max_length=50)
    exact_loudness: bool = False                       # measure the mix and correct to target_lufs (2-pass)


class ColorSettings(_Model):
    brightness: float = Field(0.0, ge=-1.0, le=1.0)
    contrast: float = Field(1.0, ge=0.0, le=2.0)
    saturation: float = Field(1.0, ge=0.0, le=3.0)
    warmth: float = Field(0.0, ge=-1.0, le=1.0)
    preset: ColorPreset = "none"
    gamma: float = Field(1.0, ge=0.3, le=3.0)
    # Per-clip exposure correction (clip id -> brightness offset) so different clips look consistent.
    clip_brightness: dict[str, float] = Field(default_factory=dict)

    @field_validator("clip_brightness")
    @classmethod
    def _clip_brightness_range(cls, v: dict[str, float]) -> dict[str, float]:
        for k, val in v.items():
            if not -0.25 <= val <= 0.25:
                raise ValueError(f"clip_brightness[{k}]={val} must be within [-0.25, 0.25]")
        return v

    def is_neutral(self) -> bool:
        return (self.preset == "none" and abs(self.brightness) < 1e-3 and abs(self.contrast - 1) < 1e-3
                and abs(self.saturation - 1) < 1e-3 and abs(self.warmth) < 1e-3 and abs(self.gamma - 1) < 1e-3)


class TextStyle(_Model):
    position: Literal["bottom", "center", "top", "top_right", "bottom_right", "bottom_left", "top_left"] = "bottom"
    size: int = Field(48, ge=12, le=480)  # font size in px at 1080 short side (scaled by renderer)
    color: str = Field("#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    box_color: str | None = Field("#7C5CFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    animation: TextAnimation = "none"
    font: str | None = Field(None, max_length=40, description="font id from text_styles.FONTS")
    outline_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    outline: float | None = Field(None, ge=0, le=20, description="outline px at 1080 (None = automatic)")
    shadow: float = Field(0.0, ge=0, le=20)
    glow: float = Field(0.0, ge=0, le=20, description="blur radius around the letters")
    uppercase: bool = False
    preset: str | None = Field(None, max_length=40)
    margin: float | None = Field(None, ge=0, le=0.45, description="distance from the edge as a share of the height")
    highlight: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$", description="karaoke: colour of the word being said")


class TextItem(_Model):
    kind: Literal["caption", "title", "watermark", "text"]
    text: str = Field(min_length=1, max_length=200)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    style: TextStyle = Field(default_factory=TextStyle)
    # text that follows a tracked person: (output seconds, x px, y px) of the point the text sits on
    track: list[list[float]] = Field(default_factory=list, max_length=2000)
    behind: bool = False  # drawn behind the people in the shot (person cut-out mask, cutmind/segmentation.py)
    # captions: when each word of `text` is SAID (seconds after `start`, one per word) — karaoke lights each word at
    # its real time instead of spreading the line evenly
    word_times: list[float] = Field(default_factory=list, max_length=60)

    @model_validator(mode="after")
    def _order(self) -> "TextItem":
        if self.end <= self.start:
            raise ValueError(f"text '{self.text[:20]}' end must be after start")
        return self


class Transition(_Model):
    type: TransitionType
    after: int = Field(ge=-2, description="segment index (by order); -1 = fade-in at start, -2 = fade-out at end")
    duration: float = Field(0.5, gt=0.05, le=2.0)


HexColor = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]


class Overlay(_Model):
    """Animated graphic layer ("graphic track"): gradient glow frame, colour wash, or lower bar."""

    kind: Literal["glow_frame", "wash", "bar"]
    label: str = Field("Gradient accent", max_length=60)
    colors: list[HexColor] = Field(min_length=2, max_length=4)
    motion: Literal["rotate", "drift", "static"] = "rotate"
    speed: float = Field(0.02, ge=0.0, le=0.2)   # gradient rotation speed (FFmpeg `gradients`)
    opacity: float = Field(0.9, gt=0.0, le=1.0)
    thickness: int = Field(10, ge=2, le=200)      # px at 720p short side: frame width / bar height
    start: float = Field(0.0, ge=0)
    end: float = Field(gt=0)

    @model_validator(mode="after")
    def _times(self) -> "Overlay":
        if self.end <= self.start:
            raise ValueError("overlay end must be after start")
        return self


class Sticker(_Model):
    """A small animated emoji sticker that pops up when the thing is SAID ("ye gulab dekho" -> a rose)."""

    emoji: str = Field(min_length=1, max_length=16)
    word: str = Field("", max_length=40)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    position: Literal["top_left", "top_right", "bottom_left", "bottom_right", "center"] = "top_right"
    size: float = Field(0.22, ge=0.08, le=0.5)  # share of the short side

    @model_validator(mode="after")
    def _times(self) -> "Sticker":
        if self.end <= self.start:
            raise ValueError("sticker end must be after start")
        return self


class Effect(_Model):
    type: EffectType
    target: int = Field(-1, ge=-1, description="segment index or -1 for all")
    strength: float = Field(1.0, gt=0.0, le=4.0)
    # beat_pulse: beat times in the segment's own output seconds (from the music's beat grid)
    times: list[float] = Field(default_factory=list, max_length=400)
    # follow / person_zoom / spotlight: subject path (segment seconds, cx, cy, w, h), normalised source coordinates
    points: list[list[float]] = Field(default_factory=list, max_length=600)
    # keyframes effect: the easing between keys (engines/motion.py EASINGS)
    easing: str | None = Field(None, max_length=20)
    # Tier 1 tools: named settings of a parametric effect (grade: brightness/contrast/…; crop / censor: x y w h)
    params: dict[str, float | str] = Field(default_factory=dict)


class Graphic(_Model):
    """One item of the graphics track, drawn over the edit between start and end (output seconds).

    layer        another clip's PICTURE (B-roll, picture-in-picture, split screen); its sound is not used
    box / ring / arrow   a highlight shape;  progress   a bar that fills with time
    blur / pixelate      a censor region;    light_leak a moving warm glow;  image  a logo / sticker file
    Positions are shares of the frame (0..1), so they survive aspect changes.
    """

    kind: Literal["layer", "box", "ring", "arrow", "progress", "blur", "pixelate", "light_leak", "image"]
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    x: float = Field(0.0, ge=-1.0, le=2.0)
    y: float = Field(0.0, ge=-1.0, le=2.0)
    w: float = Field(1.0, gt=0.0, le=2.0)
    h: float = Field(1.0, gt=0.0, le=2.0)
    source: str | None = Field(None, max_length=200)  # layer: clip id; image: file name in the project
    src_in: float = Field(0.0, ge=0)
    fit: Literal["crop", "fit"] = "crop"
    color: str = Field("#FFD60A", pattern=r"^#[0-9A-Fa-f]{6}$")
    opacity: float = Field(1.0, gt=0.0, le=1.0)
    strength: float = Field(1.0, gt=0.0, le=4.0)
    border: float = Field(0.0, ge=0.0, le=0.05)       # layer outline (share of the short side)
    animate: Literal["none", "fade", "pop", "slide"] = "none"
    angle: float = Field(0.0, ge=-360.0, le=360.0)    # arrow direction (degrees, 0 = pointing right)

    @model_validator(mode="after")
    def _times(self) -> "Graphic":
        if self.end <= self.start:
            raise ValueError("graphic end must be after start")
        return self


class AudioEdit(_Model):
    """J-cut ("j": the next shot's sound starts `seconds` early) / L-cut ("l": this shot's sound runs on)."""

    after: int = Field(ge=0)
    kind: Literal["j", "l"]
    seconds: float = Field(gt=0.0, le=3.0)


class Decision(_Model):
    """Why an edit was made — shown to the user and kept with the plan."""

    decision: str = Field(max_length=120)
    where: str = Field("", max_length=160)
    reason: str = Field(max_length=300)
    skill: str = Field("", max_length=60)


class ExportSettings(_Model):
    format: Literal["mp4"] = "mp4"
    video_codec: Literal["libx264"] = "libx264"
    crf: int = Field(23, ge=14, le=35)
    preset: Literal["ultrafast", "veryfast", "faster", "fast", "medium"] = "veryfast"
    audio_bitrate: Literal["96k", "128k", "192k"] = "128k"
    # extra deliverables made next to the MP4: an animated GIF, the soundtrack (mp3 / wav / m4a), a cover image,
    # an .srt of the captions
    extras: list[Literal["gif", "mp3", "wav", "m4a", "thumbnail", "srt"]] = Field(default_factory=list)
    platform: str | None = Field(None, max_length=40)       # export preset id (tools/b_delivery.PLATFORMS)
    max_bitrate_kbps: int | None = Field(None, ge=300, le=100000)
    thumbnail_at: float | None = Field(None, ge=0)


@dataclass(frozen=True)
class TimelineEntry:
    index: int              # position in output order
    segment: ClipSegment
    duration: float         # output duration of the segment (after speed / speed ramp)
    start: float            # output start time
    end: float              # output end time


def segment_output_duration(seg: ClipSegment, effects: list[Effect], index: int) -> float:
    """Output duration of a segment. A speed ramp plays the second half at `strength`x."""
    base = seg.source_duration / seg.speed
    ramp = next((e for e in effects if e.type == "speed_ramp" and e.target in (-1, index)), None)
    if ramp is None or ramp.strength == 1.0:
        return base
    half = base / 2
    return half + half / ramp.strength


class Focus(_Model):
    """Main focus on one person (picked by clothes colour, else the biggest): the rest blurred or darkened."""

    mode: Literal["blur", "dim"] = "blur"
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class EditPlan(_Model):
    version: str = PLAN_VERSION
    canvas: Canvas = Field(default_factory=Canvas)
    clips: list[ClipSegment] = Field(min_length=1)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    color: ColorSettings = Field(default_factory=ColorSettings)
    text: list[TextItem] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    effects: list[Effect] = Field(default_factory=list)
    overlays: list[Overlay] = Field(default_factory=list, max_length=6)
    stickers: list[Sticker] = Field(default_factory=list, max_length=12)
    style: str | None = Field(None, max_length=40)  # named look (see cutmind/styles.py)
    decisions: list[Decision] = Field(default_factory=list, max_length=400)
    focus: Focus | None = None
    export: ExportSettings = Field(default_factory=ExportSettings)
    graphics: list[Graphic] = Field(default_factory=list, max_length=60)
    audio_edits: list[AudioEdit] = Field(default_factory=list, max_length=100)

    @field_validator("version")
    @classmethod
    def _version(cls, v: str) -> str:
        if v != PLAN_VERSION:
            raise ValueError(f"unsupported plan version {v!r}, expected {PLAN_VERSION}")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> "EditPlan":
        orders = [c.order for c in self.clips]
        if len(set(orders)) != len(orders):
            raise ValueError("clip orders must be unique")
        n = len(self.clips)
        durations = [segment_output_duration(s, self.effects, i) for i, s in enumerate(self.ordered_clips())]
        seen: set[int] = set()
        for t in self.transitions:
            if t.after in seen:
                raise ValueError(f"duplicate transition at position {t.after}")
            seen.add(t.after)
            if t.after >= 0:
                if t.after >= n - 1:
                    raise ValueError(f"transition after segment {t.after} has no following segment")
                limit = min(durations[t.after], durations[t.after + 1]) * 0.5
                if t.duration > limit:
                    raise ValueError(
                        f"transition after segment {t.after} ({t.duration}s) is longer than half its neighbours"
                    )
            elif t.duration > durations[0 if t.after == FADE_IN else -1]:
                raise ValueError("fade is longer than the segment it applies to")
        for e in self.effects:
            if e.target >= n:
                raise ValueError(f"effect {e.type} targets segment {e.target} but there are only {n}")
        total = self.total_duration()
        for ov in self.overlays:
            if ov.start >= total or ov.end > total + 0.05:
                raise ValueError(f"overlay '{ov.label}' ({ov.start}-{ov.end}s) is outside the video ({total:.2f}s)")
        for g in self.graphics:
            if g.start >= total or g.end > total + 0.05:
                raise ValueError(f"{g.kind} graphic ({g.start}-{g.end}s) is outside the video ({total:.2f}s)")
        for a in self.audio_edits:
            if a.after >= n - 1:
                raise ValueError(f"audio edit after segment {a.after} has no following segment")
        for st in self.stickers:
            if st.start >= total or st.end > total + 0.05:
                raise ValueError(f"sticker {st.word or st.emoji} ({st.start}-{st.end}s) is outside the video ({total:.2f}s)")
        for item in self.text:
            if item.start >= total or item.end > total + 0.05:
                raise ValueError(f"text '{item.text[:20]}' ({item.start}-{item.end}s) is outside the video ({total:.2f}s)")
        return self

    # ---- helpers -------------------------------------------------------------------------------
    def ordered_clips(self) -> list[ClipSegment]:
        return sorted(self.clips, key=lambda c: c.order)

    def overlap_after(self, index: int) -> float:
        t = next((t for t in self.transitions if t.after == index), None)
        return t.duration if t else 0.0

    def timeline(self) -> list[TimelineEntry]:
        """Map every segment to its output [start, end], accounting for transition overlaps."""
        out: list[TimelineEntry] = []
        cursor = 0.0
        for i, seg in enumerate(self.ordered_clips()):
            dur = segment_output_duration(seg, self.effects, i)
            out.append(TimelineEntry(i, seg, dur, cursor, cursor + dur))
            cursor += dur - self.overlap_after(i)
        return out

    def total_duration(self) -> float:
        tl = self.timeline()
        return tl[-1].end if tl else 0.0

    def source_to_output(self, source: str, t: float) -> float | None:
        """Output time at which source time `t` of clip `source` is shown (None if cut out)."""
        for entry in self.timeline():
            seg = entry.segment
            if seg.source == source and seg.in_ <= t <= seg.out:
                frac = (t - seg.in_) / seg.source_duration
                return entry.start + frac * entry.duration
        return None

    def to_json(self) -> dict:
        return self.model_dump(by_alias=True, mode="json")
