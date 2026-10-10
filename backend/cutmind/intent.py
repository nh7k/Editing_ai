"""Prompt → Intent. The Director uses the deterministic parser here in mock mode (and as LLM fallback)."""

from __future__ import annotations

import functools
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from .fx_catalog import ALL_FX, LUT_LOOKS, TEXT_ANIMATIONS
from .plan import AspectRatio, ColorPreset, EffectType, TextAnimation, TransitionType


class TimedEffect(BaseModel):
    """An effect for part of the video: "starting ke 3s me zoom", "last 5 seconds black and white"."""

    effect: EffectType
    start: float = Field(0.0, ge=0, le=600, description="output seconds (from the end when from_end)")
    end: float | None = Field(None, ge=0, le=600, description="None = until the end")
    from_end: bool = False
    strength: float = Field(1.0, ge=0.2, le=3.0, description='"bahut zoom" = stronger')
    preset: str | None = Field(None, max_length=30, description="keyframes effect: a motion preset (engines/motion.py)")
    easing: str | None = Field(None, max_length=20)


class TimedText(BaseModel):
    """Text at one moment of the edit (a timeline comment: "WOW likh do" at 4.2 s). Output seconds."""

    text: str = Field(min_length=1, max_length=80)
    start: float = Field(ge=0, le=3600)
    end: float = Field(gt=0, le=3600)


class Intent(BaseModel):
    """What the user asked for, in structured form."""

    target_duration: float | None = Field(None, gt=0, le=600, description="seconds")
    aspect_ratio: AspectRatio | None = None
    resolution: Literal[360, 480, 720, 1080] | None = None
    color_preset: ColorPreset | None = None
    brightness: float = Field(0.0, ge=-0.5, le=0.5, description="extra brightness requested")
    captions: bool = False
    remove_silence: bool = False
    remove_fillers: bool = False
    fast_cuts: bool = False
    slow_motion: bool = False
    music: bool = False
    beat_sync: bool = False
    music_mood: Literal["upbeat", "calm"] | None = None
    transition: TransitionType | None = None
    effects: list[EffectType] = Field(default_factory=list)
    timed_effects: list[TimedEffect] = Field(default_factory=list, max_length=40)
    # timeline comments (cutmind/moment.py): text / stickers at a moment, parts cut out ([clip id, source in, out])
    timed_texts: list[TimedText] = Field(default_factory=list, max_length=40)
    moment_stickers: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    exclude_ranges: list[list[Any]] = Field(default_factory=list, max_length=40)
    text_restyles: list[dict[str, Any]] = Field(default_factory=list, max_length=40)  # {at, color, scale, remove}
    from_comment: bool = False      # this message is a timeline comment (changes only its moment)
    bass_boost: bool = False  # "bass wala effect": heavier low end + a zoom punch on every beat
    title: str | None = Field(None, max_length=80)
    voice_cleanup: bool = False
    order: Literal["original", "reverse", "best", "smart"] = "original"
    auto: bool = False  # "mast sa edit kar do": the Director picks a full edit itself (see agents/director.py)
    # --- extra FFmpeg operations ---
    rotate: Literal[0, 90, 180, 270] = 0
    flip: Literal["none", "h", "v", "hv"] = "none"
    reverse_playback: bool = False
    fps: Literal[24, 25, 30, 50, 60] | None = None
    gamma: float = Field(1.0, ge=0.3, le=3.0)
    mute: bool = False
    loudness: Literal["normal", "louder", "quieter"] = "normal"
    audio_fade: bool = False
    watermark: str | None = Field(None, max_length=40)
    remove_idle: bool = False
    export_gif: bool = False
    export_mp3: bool = False
    # --- pro looks & variations (see cutmind/styles.py) ---
    style: Literal["midnight_drift", "violet_authority", "cyan_kinetic"] | None = None
    variations: int = Field(1, ge=1, le=3)
    text_animation: TextAnimation = "none"
    # --- text look & person tracking ---
    text_style: str | None = Field(None, max_length=40, description="text preset id (text_styles.TEXT_PRESETS)")
    text_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    track_target: Literal["person", "face"] = "person"
    tracked_text: str | None = Field(None, max_length=60, description="text that follows the tracked person")
    # --- editorial knobs (set by the editorial brain from skills, see cutmind/editorial.py) ---
    genres: list[str] = Field(default_factory=list)
    platform: str | None = None
    cut_length: float | None = Field(None, ge=0.3, le=10.0, description="seconds per cut for fast / beat cuts")
    target_lufs: float | None = Field(None, ge=-30, le=-8)
    hook_first: bool = False
    ending_peak: bool = False
    emphasis_punch: bool = False   # small punch-in on important spoken words
    jumpcut_cover: bool = False    # alternate a subtle crop on consecutive jump cuts
    flash_accents: int = Field(0, ge=0, le=4)
    caption_words: int | None = Field(None, ge=1, le=8)
    color_pass: bool = False        # some shots high-contrast black & white, on the rhythm (fan edits)
    kinetic_text: bool = False      # big single words landing on the beat
    kinetic_words: list[str] = Field(default_factory=list, max_length=12)
    text_behind: bool = False       # big text drawn BEHIND the people in the shot (person cut-out)
    lyrics: bool = False            # kinetic words = the sung words of the song, on the moment they are sung
    voice_boost: bool = False       # the voice of the video louder / clearer, music kept under it
    ducking: bool = False           # "duck the music under the voice": music dips while someone talks
    music_volume: float | None = Field(None, ge=0.0, le=1.0, description="background music level asked for")
    use_my_song: bool = False       # use the song the user uploaded to this project
    text_front: bool = False        # "caption aage lao": text in front of the person (never behind)
    captions_behind: bool = False   # captions drawn behind the person
    track_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$", description="the person to follow: clothes colour")
    focus: Literal["blur", "dim"] | None = None  # main focus on one person: the rest blurred / darkened
    avoid: list[str] = Field(default_factory=list, description="things the user said NOT to do (bw, zoom, glitch, text…)")
    use_reference: bool = False     # edit like the reference video the user uploaded (its rhythm, colour, song)
    slow_end: bool = False          # "end me slow motion": only the closing shot in slow motion
    restore_audio: bool = False     # "audio nahi aa raha / pehle jaisa audio la do": unmute, normal voice level
    no_music: bool = False          # "gaana hata do": no music, also not the one remembered from the last edit
    restore_color: bool = False     # "color wapas lao": no B&W / colour grade, also not the remembered one
    word_stickers: bool = False     # vlog: a thing that is SAID ("ye gulab dekho") pops up as an emoji sticker
    end_text: str | None = Field(None, max_length=80)  # "last me The End likh do": text on the closing seconds
    drop_clips: list[int] = Field(default_factory=list)  # "pehla clip hata do": clip positions to leave out (1-based, -1 = last)
    length_change: float | None = Field(None, ge=0.2, le=4.0)  # "thoda chhota karo" 0.7 / "lamba karo" 1.4 (× current)
    text_scale: float | None = Field(None, ge=0.3, le=3.0)     # "text bada karo" 1.5 / "chhota" 0.7
    pace_change: float | None = Field(None, ge=0.25, le=4.0)  # "thoda slow karo" 1.5 / "thoda fast" 0.67: shot length x
    speed_moves: bool = False       # fan edits: one stutter (a moment shown 3x) and one half-speed takeoff ramp
    impact_hits: bool = False       # fan edits: zoom-blur + RGB-split hits on chosen cuts
    inferred_fields: list[str] = Field(default_factory=list, description="fields the editorial brain filled in")
    remove: list[str] = Field(default_factory=list, description="things to take out of the current edit")
    limits: dict[str, int] = Field(default_factory=dict, description="restraint limits from the editorial skills")
    recognized: list[str] = Field(default_factory=list, description="human-readable list of understood instructions")

    def is_empty(self) -> bool:
        return not self.recognized


class PromptError(ValueError):
    """Prompt is unusable (empty, too long, …)."""


MIN_PROMPT_LEN = 3
MAX_PROMPT_LEN = 1000


def validate_prompt(prompt: str) -> str:
    cleaned = " ".join((prompt or "").split())
    if len(cleaned) < MIN_PROMPT_LEN:
        raise PromptError("Prompt is empty or too short. Describe the edit, e.g. 'trim to 15s and add captions'.")
    if len(cleaned) > MAX_PROMPT_LEN:
        raise PromptError(f"Prompt is too long ({len(cleaned)} chars, max {MAX_PROMPT_LEN}).")
    return cleaned


# "ulti sidhi footage" / "arrange kar do": put the clips in the order they were filmed
SMART_ORDER = (r"\barrange", r"\bsort\b", r"organi[sz]e", r"chronolog", r"(right|correct|proper|sahi|theek|thik) (order|sequence)",
               r"\bin order\b", r"order (me|mein|se) (laga|rakh|kar|set)", r"set kar", r"jama (do|de|ke)", r"line se",
               r"ult[aie]\s*-?\s*sidh?[aie]", r"aage\s*-?\s*pee?chh?e", r"jumbled", r"mixed.?up", r"\bmessy\b",
               r"random order", r"\bstory\s*(line|wise|order)", r"timeline (order|wise)")
# "mast sa edit kar do", "make it look amazing": the user wants the agents to decide everything
AUTO_EDIT = (r"\bmast\b", r"badh?iya", r"jhakaa?s", r"[zj]abardast", r"dhamaa?kedaa?r", r"\bauto.?edit", r"\bautomatic",
             r"\bmagic\b", r"surprise me", r"you decide", r"your choice", r"\bkhud (se|hi|decide)", r"apne (aap|hisaab)",
             r"kuch bhi (kar|daal)", r"jo (bhi )?(accha|acha|achha|sahi) (lage|ho)",
             r"\b(acch?h?a|achh?a|sundar|cool|nice|awesome|amazing|great|killer|epic|banger|lit|fire|viral|trending|"
             r"professional|stunning|crazy|best)\s+((sa|si|se|wala|wali)\s+)?(edit|video|reel|clip)",
             r"make (it|this|the video) (look |sound )?(good|great|better|nice|cool|awesome|amazing|pro|professional|"
             r"viral|epic|stunning|engaging)", r"edit (it )?(like|for) (a )?(youtuber|creator|influencer)",
             r"\b(do|make) (your|the) (best|magic)",
             # "video boring hai kuch karo": the user wants it more interesting and leaves the how to the agents
             r"\bboring\b(?!.{0,15}\b(hata|nikal|remove|cut|part|hissa|hisse|wala|wale)\b)", r"\bkuch (karo|kar do|kar de|karke)\b",
             r"(interesting|engaging|achha|accha|better) (bana|banao|karo|kar do)", r"\bjaan daal")
BASS = (r"\bbass\b", r"\bba(s|se)\s+(ki tarah|jaisa|jaise|wala|wali|effect|boost|drop|heavy)", r"\bdhamak", r"\bthump",
        r"\bbeat drop")

# ---- effects for part of the video ------------------------------------------------------------------------
_UNIT = r"\s*-?\s*(?:s|sec|secs|second|seconds)\b"
_NUM = r"(\d+(?:\.\d+)?)"
_SEP = re.compile(r",|;|\.(?=\s)|\b(or|aur|and|phir|fir|then|uske baad|iske baad|after that|baad me|baad mein)\b")
_CONTINUE = {"phir", "fir", "then", "uske baad", "iske baad", "after that", "baad me", "baad mein"}
_W_RANGE = re.compile(_NUM + r"(?:" + _UNIT + r")?\s*(?:se|to|-|till|until)\s*" + _NUM + _UNIT)
_W_LAST = re.compile(r"(?:last|aakhri|akhri|ending|end|ant)\s*(?:ki|ke|ka|of the|of)?\s*" + _NUM + _UNIT)
_W_AFTER = re.compile(r"(?:after|baad)\s*" + _NUM + _UNIT + r"|" + _NUM + _UNIT + r"\s*(?:ke baad|baad|after|onwards?)")
_W_FIRST = re.compile(r"(?:starting|start|shuruaat|shuru|pehle|pehla|first|initially|initial|beginning|opening)\s*"
                      r"(?:ki|ke|ka|of the|of)?\s*" + _NUM + _UNIT)
_W_WITHIN = re.compile(_NUM + _UNIT + r"\s*(?:tak|me|mein|ke andar)\b")
# "starting me zoom karo" (no number): the opening ~3 s
_W_START = re.compile(r"\b(?:starting|start|shuruaat|shuru|beginning|opening|intro)\s*(?:me|mein|main|pe|par|at|in|of the video|mai)\b"
                      r"|\bat the (?:start|beginning)\b|\bin the beginning\b")
_STRONG = re.compile(r"\b(bahut|bohot|bhot|bahot|zyada|jyada|very|heavy|strong|full|extreme|tez|hard)\b")


def _clause_effects(c: str) -> list[str]:
    found = [f.id for f in ALL_FX if f.category in ("motion", "video_effect") and f.keywords and _has(c, *f.keywords)]
    if "zoom_out" in found and "zoom" in found and not _has(c, r"zoom.?in"):
        found.remove("zoom")
    if re.search(_BW_WORDS, c) and "mono" not in found:
        found.append("mono")
    return found


def parse_timed_effects(p: str) -> tuple[list[TimedEffect], list[tuple[int, int]]]:
    """"starting ke 3s me zoom in, phir zoom out", "last 5 sec black and white", "2s se 6s tak glitch".

    Returns the timed effects and the character spans of the numbers used for timing (so the duration
    parser doesn't read "3s" as "make the video 3 seconds long" — a real bug on a user prompt)."""
    out: list[TimedEffect] = []
    spans: list[tuple[int, int]] = []
    pos, cont, prev_end = 0, False, None
    # "black and white" is one thing, not two clauses joined by "and" (same length keeps the spans right)
    p = re.sub(r"black and white", "black_and_white", p)
    pieces: list[tuple[int, str, bool]] = []
    for m in _SEP.finditer(p):
        pieces.append((pos, p[pos:m.start()], cont))
        cont = (m.group(1) or "") in _CONTINUE or (cont and not p[pos:m.start()].strip())
        pos = m.end()
    pieces.append((pos, p[pos:], cont))
    for off, clause, after_prev in pieces:
        if not clause.strip():
            continue
        fx = _clause_effects(clause)
        window: tuple[float, float | None, bool] | None = None
        m, kind = None, ""
        for rx, kind in ((_W_RANGE, "range"), (_W_LAST, "last"), (_W_AFTER, "after"), (_W_FIRST, "first"),
                         (_W_WITHIN, "within"), (_W_START, "start")):
            m = rx.search(clause)
            if m:
                nums = [float(g) for g in m.groups() if g] or [3.0]
                window = {"range": (nums[0], nums[-1], False), "last": (nums[0], None, True),
                          "after": (nums[0], None, False), "first": (0.0, nums[0], False),
                          "within": (0.0, nums[0], False), "start": (0.0, 3.0, False)}[kind]
                break
        if fx and window is None and after_prev and prev_end is not None:
            window = (prev_end, None, False)  # "... phir zoom out" continues where the last one stopped
        if not fx or window is None:
            if m is not None and kind not in ("within", "start"):  # "last 5 sec ..." is a time range, never the length
                spans.append((off + m.start(), off + m.end()))
            continue
        start, end, from_end = window
        if end is not None and end <= start:
            continue
        if m is not None and kind != "start":
            spans.append((off + m.start(), off + m.end()))
        strength = 1.8 if _STRONG.search(clause) else 1.0
        for e in fx:
            out.append(TimedEffect(effect=e, start=start, end=end, from_end=from_end, strength=strength))
        prev_end = end if not from_end else None
    return out[:12], spans


def describe_timed(t: TimedEffect) -> str:
    from .fx_catalog import EFFECTS_BY_ID

    fx = EFFECTS_BY_ID.get(t.effect)
    name = fx.name.lower() if fx else t.effect.replace("_", " ")
    if t.strength > 1.2:
        name = f"strong {name}"
    if t.from_end:
        return f"{name} for the last {t.start:g} seconds"
    if t.end is None:
        return f"{name} after {t.start:g} seconds"
    if t.start == 0:
        return f"{name} for the first {t.end:g} seconds"
    return f"{name} from {t.start:g} to {t.end:g} seconds"


ANIM_ORDER = ("karaoke", "typewriter", "cascade", "wave", "color_cycle", "glow_pulse", "heartbeat", "flicker", "zoom_in",
              "zoom_out", "spin_in", "flip_in", "blur_in", "drop_in", "fly_left", "fly_right", "slide_up", "swing", "shake",
              "stretch", "bounce", "pop", "fade")
_TEXT_WORDS = r"(text|captions?|subtitles?|title|font|letters|likha|naam|name)"
_FOLLOW_TEXT = (r"(text|naam|name|label|tag|likh\w*).{0,40}(follow|track|upar|upr|above|on top|sar (pe|par)|saath|sath|uske|us ke)",
                r"(follow|track)\w*.{0,30}(text|naam|name|label|tag)", r"name ?tag",
                r"(upar|upr|above|on top|sar (pe|par)).{0,40}[\"“'‘].{1,60}[\"”'’].{0,20}(likh|text|naam|aaye|aye|dikhe|ho)")
_BW_WORDS = r"black[ _](and|&|n)[ _]white|\bb ?& ?w\b|\bbw\b|monochrome|grayscale|greyscale"


def _mask(p: str, pattern: str) -> tuple[str, bool]:
    hit = False

    def blank(m: re.Match[str]) -> str:
        nonlocal hit
        hit = True
        return " " * len(m.group(0))
    return re.sub(pattern, blank, p), hit


def extract_text_look(p: str) -> tuple[str, dict[str, Any]]:
    """Text preset, text colour and text animation, with their words blanked out of the prompt."""
    from .text_styles import COLOR_WORDS, TEXT_PRESETS

    look: dict[str, Any] = {"preset": None, "color": None, "anim": None}
    # presets: an explicit "<name> text style" wins over a keyword of another preset
    for pid, pr in TEXT_PRESETS.items():
        p, hit = _mask(p, rf"\b{re.escape(pr.name.lower())} (text )?style")
        if hit and look["preset"] is None:
            look["preset"] = pid
    if look["preset"] is None:
        for pid, pr in TEXT_PRESETS.items():
            for kw in pr.keywords:
                p, hit = _mask(p, kw)
                if hit and look["preset"] is None:
                    look["preset"] = pid
            if look["preset"]:
                break
    # "text colour black to white" / "kaale se safed": the colour it should BECOME is the last one
    cw = "|".join(COLOR_WORDS)
    m = re.search(rf"\b({cw})\s+(?:to|se|into|->|→|ki jagah|ke badle)\s+({cw})\b", p)
    change_to = (m.group(2), COLOR_WORDS[m.group(2)]) if m and re.search(
        _TEXT_WORDS + r"|\bcolou?r\b|\brang\b", p) else None
    if change_to:
        p = p[:m.start()] + p[m.start():m.end()].replace(m.group(1), " " * len(m.group(1)), 1) + p[m.end():]
    for word, hexv in COLOR_WORDS.items():
        for pat in (rf"\b{word} {_TEXT_WORDS}", rf"{_TEXT_WORDS} (ka |ki |ko )?(rang |colou?r )?{word}\b"):
            m = re.search(pat, p)
            if m:
                if look["color"] is None:
                    look["color"] = (word, hexv)
                # keep the word "captions"/"title" readable for the caption/title parsers: blank only the colour
                p = p[:m.start()] + m.group(0).replace(word, " " * len(word)) + p[m.end():]
    if change_to:
        look["color"] = change_to
        p = re.sub(rf"\b{change_to[0]}\b", " " * len(change_to[0]), p)
    for anim in ANIM_ORDER:
        for kw in TEXT_ANIMATIONS[anim][1]:
            m = re.search(kw, p)
            if m and look["anim"] is None:
                look["anim"] = anim
            if m:
                keep = m.group(0)
                for word in ("captions", "caption", "subtitles", "title"):
                    keep = keep.replace(word, "\0" * len(word))
                blanked = "".join(c if c == "\0" else " " for c in keep)
                orig = m.group(0)
                p = p[:m.start()] + "".join(o if b == "\0" else " " for o, b in zip(orig, blanked, strict=True)) + p[m.end():]
        if look["anim"]:
            break
    if look["preset"] == "hormozi" and look["anim"] is None:
        look["anim"] = "karaoke"  # Hormozi-style captions = big words, the spoken one highlighted
    return p, look


def _parse_text_and_subject(p: str, raw: str, it: Intent, rec: list[str]) -> None:
    """Text presets / colours, which subject to track, and text that follows the person."""
    if _has(p, r"\bface\b", r"chehr", r"\bmukh"):
        it.track_target = "face"
    if _has(p, *_FOLLOW_TEXT):
        m = re.search(r"[\"“'‘]([^\"”'’]{1,60})[\"”'’]", raw)
        if m and not re.search(r"title\s*[:=]?\s*[\"“']" + re.escape(m.group(1)), raw, re.I):
            it.tracked_text = m.group(1).strip()
            rec.append(f"text '{it.tracked_text}' that follows the {it.track_target}")


def _preset_names() -> dict[str, str]:
    from .text_styles import TEXT_PRESETS

    return {k: v.name for k, v in TEXT_PRESETS.items()}


TEXT_PRESETS_NAMES = _preset_names()

REMOVALS: dict[str, tuple[str, ...]] = {
    "captions": (r"(captions?|subtitles?)\s*(hata|nikal|remove|band|mat|off|nahi chahiye|bakwas)",
                 r"(remove|no|without|hide|delete)\s+(the\s+)?(captions?|subtitles?)"),
    "transition": (r"transitions?\s*(hata|nikal|remove|band|mat|bakwas|nahi chahiye)", r"(remove|no|without)\s+(the\s+)?transitions?"),
    "effects": (r"effects?\s*(hata|nikal|remove|band|mat|off|bakwas)", r"(remove|no|without)\s+(the\s+)?effects?",
                r"zyada flashy", r"too flashy", r"simple (kar|rakh)"),
    "word_stickers": (r"(stickers?|emojis?)\s*(hata|nikal|remove|band|mat|off|nahi chahiye|bakwas)",
                      r"(remove|no|without|hide|delete)\s+(the\s+)?(stickers?|emojis?)"),
}

NO_MUSIC = (r"\b(no|without|bina|zero)\s+(background\s+|any\s+)?(music|songs?|bgm|gaa?n[ae])",
            r"\b(music|songs?|bgm|gaa?n[ae])\s+(mat|nahi|nahin|na)\b", r"\b(don'?t|do not)\s+add\s+(any\s+)?(music|songs?)")
GENERIC_EDIT = (r"\bedit\b", r"\bbana (do|de|ke)", r"\bkar (do|de)\b", r"video (bana|kar)")


_SOUND = r"(voice|vocals?|awaa?z|sound|audio|music|gaa?n[ae]|song|bgm)"
_ORIGINAL = r"(original|video|clip|asli|purani|pehle wali|existing|current)\S*\s+(ki|ka|ke|wali|wala|of the video)?\s*"
_REPLACE = (r"(uske|iske|us ki|is ki)\s+(jagah|badle)", r"\binstead\b", r"replace", r"\b(dusra|doosra|koi aur|another|new|naya|second)\s+"
            r"(gaa?n[ae]|song|music|track|bgm)", r"(gaa?n[ae]|song|music)\s+(badal|change)")


def _parse_audio_controls(p: str, it: "Intent", rec: list[str]) -> None:
    """Sound requests: take the video's own voice / music out, put another song in, voice louder with a soft music
    bed, music level, the user's own uploaded song, lyrics as text, text behind the person."""
    replace = _has(p, *_REPLACE)
    remove_original = _has(p, _ORIGINAL + _SOUND + r"\s*(ko\s*)?(hata|nikal|remove|band|mute|off|delete|badal|change|replace)",
                           r"(remove|delete|mute|replace|change)\s+(the\s+)?(original|video'?s?|clip'?s?|existing|current)\s+"
                           + _SOUND, r"(voice|vocals?|awaa?z)\s*(ko\s*)?(hata|nikal|band|remove|mute|off)")
    if remove_original or (replace and _has(p, r"(original|video|clip)\S*\s+(ki|ka|ke|'?s)?\s*" + _SOUND)):
        if not it.mute:
            it.mute = True
            rec.append("original sound removed")
    if replace or (remove_original and _has(p, r"\b(lagao|laga do|laga de|add|daal|dal do|put)\b")):
        if not it.music:
            it.music, it.music_mood = True, it.music_mood or "upbeat"
            rec.append("new music")
    elif _has(p, r"\b(music|gaa?n[ae]|song|bgm)\s*(ko\s*)?(hata|nikal|remove|band)", r"remove (the )?(music|song|bgm)") \
            and not remove_original:
        it.music = False  # "music hata do" = no added music
        rec[:] = [r for r in rec if not r.endswith(" music")]
        rec.append("no music")
    if _has(p, r"(voice|vocals?|awaa?z|dialogue|baat|speech)\s*(ko\s*)?(thoda\s*)?"
               r"(te[zj]|loud|louder|zyada|badha|boost|upar|high)",
            r"(boost|increase|raise|louder|clearer)\s+(the\s+)?(voice|vocals|dialogue|speech)", r"voice (up|boost)"):
        it.voice_boost = True
        rec.append("voice louder")
    if _has(p, r"\bduck(ing|s|ed)?\b", r"music under (the )?(voice|speech|talking)",
            r"bolte (waqt|samay) (gaa?n[ae]|music) (dheem\w*|kam|neeche)", r"(awaa?z|voice) ke neeche (music|gaa?n[ae])"):
        it.ducking = True
        if not it.music:
            it.music = True
        rec.append("music ducked under the voice")
    if _has(p, r"(background|bg|peeche|piche)\s*(me|mein|main|in)?\s*(ek\s+)?(second|dusra|doosra|koi|halka|soft)?\s*"
               r"(music|gaa?n[ae]|song|bgm|track)", r"\b(second|another|background) (music|song|track)\b"):
        if not it.music:
            it.music, it.music_mood = True, it.music_mood or ("calm" if it.voice_boost else "upbeat")
            rec.append("background music")
    if _has(p, r"(music|gaa?n[ae]|song|bgm)\s*((ki|ka|ke|ko)\s+)?((awaa?z|volume|sound)\s+)?(ko\s*)?"
               r"(thod[aie]\s*|zara\s*|bahut\s*)?(halka|dheem\w*|dheere|dhima|soft|low|kam|neeche)",
            r"(low|soft|light|quiet|halka)\s+(background\s+)?(music|bgm|gaa?n[ae])"):
        it.music_volume = 0.12
        rec.append("music soft")
    elif _has(p, r"(music|gaa?n[ae]|song|bgm)\s*((ki|ka|ke|ko)\s+)?((awaa?z|volume|sound)\s+)?(ko\s*)?"
                 r"(thod[aie]\s*|zara\s*|bahut\s*)?(te[zj]|loud|zyada|upar|full|badha\w*)\b", r"loud music"):
        it.music_volume = 0.6
        rec.append("music loud")
    if _has(p, r"\b(my|mera|meri|mere|apna|apni|uploaded|upload kiya|is|this|ye|yeh)\s+(own\s+|wala\s+|wali\s+)?"
               r"(song|gaa?n[ae]|music|track|audio)\b"):
        it.use_my_song = True
        it.music = True
        it.music_mood = it.music_mood or "upbeat"
        rec.append("your song")
    if _has(p, r"\blyrics?\b", r"gaa?ne ke (bol|words|shabd|lyrics)", r"song (words|text)", r"words of the song", r"\bbol\b.{0,15}(text|likh)"):
        it.lyrics = True
        it.kinetic_text = True
        it.music = True
        it.music_mood = it.music_mood or "upbeat"
        rec.append("lyrics as text")
    if _has(p, r"(text|words?|title|naam|likh\w*)\b.{0,30}\b(behind|peeche|piche|pichhe)\b",
            r"behind (the )?(person|player|subject|him|her|people|me|body|guy|girl)",
            r"(person|player|banda|bande|insaan|ladka|ladki)\w* ke (peeche|piche|pichhe)"):
        it.text_behind = True
        rec.append("text behind the person")


_TEXT_REF = r"(text|captions?|subtitles?|words?|lyrics?|naam|name|title|likh\w*|shabd)"
_AAGE = r"(aage|agey|aagey|front|saamne|samne)"
_PEECHE = r"(behind|peeche|piche|pichhe|peechhe)"
_PERSON = r"(person|player|banda|bande|insaan|ladka|ladki|aadmi|guy|girl|man|woman|him|her|people|log)"


def _parse_placement_and_focus(p: str, it: "Intent", rec: list[str]) -> None:
    """Text in front of / behind the person, and "blue shirt wale pe focus karo, baaki blur"."""
    from .text_styles import COLOR_WORDS

    front = _has(p, _TEXT_REF + r".{0,60}\b" + _AAGE + r"\b.{0,20}(lao|laao|karo|kar do|kar de|rakho|dikhao|aaye|aye|chahiye|"
                                                           r"hona|ho)\b",
                 r"(bring|put|move|keep)\s+(the\s+)?" + _TEXT_REF + r".{0,25}\bfront\b",
                 _TEXT_REF + r".{0,30}in front of (the )?" + _PERSON)
    behind = _has(p, _TEXT_REF + r"\b.{0,40}\b" + _PEECHE + r"\b", r"\bbehind (the )?" + _PERSON,
                  _PERSON + r"\w* ke " + _PEECHE)
    if front:
        it.text_front, it.text_behind, it.captions_behind = True, False, False
        rec[:] = [r for r in rec if r != "text behind the person"]
        rec.append("text in front of the person")
    elif behind:
        it.text_behind = True
        if _has(p, r"(captions?|subtitles?).{0,40}" + _PEECHE):
            it.captions_behind = True
            if not it.captions:
                it.captions = True
                rec.append("captions")
        if "text behind the person" not in rec:
            rec.append("text behind the person")
    if (front or behind) and "follow" in it.effects and not _has(p, r"\bfollow", r"\btrack", r"reframe", r"cent(er|re)"):
        it.effects.remove("follow")  # "person ke peeche" was about the text, not about following the person
        rec[:] = [r for r in rec if r != "follow effect"]

    colors = "|".join(sorted(COLOR_WORDS, key=len, reverse=True))
    m = (re.search(rf"\b({colors})\s+(colou?r\s+|rang\s+)?(shirt|t-?shirt|tshirt|tee|jersey|kurta|kurti|dress|jacket|hoodie|"
                   rf"top|kapd\w*|saree|cap|wal[ae]|wali|waale|wale|vala|vale)\b", p)
         or re.search(rf"\b{_PERSON}\s+(in|wearing|with)\s+(a\s+|the\s+)?({colors})\b", p))
    if m:
        word = next(g for g in m.groups() if g in COLOR_WORDS)
        it.track_color = COLOR_WORDS[word]
        rec.append(f"the person in {word}")
    blur_rest = _has(p, r"(baaki|baki|rest|background|bg|others|baakiyo\w*|baakiyon|dusre|doosre|sab\w*)\s*(sab\w*\s*)?(ko\s*)?"
                        r"(blur|dhundhl\w*|dhundl\w*)",
                     r"blur (the )?(rest|background|baaki|everything else|others|everyone else|baakiyo\w*)",
                     r"focus.{0,40}\bblur")
    # "highlights only" = best moments, not a person: highlight / focus count only with someone to focus on
    focus_words = _has(p, r"\bfocus", r"main focus", r"\bhighlight (the |that |this )?" + _PERSON, r"spotlight",
                       r"(usko|use|usi ko|unko|him|her)\s*(hi\s*)?(dikhao|dikha|show)", r"\bsirf\b.{0,30}\b(dikh\w*)")
    someone = bool(it.track_color) or _has(p, r"\b" + _PERSON + r"\b", r"\bwal[ae]\b", r"\bwaale\b", r"\bwale\b")
    if blur_rest and someone and (focus_words or it.track_color or _has(p, r"(baaki|baki|rest|others|dusre)")):
        it.focus = "blur"
    elif it.track_color and focus_words:
        it.focus = "dim"
    if it.focus:
        it.effects = [e for e in it.effects if e not in ("blur", "blur_background", "spotlight")]
        rec[:] = [r for r in rec if r not in ("blur effect", "blur_background effect", "spotlight effect")]
        who = f"the person in {next(k for k, v in COLOR_WORDS.items() if v == it.track_color)}" if it.track_color \
            else "the main person"
        rec.append(f"focus on {who}, the rest {'blurred' if it.focus == 'blur' else 'darker'}")


_NEG = r"\b(mat|nahi|nahin|nai|no|not|without|bina|don'?t|never|avoid|band|hata\w*|remove|nikal\w*|skip)\b"
_FX_NAMES_AVOID_ZOOM = ("pulse", "punch", "impact", "drift")


def _parse_negations(p: str, it: "Intent", rec: list[str]) -> None:
    """What NOT to do: "black and white screen mat karo", "zoom nahi chahiye", "no glitch", "text mat daalo"."""
    q = re.sub(r"black (and|&|n) white", "black_and_white", p)
    for clause in re.split(r",|;|\.(?=\s)|\b(?:aur|and|but|lekin|magar|phir|fir|then)\b", q):
        if not clause or not re.search(_NEG, clause):
            continue
        bare = re.sub(_NEG, " ", clause).replace("black_and_white", "black and white")
        fx = set(_clause_effects(bare))
        gone: list[str] = []
        if re.search(_BW_WORDS, bare) or "mono" in fx:
            fx |= {"mono", "silhouette", "invert_mono", "film_bw"}
            it.avoid.append("bw")
            it.color_pass = False
            if it.color_preset == "bw":
                it.color_preset = None
            gone.append("black & white")
        if "zoom" in fx:
            fx |= set(_FX_NAMES_AVOID_ZOOM)
        if fx:
            it.effects = [e for e in it.effects if e not in fx]
            it.timed_effects = [t for t in it.timed_effects if t.effect not in fx]
            it.avoid += sorted(fx)
            gone += sorted(fx - {"mono", "silhouette", "invert_mono", "film_bw", *_FX_NAMES_AVOID_ZOOM})
        if _has(bare, r"\b(text|likh\w*|naam|title)\b", r"\bwords? on (the )?screen") \
                and not _has(bare, r"captions?|subtitles?"):  # not "remove filler words"
            if _has(p, r"\b(ek|one|1|duplicate|double|dobara|2 baar|do baar|two times|twice|dono me se|ek baar)\b"):
                # "2 baar text dikh raha, usme se ek hata do": keep the title, drop the repeated beat words
                it.kinetic_text = False
                it.avoid.append("kinetic")
                gone.append("repeated text (the title stays)")
            else:
                it.kinetic_text, it.title = False, None
                it.avoid.append("text")
                gone.append("text on screen")
        if _has(bare, r"slow.?mo", r"slow motion"):
            it.slow_motion = False
            it.avoid.append("slow_motion")
            gone.append("slow motion")
        if gone:
            drop = {"bw color", "mono effect", *(f"{e} effect" for e in fx)}
            rec[:] = [r for r in rec if r not in drop and not any(r.startswith(f"{e} ") for e in ("black & white",))]
            rec.append("no " + ", no ".join(dict.fromkeys(gone)))
    it.avoid = list(dict.fromkeys(it.avoid))


@functools.lru_cache(maxsize=8192)
def _rx(pattern: str) -> re.Pattern[str]:
    # the rules use ~2000 patterns; Python's own cache keeps 512, so every message recompiled them (~0.5 s each time)
    return re.compile(pattern)


def _has(text: str, *patterns: str) -> bool:
    return any(_rx(p).search(text) for p in patterns)


def parse_intent(prompt: str) -> Intent:
    """Deterministic keyword/regex parser. Covers the common phrasing of editing requests."""
    raw = validate_prompt(prompt)
    p = raw.lower()
    it = Intent()
    rec: list[str] = []

    # "starting ke 3s me zoom" is WHEN an effect happens, not how long the video is: parse those first
    timed, timing_spans = parse_timed_effects(p)

    def is_timing(m: re.Match[str]) -> bool:
        return any(a <= m.start(1) < b for a, b in timing_spans)

    # "zoom in text", "neon text style", "flickering text" describe TEXT: read them first, then blank them out so
    # the effect / look / style parsers below don't also apply them to the video (same length keeps spans valid)
    p, tlook = extract_text_look(p)

    # Several numbers may appear ("30 sec reel with 1s fades"): the largest one is the target length.
    candidates = [float(m.group(1)) * 60 for m in re.finditer(r"(\d+(?:\.\d+)?)\s*-?\s*(?:min|mins|minute|minutes)\b", p)
                  if not is_timing(m)]
    candidates += [float(m.group(1)) for m in re.finditer(r"(\d+(?:\.\d+)?)\s*-?\s*(?:s|sec|secs|second|seconds)\b", p)
                   if not is_timing(m)]
    candidates = [c for c in candidates if c >= 3]
    if candidates:
        it.target_duration = min(600.0, max(candidates))
    if it.target_duration:
        rec.append(f"target duration {it.target_duration:g}s")

    if _has(p, r"9\s*:\s*16", r"\bvertical\b", r"\breels?\b", r"\bshorts?\b", r"tiktok", r"\bstory\b", r"\bportrait\b",
            r"\bkhad[aei]\b", r"phone (wala|wali|ke liye|size|screen)", r"mobile (size|screen|wala)"):
        it.aspect_ratio = "9:16"
    elif _has(p, r"1\s*:\s*1", r"\bsquare\b"):
        it.aspect_ratio = "1:1"
    elif _has(p, r"16\s*:\s*9", r"\blandscape\b", r"\bhorizontal\b", r"widescreen", r"youtube"):
        it.aspect_ratio = "16:9"
    if it.aspect_ratio:
        rec.append(f"aspect ratio {it.aspect_ratio}")

    m = re.search(r"\b(1080|720|480|360)p\b", p)
    if m:
        it.resolution = int(m.group(1))  # type: ignore[assignment]
    elif "4k" in p:
        it.resolution = 1080

    presets: list[tuple[ColorPreset, tuple[str, ...]]] = [
        # English + common Hinglish words (Indian creators write prompts like "thoda garam rang do")
        ("bw", (r"black\s*(?:and|&)?\s*white", r"\bb\s*&\s*w\b", r"\bbw\b", r"monochrome", r"grayscale", r"greyscale")),
        ("warm", (r"\bwarm", r"golden", r"sunset", r"\bgara?m\b")),
        # "an edit that is cool" = good, "too cold" = a lyric: only colour words make it a cool GRADE
        ("cool", (r"\bcool(er)? ?(tones?|colou?rs?|look|grade|grading|filter|blue|rang|feel)\b",
                  r"\bcolou?rs?\b.{0,12}\bcool(er)?\b", r"\bcold (tones?|colou?rs?|look|grade|feel|rang)\b",
                  r"blue tone", r"\bicy\b", r"\bthand[aei] (rang|colou?r|look|tone)")),
        ("cinematic", (r"cinematic", r"(?<!old )\bfilm(ic)?\b(?! grain)", r"teal")),
        ("sepia", (r"sepia", r"old photo", r"brownish")),
        ("vintage", (r"vintage", r"retro", r"old.?school", r"\bfaded\b", r"\bpuran[aei]\b", r"purane zamane")),
        ("vivid", (r"vivid", r"vibrant", r"punchy", r"colou?rful", r"saturated", r"rangeen", r"chamak")),
    ]
    if _has(p, r"(rang|colou?rs?)\w*\s.{0,20}\b(feek|fik|halk|dull|kam|dab)\w*", r"\b(feek|fik)\w*\s+(rang|colou?r)",
            r"(muted|washed.?out|less colou?rful|desaturat)"):
        it.color_preset = "faded_film"  # type: ignore[assignment]
        rec.append("Faded Film look")
    elif _has(p, r"\bdramatic\b", r"movie trailer", r"trailer (jaisa|jaise|like)", r"film (jaisa|jaise) look"):
        it.color_preset = "cinematic"
        rec.append("cinematic color")
    # a look is read only from the parts that ASK for it: "black and white hata do, warm karo" = warm
    pos = p
    if re.search(_NEG, p):
        q = re.sub(r"(black|teal) (and|&|n) (white|orange|gold)", r"\1_and_\3", p)
        pos = " , ".join(c for c in re.split(r",|;|\.(?=\s)|\b(?:aur|and|but|lekin|magar|phir|fir|then)\b", q)
                         if c and not re.search(_NEG, c)).replace("_and_", " and ")
    for look, (lname, _desc, pats) in ([] if it.color_preset else LUT_LOOKS.items()):  # LUT looks (more specific words)
        if _has(pos, *pats):
            it.color_preset = look  # type: ignore[assignment]
            rec.append(f"{lname} look")
            break
    for preset, pats in ([] if it.color_preset else presets):
        if _has(pos, *pats):
            it.color_preset = preset
            rec.append(f"{preset} color")
            break
    if _has(p, r"(zyada|bahut|too|very|kaafi) dark", r"dark ho gaya", r"andhera (zyada|bahut)"):
        it.brightness = 0.08   # "too dark" means: make it BRIGHTER
        rec.append("brighter")
    elif _has(p, r"(zyada|bahut|too|very) bright", r"bright ho gaya"):
        it.brightness = -0.06
        rec.append("darker")
    elif _has(p, r"bright(er|en)", r"\blighter\b", r"\broshni\b", r"\bujal", r"(thoda|zara|aur|bit|little) bright",
              r"bright kar", r"\brosh?an\b", r"(kala|kaala|andhera|dark)\s+(lag|dikh)", r"too dark"):
        it.brightness = 0.08
        rec.append("brighter")
    elif _has(p, r"dark(er|en)", r"\bmoody\b", r"(thoda|zara|aur|bit|little) dark", r"dark kar"):
        it.brightness = -0.06
        rec.append("darker")

    if _has(p, r"caption", r"subtitle", r"\bsubs\b"):
        it.captions = True
        rec.append("captions")
    if _has(p, r"silen", r"dead air", r"\bpauses?\b", r"khamosh", r"\bchup\b", r"bol nahi", r"awaa?z nahi",
            r"(nahi|nhi|nai|na)\s+bol\s*(raha|rahi|rha|rhi|rahe|ta|ti)", r"\b(not|n'?t)\s+(talking|speaking|saying)",
            r"no ?one (is )?(talking|speaking)", r"nobody (is )?(talking|speaking)", r"(baat|bol)\s*(nahi|nhi) (ho|kar)"):
        it.remove_silence = True
        rec.append("remove silence")
    if _has(p, r"filler", r"\bums?\b", r"\buhs?\b"):
        it.remove_fillers = True
        rec.append("remove filler words")
    if _has(p, r"fast.?(cut|paced|edit)", r"quick.?cuts?", r"snappy", r"energetic", r"\bhype\b", r"rapid", r"\btez\b", r"jaldi jaldi"):
        it.fast_cuts = True
        rec.append("fast cuts")
    if _has(p, r"\b(end|ending|aakhir|akhir|aakhri|akhri|last|ant)\w*\s+(me|mein|main|pe|par|at|in|wala|wale)?\s*"
               r"(slow.?mo\w*|slow motion|slow)\b", r"(slow.?mo\w*|slow motion)\s+(at|in|on)\s+the\s+end"):
        it.slow_end = True  # only the closing shot, not the whole video
        rec.append("slow motion on the last shot")
    elif _has(p, r"slow.?mo", r"slow motion", r"\bslow\s+(wala|wali|sa|si|type|feel|vibe)\b", r"\bdheere\s+dheere\b"):
        it.slow_motion = True
        rec.append("slow motion")
    elif _has(p, r"\b(slow|slower|dheere|dheema|dheemi)\s*(karo|kar\s*do|kr\s*do|kardo|kar\s*de|rakho|chahiye|ho|pace)\b",
              r"\b(thoda|thodi|zara|aur|bit|little|bahut|zyada|too)\s+(slow|slower|dheere|dheema)\b(?!.{0,4}(mo\b|motion))") \
            and not _has(p, r"\b(gaa?n[aei]|music|song|bgm|awaa?z|volume|sound)\b"):
        # ("gaana thoda dheere karo" is about the music's LEVEL — "music soft" — not the cut)
        # "thoda slow karo" after an edit = longer shots (the pace), not slow motion
        it.pace_change = 2.0 if _has(p, r"\b(bahut|zyada|much|too|kaafi)\b") else 1.5
        rec.append("slower pace (longer shots)")
    if _has(p, r"\b(fast|faster|tez|tezz|jaldi)\s*(karo|kar\s*do|kr\s*do|kardo|kar\s*de|rakho|chahiye)\b",
            r"\b(thoda|thodi|zara|aur|bit|little|bahut|zyada|too)\s+(fast|faster|tez|tezz|quick)\b"):
        it.pace_change = 0.5 if _has(p, r"\b(bahut|zyada|much|too|kaafi)\b") else 0.67
        rec.append("faster pace (shorter shots)")
    if _has(p, *NO_MUSIC):
        rec.append("no music")
    elif _has(p, r"music", r"\bsong\b", r"soundtrack", r"\bbgm\b", r"background track", r"\bbeats?\b", r"\bgaa?n[ae]\b",
            r"sangeet", r"\btunes?\b"):
        it.music = True
        it.music_mood = "calm" if _has(p, r"calm", r"chill", r"relax", r"soft", r"lofi", r"lo-fi", r"emotional", r"\bsad\b",
                                       r"sentimental", r"romantic", r"\bdard\w*", r"\bdukh\w*", r"\bshaant", r"yaadgaar",
                                       r"nostalgi") else "upbeat"
        rec.append(f"{it.music_mood} music")
    if _has(p, r"beat.?sync", r"on the beat", r"to the beat", r"\bbeats?\b", r"rhythm"):
        it.beat_sync = True
        it.music = True
        it.music_mood = it.music_mood or "upbeat"
        rec.append("beat-synced cuts")
        if not it.fast_cuts and _has(p, r"\bcuts?\b"):
            it.fast_cuts = True  # "beat sync cuts" = cut on the beat, i.e. short beat-length segments
            rec.append("fast cuts")

    # "fade the audio / music" is an audio fade, not a video transition
    audio_fade_pat = r"fade (in |out |in and out |in/out )?(the )?(audio|music|sound|song)|(audio|music|sound) fade"
    if re.search(audio_fade_pat, p):
        it.audio_fade = True
        rec.append("audio fade in/out")
    pv = re.sub(audio_fade_pat, " ", p)
    cat_t = next((f.id for f in ALL_FX if f.category == "transition" and f.keywords and _has(pv, *f.keywords)), None)
    if cat_t:
        it.transition = cat_t
    elif _has(pv, r"cross.?fade", r"dissolve"):
        it.transition = "crossfade"
    elif _has(pv, r"\bwipes?\b"):
        it.transition = "wipe"
    elif _has(pv, r"zoom transition", r"zoom between"):
        it.transition = "zoom"
    elif _has(pv, r"\bfades?\b", r"fade.?in", r"fade.?out"):
        it.transition = "fade"
    elif _has(pv, r"transition"):
        it.transition = "crossfade"
    if it.transition:
        rec.append(f"{it.transition} transitions")

    effects: list[EffectType] = []
    if _has(p, r"zoom.?in", r"zoom effect", r"ken burns", r"punch.?in", r"\bzooms?\b(?! transition| out)") and it.transition != "zoom":
        effects.append("zoom")
    if _has(p, r"speed.?ramp", r"\bramp"):
        effects.append("speed_ramp")
    if _has(p, r"blur(red)?.?(the )?(background|bg)", r"background blur"):
        effects.append("blur_background")
    if _has(p, r"shake", r"handheld"):
        effects.append("shake")
    if _has(p, r"vignette", r"dark (edges|corners)", r"kinar\w*.{0,20}(andher|kaal|kale|dark)", r"corners?.{0,10}(dark|kale)"):
        effects.append("vignette")
    if _has(p, r"sharpen", r"sharper", r"\bcrisp"):
        effects.append("sharpen")
    if (_has(p, r"\bblur(red|ry)?\b(?!.{0,6}(background|bg))", r"soft focus", r"dhundh")
            and "blur_background" not in effects):
        effects.append("blur")
    # everything else in the FX catalogue (glitch, VHS, film grain, pans, kaleidoscope, …)
    for fx in ALL_FX:
        if fx.category in ("motion", "video_effect") and fx.id not in effects and fx.keywords and _has(p, *fx.keywords):
            if fx.id == "zoom" and it.transition == "zoom":
                continue
            if fx.id == "blur" and "blur_background" in effects:
                continue
            effects.append(fx.id)
    if _has(p, *BASS):
        it.bass_boost = True
        rec.append("bass boost + zoom punch on every beat")
        if "pulse" not in effects:
            effects.append("pulse")
        if not it.music:
            it.music, it.music_mood = True, it.music_mood or "upbeat"
            rec.append("upbeat music")
    # "paas se dikhao chehra" = close-up on the face / person; "paas se dikhao" alone = a push-in
    if _has(p, r"(paas|kareeb|nazdeek|close)\s*(se)?\b.{0,25}(chehr|face|person|bande|banda|insaan)",
            r"(chehr|face)\w*.{0,20}(paas|kareeb|nazdeek|close)"):
        if "person_zoom" not in effects:
            effects.append("person_zoom")
    elif _has(p, r"(paas|kareeb|nazdeek)\s+se\s+(dikha|dikhao|dikhe)") and "zoom" not in effects:
        effects.append("zoom")
    _BWW = r"(black\s*(?:and|&|n)?\s*white|\bb\s*&\s*w\b|\bbw\b)"
    _END = r"\b(last|end|ending|aakhri|akhri|aakhiri|aakhir|akhir|ant)\s*(wala|wali|wale)?\s*(shot|clip|scene|part|hissa|me|mein|main|pe|par|mai)?\b"
    _START = r"\b(first|pehla|pehli|pahla|starting|start|shuru|shuruat)\s*(wala|wali|wale)?\s*(shot|clip|scene|part|hissa|me|mein|main|pe|par|mai)?\b"
    if it.color_preset == "bw" and not it.timed_effects and not _has(p, r"\d+\s*(sec|second|s\b)") and (
            _has(p, _END + r".{0,8}" + _BWW, _BWW + r".{0,8}" + _END) or _has(p, _START + r".{0,8}" + _BWW)):
        # "last shot black and white": only the closing ~2.5 s, not a B&W video
        from_end = _has(p, _END + r".{0,8}" + _BWW, _BWW + r".{0,8}" + _END)
        it.timed_effects = [TimedEffect(effect="mono", start=2.5 if from_end else 0.0,
                                        end=None if from_end else 2.5, from_end=from_end)]
        it.color_preset = None
        rec[:] = [r for r in rec if r != "bw color"]
        rec.append("black & white on the " + ("last" if from_end else "first") + " shot")
    if it.color_preset == "bw" and (
            _has(p, r"\b(some|few|a few|kuch|thode|beech\s*beech|kabhi\s*kabhi|alternate|random)\b.{0,25}" + _BWW)
            or _has(p, _BWW + r"\s*(shots?|clips?|flashes|moments|parts?)\b")):
        # "some shots black and white" / "kuch shots black and white": a colour pass on the rhythm, not a B&W video
        it.color_preset = None
        rec[:] = [r for r in rec if r != "bw color"]
        if not it.color_pass:
            it.color_pass = True
            rec.append("some shots black & white")
    if "film_bw" in effects:  # "old movie black and white" is one look (grain + flicker + B&W), not three
        effects = [e for e in effects if e != "old_film"]
        if it.color_preset == "bw":
            it.color_preset = None
            rec[:] = [r for r in rec if r != "bw color"]
    if "person_zoom" in effects and "zoom" in effects:  # "zoom on the face" is the tracked zoom, not a plain push-in
        effects.remove("zoom")
    # effects that only apply to part of the video are not whole-video effects
    if any(t.effect == "mono" for t in timed) and it.color_preset == "bw":
        it.color_preset = None  # "pehle 3 sec black and white" is NOT a black-and-white video
        rec[:] = [r for r in rec if r != "bw color"]
    if timed:
        it.timed_effects = timed
        effects = [e for e in effects if e not in {t.effect for t in timed}]
        rec.extend(describe_timed(t) for t in timed)
    it.effects = effects
    rec.extend(f"{e} effect" for e in effects)
    if tlook["preset"]:
        it.text_style = tlook["preset"]
        rec.append(f"{TEXT_PRESETS_NAMES[tlook['preset']]} text style")
    if tlook["color"]:
        it.text_color = tlook["color"][1]
        rec.append(f"{tlook['color'][0]} text")
    if tlook["anim"]:
        it.text_animation = tlook["anim"]  # type: ignore[assignment]
        rec.append(f"{tlook['anim']} text animation")
        if tlook["anim"] == "karaoke" and not it.captions:
            it.captions = True
            rec.append("captions")

    _parse_text_and_subject(p, raw, it, rec)
    m = re.search(r"title\s*[:=]?\s*[\"“']([^\"”']{1,80})[\"”']", raw, re.I)
    if not m and not it.tracked_text and not _has(p, r"\b(track\w*|follow\w*)\b") \
            and _has(p, r"\b(text|likh\w*|naam|name|title|word)\b"):
        # "text bhi daal do 'RONALDO'", "RONALDO likh do": the quoted / ALL-CAPS word is the title
        m = (re.search(r"[\"“'‘]([^\"”'’]{1,40})[\"”'’]", raw)
             or re.search(r"\b([A-Z][A-Z0-9]{2,}(?: [A-Z0-9]{2,}){0,3})\b", raw))
    if m:
        it.title = m.group(1).strip()
        rec.append(f"title '{it.title}'")
    if _has(p, r"clean.?(up)?.?(the )?(audio|voice|sound)", r"denois", r"background noise", r"voice cleanup",
            r"enhance (the )?(audio|voice)", r"\bnoise\b(?! effect)", r"\bhawa\b", r"\bwind\b", r"\bshor\b",
            r"(voice|audio|sound|a{1,2}wa{1,2}j?z?)\b.{0,40}\b(clear|saaf|clean|theek)", r"\bhiss\b", r"\bhumming\b",
            r"gungun\w*", r"khar ?khar", r"\bmuffled\b"):  # not "hum" (= "we" in Hindi)
        it.voice_cleanup = True
        rec.append("voice cleanup")
    if _has(p, *SMART_ORDER):
        it.order = "smart"
        rec.append("smart arrange (in the order it was filmed)")
    elif _has(p, r"reverse order", r"backwards order", r"\bult[aie]\b(?!\s+(chala|chalao|chalado|play|ghuma))",
              r"clips?\s+(ko\s+)?ult[aie]"):  # "clips ulta chalao" = the clips in reverse order
        it.order = "reverse"
        rec.append("reverse clip order")
    elif _has(p, r"best (moments|parts|shots)", r"highlights?"):
        it.order = "best"
        rec.append("best moments first")
    if _has(p, r"travel", r"\btrip\b", r"vlog"):
        rec.append("travel/vlog style")
    _parse_extra_ops(p, raw, it, rec)
    _parse_style(p, it, rec)
    if _has(p, *AUTO_EDIT) or (not rec and _has(p, *GENERIC_EDIT)):
        it.auto = True
        if it.order == "original":
            it.order = "smart"
        rec.append("auto edit (the agents choose effects, music, captions and order)")

    _parse_placement_and_focus(p, it, rec)
    _parse_negations(p, it, rec)
    if _has(p, r"\b(reference|refrence|refernce|refrance)\b",
            r"\b(sample|example)\s+(video|edit|reel)?\s*(jaisa|jaise|ki tarah|like|style)",
            r"(is|us|that|this|uploaded|upload ki)\s+(edit|video|reel)\s+(jaisa|jaise|ki tarah|like|wala style)",
            r"(usi|isi|wahi|same)\s+(style|tarah)", r"same to same", r"copy (the |its |that )?(style|edit)",
            r"edit (it |mine |my video )?(just )?like (that|this|the other|the uploaded) (one|video|edit)"):
        it.use_reference = True
        rec.append("edit like the reference video")
    # "captions hata de", "transitions bakwas hai", "zyada flashy hai simple kar": take things OUT
    for fld, pats in REMOVALS.items():
        if _has(p, *pats):
            it.remove.append(fld)
            setattr(it, fld, [] if fld == "effects" else None if fld == "transition" else False)
            gone = {"captions": lambda r: r == "captions", "transition": lambda r: r.endswith(" transitions"),
                    "effects": lambda r: r.endswith(" effect"),
                    "word_stickers": lambda r: r.startswith("stickers of")}[fld]
            rec[:] = [r for r in rec if not gone(r)]
            rec.append(f"remove {fld}")
    _parse_everyday_asks(p, it, rec, raw)
    it.recognized = rec
    return it


def _parse_everyday_asks(p: str, it: "Intent", rec: list[str], raw: str = "") -> None:
    """Short things people say in the chat that the rules above miss (found by tests/unit/test_noob_messages.py)."""
    # "tez" about colour / sound is not speed: "rang tez karo" = stronger colours, "gaana / awaaz tez karo" = louder
    about = r"\b(rang|colou?rs?|awaa?z|aawaa?z|gaa?n[ae]|music|song|volume|sound|voice|bass|light|roshni)\w*"
    if _has(p, about + r".{0,20}\b(te[zj]|tezz|fast)\b") and not _has(p, r"\b(cuts?|edit|video|pace|speed|shots?)\b.{0,12}"
                                                                         r"\b(te[zj]|fast)\b", r"\bfast (cuts?|edit|pace)\b"):
        it.fast_cuts, it.pace_change = False, None
        rec[:] = [r for r in rec if r not in ("fast cuts", "faster pace (shorter shots)")]
    if _has(p, r"\b(rang|colou?rs?)\w*.{0,12}\b(te[zj]|tezz|gehr\w*|gaadh\w*)\b") and it.color_preset is None:
        it.color_preset = "vivid"
        rec.append("vivid color")
    # "color wapas lao", "rang normal karo", "original colour": the footage's own colours again (no B&W, no grade)
    if _has(p, r"\b(colou?rs?|rang)\b.{0,12}\b(wapas|vapas|wapis|back|normal|original|asli|pehle (jaisa|jaise|wala))\b",
            r"\b(original|asli|normal|real)\s+(colou?rs?|rang)\b") \
            and not _has(p, r"(black (and|&|n) white|b ?& ?w)\b.{0,40}colou?r"):
        it.restore_color = True
        it.color_preset, it.color_pass = None, False
        it.effects = [e for e in it.effects if e not in ("mono", "film_bw", "invert_mono", "silhouette")]
        rec[:] = [r for r in rec if r not in ("mono effect", "bw color")]
        rec.append("original colours back (no black & white, no grade)")
    # "start me Goa Trip likh do" / "last me The End likh do": the words between "me" and "likh do" ARE the text
    m = re.search(r"\b(start|starting|shuru|shuruat|beginning)\s*(me|mein|main|pe|par|mai)?\s+(.{2,40}?)\s+"
                  r"(likh|likho|likhna|likh do|likh de|daal|daalo|dikhao|aaye|aana chahiye)\b", raw, re.I)
    if m and not it.title and not it.tracked_text and not re.search(r"\b(zoom|slow|music|gaana|black|colou?r)\b",
                                                                     m.group(3), re.I):
        it.title = m.group(3).strip(" '\"")
        rec[:] = [r for r in rec if r != "travel/vlog style"] if "trip" in it.title.lower() else rec
        rec.append(f"title '{it.title}' at the start")
    # the LAST "end / last … likh do" in the message ("end me slow motion aur last me The End likh do")
    m = re.search(r"^.*\b(last|end|ending|aakhir|akhir|aakhri|akhri|ant)\s*(me|mein|main|pe|par|mai)?\s+(.{2,40}?)\s+"
                  r"(likh|likho|likhna|likh do|likh de|daal|daalo|dikhao|aaye|aana chahiye)\b", raw, re.I | re.S)
    if m and not re.search(r"\b(zoom|slow|music|gaana|black|colou?r)\b", m.group(3), re.I):
        it.end_text = m.group(3).strip(" '\"")
        rec.append(f"'{it.end_text}' at the end")
    # "jo bol raha hu uske stickers / emoji / animation daalo": spoken things pop up as stickers
    if _has(p, r"\b(stickers?|emojis?|emoticons?)\b",
            r"\b(jo|jis|jiske|jiski)\b.{0,40}\b(bol|bolu|boloon|bolta|bolti|bol raha|bol rahi|baat|keh|kah|say|said|talk)\w*"
            r".{0,60}\b(animation|animated|cartoon|chitra|photo|image|picture|icon)\w*",
            r"\b(say|talk about|mention)\w*.{0,40}\b(pop ?up|appear|show)\w*.{0,20}\b(animation|icon|image|picture)\w*"):
        if "word_stickers" not in it.remove and not _has(
                p, r"\b(stickers?|emojis?)\b.{0,25}\b(hata|nikal|remove|mat|nahi|band|off)\w*"):
            it.word_stickers = True
            rec.append("stickers of the things that are said")
    # "zoom thoda kam karo": a gentler move, not a new zoom
    if _has(p, r"\bzoom\w*\s.{0,10}\b(kam|halka|less|dheere|dheema|slow)\b", r"\b(kam|less)\s+zoom\b"):
        it.effects = [e for e in it.effects if e not in ("zoom", "zoom_out")] + ["drift"]
        it.avoid.append("zoom")
        rec[:] = [r for r in rec if r != "zoom effect"]
        rec.append("gentler zoom")
    # "music thoda kam karo" changes the level, not the song
    if any(r in ("music soft", "music loud") for r in rec) and not _has(
            p, r"\b(upbeat|calm|sad|shaant|shant|mast|josh|happy|romantic|emotional|party|chill|lofi|naya|dusra|badal)\w*"):
        it.music_mood = None
        rec[:] = [r for r in rec if r not in ("upbeat music", "calm music")]
    # "thoda smooth karo": soft joins between shots
    if _has(p, r"\b(smooth|smoothly|smoothness|aaram se|araam se|soft)\b") and not it.transition \
            and not _has(p, r"\b(skin|face|chehra|awaa?z|voice|music)\b"):
        it.transition = "crossfade"
        rec.append("smooth (crossfade) transitions")
    # "pehla clip hata do", "last video nikal do": leave a clip out by its place in the list
    order_words = {"pehla": 1, "pehli": 1, "pahla": 1, "phela": 1, "first": 1, "1st": 1, "ek": 1,
                   "dusra": 2, "doosra": 2, "dusri": 2, "second": 2, "2nd": 2, "do": 2,
                   "teesra": 3, "tisra": 3, "teesri": 3, "third": 3, "3rd": 3,
                   "chautha": 4, "fourth": 4, "4th": 4, "last": -1, "aakhri": -1, "akhri": -1, "aakhiri": -1}
    for w, _noun in re.findall(r"\b(" + "|".join(order_words) + r"|\d)\s*(?:wala|wali|number|no\.?)?\s*(clip|video|vid)\b"
                           r"(?=.{0,20}\b(?:hata|nikal|remove|delete|mat|nahi|hatao|kaat)\w*)", p):
        k = order_words.get(w, int(w) if w.isdigit() else 0)
        if k and k not in it.drop_clips:
            it.drop_clips.append(k)
            rec.append(f"leave out clip {k if k > 0 else 'last'}")
    # "thoda chhota karo" / "lamba karo": relative length (the current edit's length × this)
    if it.target_duration is None:
        if _has(p, r"\b(chhota|chota|chhoti|choti|short(er)?|kam\s+(time|length|lamba\w*))\s*(karo|kar\s*do|kr\s*do|kardo|"
                   r"bana\w*|chahiye|rakho)\b", r"\bmake it shorter\b", r"\b(thoda|aur|bit)\s+(chhota|chota|short)\b"):
            it.length_change = 0.5 if _has(p, r"\b(bahut|kaafi|much|aadha|half)\b") else 0.7
            rec.append("shorter")
        elif _has(p, r"\b(lamba|lambi|longer|bada|badi)\s*(karo|kar\s*do|kr\s*do|kardo|bana\w*|chahiye|rakho)\b",
                  r"\bmake it longer\b", r"\b(thoda|aur|bit)\s+(lamba|lambi|long)\b"):
            if not _has(p, r"\b(text|title|caption|font|naam|likh\w*)\b"):  # "text bada karo" is about the text
                it.length_change = 2.0 if _has(p, r"\b(bahut|kaafi|much|double|dugna)\b") else 1.4
                rec.append("longer")
    # "text bada karo" / "text chhota karo"
    if _has(p, r"\b(text|title|caption\w*|font|naam|likha\w*)\b.{0,15}\b(bada|badi|bade|big(ger)?|large|zyada)\b"):
        it.text_scale = 1.5
        rec.append("bigger text")
    elif _has(p, r"\b(text|title|caption\w*|font|naam|likha\w*)\b.{0,15}\b(chhota|chota|chhoti|choti|small(er)?)\b"):
        it.text_scale = 0.7
        rec.append("smaller text")
    # "boring part kaat do", "faltu hissa hata do"
    if _has(p, r"\b(boring|bekaar|bekar|faltu|bakwas|useless|dull)\b.{0,20}\b(kaat|kat|hata|nikal|remove|cut|skip)\w*",
            r"\b(kaat|hata|nikal|remove|cut)\w*\s.{0,10}\b(boring|bekaar|faltu|bakwas)\b"):
        it.remove_idle = True
        if "remove idle parts" not in rec:
            rec.append("remove idle parts")
    # "best part pehle dikhao"
    if _has(p, r"\b(best|accha|achha|acha|mast|zabardast|strong\w*|top)\s+(part|moment|scene|shot|hissa|wala|clip)\w*.{0,20}"
               r"\b(pehle|phele|pahle|shuru|starting|opening)\b",
            r"\b(start|open|begin)\s+with\s+(the\s+)?(best|strongest)\b"):
        it.hook_first = True
        if "best moment first" not in rec:
            rec.append("best moment first")
    # "instagram ke liye" / "youtube ke liye": the shape that platform shows
    if it.aspect_ratio is None:
        if _has(p, r"\b(insta\w*|reels?|tiktok|tik tok|shorts?|status|story|stories|snapchat|moj|josh)\b"):
            it.aspect_ratio = "9:16"
            rec.append("aspect ratio 9:16")
        elif _has(p, r"\byou\s?tube\b(?!\s+shorts?)"):
            it.aspect_ratio = "16:9"
            rec.append("aspect ratio 16:9")
    if it.resolution and not any(r.startswith("resolution") for r in rec):
        rec.append(f"resolution {it.resolution}p")
    if it.music is False and any(r == "no music" for r in rec):
        it.no_music = True  # an explicit "no music": a remembered song must go too


def _parse_extra_ops(p: str, raw: str, it: Intent, rec: list[str]) -> None:
    """Rotate / flip / reverse / fps / gamma / audio / watermark / idle removal / GIF & MP3 export."""
    if _has(p, r"upside.?down", r"rotate (it |the video |video )?(by )?180", r"\b180 ?(degrees?|°)"):
        it.rotate = 180
    elif _has(p, r"rotate (it |the video |video )?(to the )?left", r"counter.?clockwise", r"anti.?clockwise",
              r"rotate (it |the video |video )?(by )?(270|-90)"):
        it.rotate = 270
    elif _has(p, r"rotate", r"ghuma", r"clockwise", r"\b90 ?(degrees?|°)"):
        it.rotate = 90
    if it.rotate:
        rec.append(f"rotate {it.rotate} deg")

    if _has(p, r"flip (it |the video |video )?vertical", r"vertical(ly)? flip", r"mirror vertical"):
        it.flip = "v"
    elif _has(p, r"\bmirror(?! effect)(?!ed)", r"\bflip", r"ulta (side|taraf)"):
        it.flip = "h"
    if it.flip != "none":
        rec.append(f"flip {it.flip}")

    if _has(p, r"play (it |the video |video )?(in )?revers", r"play\b.{0,20}\bbackwards?", r"\brewind",
            r"(video|clip|footage|it) (runs? |going )?backwards?",
            r"revers(e|ed) (the )?(video|playback|clip|footage)", r"backwards? (video|playback)", r"peeche chala",
            r"(?<!clips )(?<!clip )\bult[aie]\s+(chala|chalao|chalado|play|ghuma)"):
        it.reverse_playback = True
        rec.append("reverse playback")

    m = re.search(r"\b(24|25|30|50|60)\s*(fps|frames? per second)", p)
    if m:
        it.fps = int(m.group(1))  # type: ignore[assignment]
        rec.append(f"{it.fps} fps")

    m = re.search(r"gamma\s*(?:to|=|of)?\s*(\d(?:\.\d+)?)", p)
    if m:
        it.gamma = max(0.3, min(3.0, float(m.group(1))))
        rec.append(f"gamma {it.gamma:g}")
    elif _has(p, r"(increase|raise|boost|more) gamma", r"lift (the )?(shadows|midtones)"):
        it.gamma = 1.3
        rec.append("gamma 1.3")

    if _has(p, r"\bmute", r"no (sound|audio)", r"remove (the )?(audio|sound)", r"without (audio|sound)", r"silent video",
            r"awaa?z hata", r"awaa?z band"):
        it.mute = True
        rec.append("mute original audio")
    # a complaint, not an instruction: "audio sunai nahi de raha", "awaaz nahi aa rahi", "pehle jaisa audio la do"
    _AUD = r"(audio|sound|awaa?z|aawaa?z|awaj|aavaa?z|voice|volume|aawaj)"
    if _has(p, _AUD + r"\w*\s.{0,25}\b(nahi|nhi|nai|na|not|no)\b.{0,15}\b(aa|aa?\s*ra|sun|de|chal|hear|work|coming|aata|aati)",
            r"\b(sunai|sunaai|sunayi)\s*(hi\s*)?(nahi|nhi|nai|na)\b", r"\bcan'?t hear\b", r"\bno sound (is )?coming\b",
            _AUD + r"\w*\s+(hi\s+|bhi\s+)?(nahi|nhi|nai)\s+(hai|h|he|hain)\b",
            _AUD + r"\w*\s.{0,25}\b(wapas|vapas|wapis|waapas|back|phele|pehle|pahle)\b",
            r"\b(phele|pehle|pahle)\s+(jaisa|jaise|wala)\s+" + _AUD, r"\bunmute\b", _AUD + r"\s+(on|chalu|wapas)\s+(karo|kar do|kr do)"):
        it.restore_audio = True
        it.mute = False
        if it.remove_silence and not _has(p, r"silen", r"dead air", r"\bpauses?\b", r"khamosh"):
            it.remove_silence = False  # "awaaz nahi aa rahi" is about the sound, not about pauses in speech
        it.auto = False
        rec[:] = [r for r in rec if r not in ("mute original audio", "remove silence") and not r.startswith("auto edit")]
        rec.append("bring the original sound back (unmuted, normal level)")
    if _has(p, r"\blouder\b", r"(increase|boost|raise|turn up) (the )?(volume|audio|sound)", r"volume up", r"awaa?z badha"):
        it.loudness = "louder"
        rec.append("louder")
    elif _has(p, r"\bquieter\b", r"(decrease|lower|reduce|turn down) (the )?(volume|audio|sound)", r"volume down",
              r"awaa?z kam"):
        it.loudness = "quieter"
        rec.append("quieter")

    _parse_audio_controls(p, it, rec)

    m = re.search(r"watermark\s*(?:text)?\s*[:=]?\s*[\"“']([^\"”']{1,40})[\"”']", raw, re.I) or \
        re.search(r"watermark\s*[:=]?\s*(@\w{1,30})", raw, re.I)
    if m:
        it.watermark = m.group(1).strip()
        rec.append(f"watermark '{it.watermark}'")

    if _has(p, r"\bidle\b", r"frozen", r"\bfreeze", r"static (parts|scenes|shots|frames)", r"still (parts|frames)",
            r"nothing (is )?happen", r"kuch nahi ho raha"):
        it.remove_idle = True
        rec.append("remove idle/frozen parts")

    if _has(p, r"\bgif\b"):
        it.export_gif = True
        rec.append("export GIF")
    if _has(p, r"\bmp3\b", r"extract (the )?(audio|sound|music)", r"audio file", r"sirf (audio|awaa?z)"):
        it.export_mp3 = True
        rec.append("export MP3")


def _parse_style(p: str, it: Intent, rec: list[str]) -> None:
    """Named pro looks and "give me N versions"."""
    if _has(p, r"midnight", r"premium", r"\bminimal", r"dark blue", r"elegant"):
        it.style = "midnight_drift"
    elif _has(p, r"violet", r"authority", r"blue.?purple", r"purple", r"bold gradient"):
        it.style = "violet_authority"
    elif _has(p, r"kinetic", r"\bglow", r"neon", r"cyan", r"indigo", r"motion accent"):
        it.style = "cyan_kinetic"
    if it.style:
        rec.append(f"{it.style.replace('_', ' ')} look")
    m = re.search(r"\b([23]|two|three)\s+(versions|variations|options|styles|looks|variants)", p)
    if m:
        it.variations = {"two": 2, "three": 3}.get(m.group(1), None) or int(m.group(1))
    elif _has(p, r"edit like a pro", r"\bvariations\b", r"\bversions\b", r"different looks", r"multiple (styles|looks)"):
        it.variations = 3
    if it.variations > 1:
        rec.append(f"{it.variations} styled versions")
