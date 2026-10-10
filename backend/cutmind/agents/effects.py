"""Effects agent: canvas/reframing, captions (from transcript), titles, transitions, motion effects."""

from __future__ import annotations

import random
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..framing import Frame, follow_zoom
from ..learning import ensure_choice
from ..plan import (
    FADE_IN,
    FADE_OUT,
    AspectRatio,
    Canvas,
    ClipSegment,
    EditPlan,
    Effect,
    EffectType,
    TextItem,
    TextStyle,
    TimelineEntry,
    Transition,
    TransitionType,
)
from ..song import STYLE as SONG_STYLE
from ..text_styles import POSTER_COLORS, apply_look
from ..tracking import Track, track_clip
from .base import AgentContext, BaseAgent, Feedback
from .cutter import span_energy, window

QUICK_ANIMS = ("pop", "zoom_in", "flicker", "shake")  # animations that read within ~0.2 s (lyric words)

SUBJECT_TYPES = ("follow", "person_zoom", "spotlight")
PLATFORM_SAFE = {"instagram_reels": 0.24, "tiktok": 0.22, "youtube_shorts": 0.18, "youtube": 0.12, "linkedin": 0.12}
STOPWORDS = {"the", "a", "an", "to", "and", "or", "of", "in", "on", "at", "is", "was", "it", "um", "uh", "so", "our", "my",
             "your", "we", "i", "you", "ki", "ka", "ke", "hai", "aur", "ye", "wo"}
PIVOT_WORDS = {"but", "actually", "however", "lekin", "par", "magar", "never", "always", "secret", "important", "zaroori",
               "seriously", "kabhi", "sabse"}


def emphasis_points(timeline: list[TimelineEntry], analysis: Any) -> list[tuple[int, float, str]]:
    """Words worth a punch-in: numbers, pivot words, long words, words after a pause. One every ~6.5 s, ≥3.5 s apart."""
    cands: list[tuple[float, float, int, float, str]] = []  # (score, out_t, seg, local_t, word)
    for e in timeline:
        seg = e.segment
        words = [w for w in analysis.get(seg.source).words if seg.in_ <= w.start < seg.out]
        first_content = True
        for k, w in enumerate(words):
            clean = "".join(ch for ch in w.text.lower() if ch.isalnum())
            if clean in STOPWORDS or not clean:
                continue  # never punch "the", "to", "um"
            score = 0.0
            if any(ch.isdigit() for ch in clean):
                score += 3
            if clean in PIVOT_WORDS:
                score += 2
            if len(clean) >= 7:
                score += 1
            if k and w.start - words[k - 1].end > 0.5:
                score += 1.2
            if first_content and e.index > 0:
                score += 1.2  # a new thought: the pause before it was cut out
            first_content = False
            if score >= 1.2:  # a number / pivot word / long word, or the first word of a new thought after a pause
                local = (w.start - seg.in_) / seg.speed
                cands.append((score, e.start + local, e.index, local, w.text))
    total = timeline[-1].end if timeline else 0.0
    budget = max(1, int(total / 6.5))
    picked: list[tuple[float, float, int, float, str]] = []
    for c in sorted(cands, key=lambda c: -c[0]):
        if len(picked) >= budget:
            break
        if all(abs(c[1] - q[1]) >= 3.5 for q in picked):
            picked.append(c)
    return [(c[2], round(c[3], 3), c[4]) for c in sorted(picked, key=lambda c: c[1])]
MIN_FOUND = 0.3  # below this share of frames the "person" is too unsure to follow

MAX_CAPTION_WORDS = 4
MAX_CAPTION_SECONDS = 2.2


class EffectsDecision(BaseModel):
    captions: bool = False
    caption_position: Literal["bottom", "center", "top"] = "bottom"
    transition: TransitionType | None = None
    transition_seconds: float = Field(0.5, ge=0.1, le=1.5)
    effects: list[EffectType] = Field(default_factory=list)
    title: str | None = Field(None, max_length=80)


def default_aspect(ctx: AgentContext) -> AspectRatio:
    if ctx.analysis and ctx.clips:
        first = ctx.analysis.get(sorted(ctx.clips, key=lambda c: c.position)[0].id)
        w, h = first.width, first.height
        if ctx.intent and ctx.intent.rotate in (90, 270):
            w, h = h, w  # a rotated landscape clip is portrait
        if h > w:
            return "9:16"
        if h == w:
            return "1:1"
    return "16:9"


def caption_items(timeline: list[TimelineEntry], words_by_clip: dict[str, list[Any]], position: str,
                  size: int, box_color: str = "#7C5CFF", max_words: int = 0) -> list[TextItem]:
    """Group transcript words into short captions and map them to output time."""
    raw: list[tuple[float, float, str]] = []
    for entry in timeline:
        seg = entry.segment
        words = [w for w in words_by_clip.get(seg.source, []) if w.start >= seg.in_ - 0.02 and w.end <= seg.out + 0.02]

        def to_out(t: float, e: TimelineEntry = entry) -> float:
            s = e.segment
            frac = min(1.0, max(0.0, (t - s.in_) / s.source_duration))
            return e.start + frac * e.duration

        group: list[Any] = []
        for w in words:
            if group and (len(group) >= (max_words or MAX_CAPTION_WORDS) or w.end - group[0].start > MAX_CAPTION_SECONDS
                          or group[-1].text.endswith((".", "!", "?", ","))):
                raw.append((to_out(group[0].start), to_out(group[-1].end), " ".join(g.text for g in group)))
                group = []
            group.append(w)
        if group:
            raw.append((to_out(group[0].start), to_out(group[-1].end), " ".join(g.text for g in group)))
    total = timeline[-1].end if timeline else 0.0
    items: list[TextItem] = []
    raw.sort()
    for i, (s, e, text) in enumerate(raw):
        nxt = raw[i + 1][0] if i + 1 < len(raw) else total
        e = min(max(e, s + 0.6), nxt, total)
        if e - s < 0.15 or s >= total:
            continue
        items.append(TextItem(kind="caption", text=text.strip()[:200], start=round(s, 3), end=round(e, 3),
                              style=TextStyle(position=position, size=size, box_color=box_color)))
    return items


class EffectsAgent(BaseAgent):
    name = "effects"
    system_prompt = (
        "You are the Effects agent of a video editor. Decide: captions (bool) and their position, one transition type "
        "(fade|crossfade|zoom|wipe or null) and its length in seconds, motion effects (zoom|speed_ramp|"
        "blur_background|shake), and an optional short on-screen title. Only add what the user asked for. JSON only."
    )
    decision_model = EffectsDecision

    def task_payload(self, ctx: AgentContext) -> dict[str, Any]:
        it = ctx.intent
        return {"prompt": ctx.prompt, "segments": len(ctx.sections.get("clips", [])),
                "speech_present": bool(ctx.analysis and ctx.analysis.any_speech),
                "requested": it.model_dump(include={"captions", "transition", "effects", "title", "aspect_ratio"}) if it else {}}

    def build(self, ctx: AgentContext, d: EffectsDecision, feedback: list[Feedback] | None) -> dict[str, Any]:
        it = ctx.intent
        assert it is not None and ctx.analysis is not None
        fb = {f.check for f in feedback or []}
        aspect = ctx.options.get("aspect_ratio") or it.aspect_ratio or default_aspect(ctx)
        resolution = ctx.options.get("resolution") or it.resolution or 720
        reframe = "blur_pad" if "blur_background" in d.effects else "crop"
        canvas = Canvas(aspect_ratio=aspect, resolution=resolution, fps=it.fps or 30, reframe=reframe,
                        rotate=it.rotate, flip=it.flip)

        segments = [ClipSegment.model_validate(c) for c in ctx.sections["clips"]]
        n = len(segments)
        effects: list[Effect] = []
        for e in d.effects:
            if e == "speed_ramp" and any(s.reverse for s in segments):
                ctx.log(self.name, "warn", "speed ramp skipped: it can't be combined with reverse playback")
                continue
            if e == "speed_ramp":
                # ramp the longest segment without speech (ramping speech sounds bad)
                ordered = sorted(segments, key=lambda s: s.order)
                def has_words(s: ClipSegment) -> bool:
                    return any(s.in_ <= w.start <= s.out for w in ctx.analysis.get(s.source).words)
                quiet = [i for i, s in enumerate(ordered) if not has_words(s)]
                pool = quiet or list(range(n))
                target = max(pool, key=lambda i: ordered[i].source_duration / ordered[i].speed)
                effects.append(Effect(type="speed_ramp", target=target, strength=2.0))
            else:
                effects.append(Effect(type=e, target=-1, strength=1.0))

        # transitions between every pair (shortened when segments are short)
        transitions: list[Transition] = []
        tmp = EditPlan(canvas=canvas, clips=segments, effects=effects)
        durs = [e.duration for e in tmp.timeline()]
        if d.transition:
            td = min(d.transition_seconds, 0.3 if it.fast_cuts else d.transition_seconds)
            seq = sorted(segments, key=lambda s: s.order)
            for i in range(n - 1):
                a, b = seq[i], seq[i + 1]
                if a.source == b.source and abs(a.out - b.in_) < 1e-3 and not a.reverse:
                    continue  # one shot split for a timed effect: keep it seamless
                limit = 0.5 * min(durs[i], durs[i + 1]) - 0.01
                if limit >= 0.12:
                    transitions.append(Transition(type=d.transition, after=i, duration=round(min(td, limit), 3)))
            if d.transition == "fade":
                transitions.append(Transition(type="fade", after=FADE_IN, duration=round(min(0.5, durs[0] * 0.5), 3)))
                transitions.append(Transition(type="fade", after=FADE_OUT, duration=round(min(0.5, durs[-1] * 0.5), 3)))
        plan = EditPlan(canvas=canvas, clips=segments, effects=effects, transitions=transitions)
        timeline = plan.timeline()
        total = plan.total_duration()
        effects = self._editorial_effects(ctx, effects, timeline)
        effects = self._copy_effects(ctx, effects, timeline)
        effects = self._timed_and_beats(ctx, effects, timeline, total)
        effects, seg_points = self._subjects(ctx, effects, timeline)
        plan = EditPlan(canvas=canvas, clips=segments, effects=effects, transitions=transitions)

        text: list[TextItem] = []
        caption_size = 58 if aspect == "9:16" else 50
        if "captions_present" in fb:
            caption_size += 10
        if d.captions:
            words = {cid: ca.words for cid, ca in ctx.analysis.clips.items()}
            text += caption_items(timeline, words, d.caption_position, caption_size, max_words=it.caption_words or 0)
            plat = PLATFORM_SAFE.get(it.platform or "")
            if plat and d.caption_position == "bottom":  # keep captions above the app's own buttons
                for t in text:
                    t.style.margin = round(plat + 0.03, 3)
            if it.text_animation != "none":
                for t in text:
                    t.style.animation = it.text_animation
            if not text:
                ctx.log(self.name, "warn", "captions requested but no speech was transcribed in the kept segments")
                ctx.decide("captions", "no clear words", "speech-to-text could not read clear words in this video's "
                           "sound, so there is nothing to write as captions", "captions_none")
            if it.captions_behind:
                for t in text:
                    t.behind = True
        if it.watermark:
            text.append(TextItem(kind="watermark", text=it.watermark, start=0.0, end=round(total, 3),
                                 style=TextStyle(position="top_right", size=34, box_color=None)))
        if d.title:
            pos = "top" if d.captions and d.caption_position != "top" else "center"
            # an opening title must read at a glance on a phone: big, with a shadow (96 px looked small on a reel)
            tsize = 150 if aspect == "9:16" else 120
            text.append(TextItem(kind="title", text=d.title, start=0.0, end=round(min(2.5, total * 0.4), 3),
                                 style=TextStyle(position=pos, size=tsize, box_color=None, shadow=4.0,
                                                 outline=3.0 if not it.text_style else None,
                                                 animation=it.text_animation if it.text_animation not in ("karaoke", "none")
                                                 else "pop"),
                                 behind=it.text_behind))
        if it.end_text:  # "last me The End likh do"
            text.append(TextItem(kind="title", text=it.end_text, start=round(max(0.0, total - 2.2), 3),
                                 end=round(total, 3), style=TextStyle(position="center", size=140 if aspect == "9:16"
                                                                      else 110, box_color=None, shadow=4.0,
                                                                      outline=3.0, animation="fade")))
            ctx.decide("closing text", it.end_text, "on the last 2 seconds, as you asked", "text")
        for tt in it.timed_texts:  # timeline comments: "WOW likh do" at 4.2 s
            if tt.start < total - 0.3:
                text.append(TextItem(kind="text", text=tt.text, start=round(tt.start, 3),
                                     end=round(min(total, max(tt.end, tt.start + 0.8)), 3),
                                     style=TextStyle(position="center", size=110 if aspect == "9:16" else 90,
                                                     box_color=None, shadow=4.0, outline=3.0, animation="pop")))
                ctx.decide("text", tt.text, f"your comment on the timeline at {tt.start:.1f}s", "text")
        if it.kinetic_text:
            text += self._kinetic(ctx, timeline, total, aspect)
        text += self._copy_texts(ctx, total, aspect)
        if it.text_scale:  # "text bada karo"
            before = [t.style.size for t in text]
            for t in text:
                t.style.size = int(max(12, min(480, t.style.size * it.text_scale)))
            if not text:
                ctx.decide("text size", "no text", "there is no text in this edit to make bigger / smaller — ask for "
                           "one, e.g. 'RONALDO likh do'", "text")
            elif before == [t.style.size for t in text]:
                ctx.decide("text size", "already at the limit", "the text is already as " + ("big" if it.text_scale > 1
                           else "small") + " as it can be on this screen", "text")
            else:
                ctx.decide("text size", f"x{it.text_scale:g}", "you asked for " + ("bigger" if it.text_scale > 1
                           else "smaller") + " text", "text")
        for r in it.text_restyles:  # timeline comments on a text: "text white karo" / "ye text hata do" at 4.4 s
            at = float(r.get("at", -1))
            hit = [t for t in text if t.start - 0.05 <= at < t.end + 0.05]
            if r.get("remove"):
                text = [t for t in text if t not in hit]
            for t in hit if not r.get("remove") else []:
                upd: dict[str, Any] = {}
                if r.get("color"):
                    upd.update(color=r["color"], outline_color="#000000" if r["color"].upper() != "#000000" else "#FFFFFF")
                if r.get("scale"):
                    upd["size"] = int(max(12, min(480, t.style.size * float(r["scale"]))))
                t.style = t.style.model_copy(update=upd)
            if hit:
                ctx.decide("text at a moment", ", ".join(x.text for x in hit)[:120], ("removed" if r.get("remove") else
                           "restyled") + f" — your comment on the timeline at {at:.1f}s", "text")
        if it.text_style or it.text_color:
            for t in text:
                if t.kind in ("caption", "title"):
                    t.style = apply_look(t.style, it.text_style, it.text_color)
        if it.tracked_text:
            tracked = self._tracked_text(ctx, it.tracked_text, timeline, seg_points, effects, canvas, reframe, total)
            if tracked is not None:
                text.append(tracked)
        ctx.log(self.name, "info", f"canvas {aspect} {canvas.size[0]}x{canvas.size[1]} ({reframe}), "
                                   f"{len([t for t in text if t.kind == 'caption'])} captions, "
                                   f"{len(transitions)} transitions, effects={[e.type for e in effects]}")
        focus = None
        if it.focus:
            focus = {"mode": it.focus, "color": it.track_color}
            who = f"the person wearing {it.track_color}" if it.track_color else "the main person"
            ctx.decide("main focus", who, "cut out in every frame (person detector + segmentation); the rest "
                       + ("blurred" if it.focus == "blur" else "darkened"), "subject_focus")
        if it.text_front:
            for t in text:
                t.behind = False
        stickers = self._word_stickers(ctx, timeline, total) if it.word_stickers else []
        for st in it.moment_stickers:  # timeline comments: "rose" at 4.2 s
            a = float(st["start"])
            if a < total - 0.3:
                stickers.append({**st, "end": round(min(total, float(st["end"])), 3),
                                 "position": "top_left" if len(stickers) % 2 else "top_right"})
                ctx.decide("sticker", f"{st['emoji']} at {a:.1f}s", "your comment on the timeline", "word_stickers")
        stickers.sort(key=lambda x: x["start"])
        return {
            "focus": focus,
            "stickers": stickers,
            "canvas": canvas.model_dump(),
            "text": [t.model_dump() for t in text],
            "transitions": [t.model_dump() for t in transitions],
            "effects": [e.model_dump() for e in effects],
            "export": {"extras": [x for x, on in (("gif", it.export_gif), ("mp3", it.export_mp3)) if on]},
        }

    def _word_stickers(self, ctx: AgentContext, timeline: list[TimelineEntry], total: float) -> list[dict[str, Any]]:
        """Vlog stickers: a thing that is SAID ("ye gulab dekho") pops up as an emoji sticker at that moment."""
        from .. import stickers as stk

        assert ctx.analysis is not None
        said: list[tuple[str, float, float]] = []
        for entry in timeline:
            seg = entry.segment
            for w in ctx.analysis.get(seg.source).words:
                if seg.in_ - 0.02 <= w.start and w.end <= seg.out + 0.02:
                    frac = lambda t: min(1.0, max(0.0, (t - seg.in_) / seg.source_duration))
                    said.append((w.text, entry.start + frac(w.start) * entry.duration,
                                 entry.start + frac(w.end) * entry.duration))
        # sung words too (a lyrics edit: "pyar" is sung → a heart), song seconds moved to where the music starts
        said += [(w.text, w.start - ctx.music_start, w.end - ctx.music_start) for w in ctx.lyrics
                 if 0.0 <= w.start - ctx.music_start < total]
        if not stk.available():
            ctx.decide("word stickers", "not possible here", "no colour emoji font on this machine", "word_stickers_none")
            return []
        picked = stk.pick(said, total)
        if not said and ctx.analysis.any_speech:
            ctx.decide("word stickers", "words not readable", "people talk, but speech-to-text could not read clear "
                       "words in this sound, so it can't tell which things are named — add one yourself: stop the "
                       "video, long-press the timeline and write e.g. 'rose'", "word_stickers_none")
        elif not said:
            ctx.decide("word stickers", "nobody speaks", "no spoken words were found in the kept parts, so there is "
                       "nothing to turn into stickers", "word_stickers_none")
        elif not picked:
            ctx.decide("word stickers", "no things named", "nothing that was said has a sticker (try words like "
                       "gulab, ped, chai, beach, dog)", "word_stickers_none")
        sides = ["top_right", "top_left"]
        out = []
        for i, s in enumerate(picked):
            ctx.decide("word sticker", f"{s['emoji']} at {s['start']:.1f}s", f"'{s['word']}' is said there",
                       "word_stickers")
            out.append({**s, "position": sides[i % 2]})
        return out

    def _timed_and_beats(self, ctx: AgentContext, effects: list[Effect], timeline: list[TimelineEntry],
                         total: float) -> list[Effect]:
        """Effects for part of the video → the segments in that window; beat pulse → the real beat times."""
        it = ctx.intent
        assert it is not None and ctx.analysis is not None
        out = list(effects)
        for t in it.timed_effects:
            a, b = window(t, total)
            hit = [e.index for e in timeline if a - 0.05 <= e.start + e.duration / 2 < b + 0.05]
            if t.effect == "keyframes":  # motion engine preset: keyframes over the shot (engines/motion.py)
                from ..engines.motion import preset as motion_preset

                for i in hit:
                    pts, easing = motion_preset(t.preset or "pop_in", timeline[i].duration)
                    out.append(Effect(type="keyframes", target=i, strength=t.strength, points=pts,
                                      easing=t.easing or easing))
            else:
                out += [Effect(type=t.effect, target=i, strength=t.strength) for i in hit]
            ctx.log(self.name, "info", f"{t.effect} on {a:.1f}-{b:.1f}s → segments {hit}")
        out = self._song_motion(ctx, out, timeline)
        if not any(e.type == "pulse" for e in out):
            return out
        music = sorted(ctx.music_beats)
        expanded: list[Effect] = []
        for e in out:
            if e.type != "pulse":
                expanded.append(e)
                continue
            for entry in timeline:
                if e.target not in (-1, entry.index):
                    continue
                if music:  # the music starts at 0 in output time
                    local = [round(x - entry.start, 3) for x in music if entry.start <= x < entry.end]
                else:  # no music: the clip's own beats, mapped from source time
                    seg = entry.segment
                    local = [round((x - seg.in_) / seg.speed, 3) for x in ctx.analysis.get(seg.source).beats
                             if seg.in_ <= x < seg.out]
                strength = e.strength
                if ctx.song is not None and ctx.song.energy and not it.bass_boost:
                    en = ctx.song.mean_energy(entry.start, entry.end)
                    if en < 0.45:
                        continue  # a calm part of the song: no punches, the picture breathes
                    part = "fast" if en >= 0.75 else "medium"  # this part of the song, not the song overall
                    strength = round(min(2.0, e.strength * float(SONG_STYLE[part]["pulse"]) * (0.6 + 0.6 * en)
                                         * ensure_choice(ctx).get("punch", 1.0)), 2)
                expanded.append(Effect(type="pulse", target=entry.index, strength=strength, times=local))
        return expanded

    def _song_motion(self, ctx: AgentContext, effects: list[Effect], timeline: list[TimelineEntry]) -> list[Effect]:
        """Calm parts of the song: long shots drift slowly in (no punches there)."""
        song = ctx.song
        if song is None or not song.energy or not (ctx.intent and ctx.intent.beat_sync) or ctx.blueprint is not None:
            return effects
        busy = {e.target for e in effects if e.type not in ("pulse", "mono", "invert_mono", "silhouette", "film_bw", "flash")}
        drift = [e.index for e in timeline if e.duration >= 1.2 and e.index not in busy
                 and song.mean_energy(e.start, e.end) < 0.45]
        if drift:
            ctx.decide("slow drift", f"segments {drift[:6]}{'...' if len(drift) > 6 else ''}",
                       "quiet part of the song: slow push-in instead of beat punches", "song_driven")
        return [*effects, *(Effect(type="drift", target=i, strength=1.0) for i in drift)]

    def _editorial_effects(self, ctx: AgentContext, effects: list[Effect], timeline: list[TimelineEntry]) -> list[Effect]:
        """Emphasis punches, jump-cut cover and flash accents — each placed for a reason that is logged."""
        it = ctx.intent
        assert it is not None and ctx.analysis is not None
        out = list(effects)
        if it.emphasis_punch:
            for entry, local, word in emphasis_points(timeline, ctx.analysis):
                out.append(Effect(type="punch", target=entry, strength=1.0, times=[local]))
                ctx.decide("punch-in", f"segment {entry} at {local:.2f}s", f"emphasis on '{word}'", "emphasis_punch")
        if it.jumpcut_cover:
            seq = [e.segment for e in timeline]
            jumps = 0
            for i in range(1, len(seq)):
                a, b = seq[i - 1], seq[i]
                if not (a.source == b.source and 0 <= b.in_ - a.out < 8.0):
                    continue  # not a jump cut (another clip, or far apart in time)
                jumps += 1
                if jumps % 2 == 1:  # alternate: tight, normal, tight… so no two neighbours share the framing
                    out.append(Effect(type="punch_static", target=i))
                    ctx.decide("crop 8% tighter", f"segment {i}", f"hides the jump cut after {a.out:.2f}s (same angle)",
                               "jump_cut_cover")
        # a stutter must read as ONE moment shown three times: no colour pass / flash on its repeats
        stutter = set(ctx.sections.get("cutter", {}).get("moves", {}).get("stutter", []))
        if it.color_pass and len(timeline) >= 4:
            # every third shot (never the opening or the final one, never two in a row) goes black & white
            every = int(ensure_choice(ctx).get("bw_rate", 3))  # learned: fewer / more black & white shots
            picks = [e.index for e in timeline[1:-1] if e.index % every == every - 1 and e.index not in stutter]
            names = {"film_bw": "old-movie black & white", "invert_mono": "negative black & white",
                     "silhouette": "silhouette"}
            harsh = [x for x in ("silhouette", "invert_mono") if x in it.effects]  # only when the user asked for them
            for k, i in enumerate(picks):
                kind = harsh[k % len(harsh)] if harsh and k % 2 == 1 else "film_bw"
                out.append(Effect(type=kind, target=i))
                ctx.decide("colour pass", f"segment {i}", f"{names[kind]} shot for rhythm (one in three)", "colour_pass")
        if it.impact_hits and len(timeline) >= 4:
            moves = ctx.sections.get("cutter", {}).get("moves", {})
            ramp = moves.get("ramp", [])
            hits = [*moves.get("stutter", [])[:3], *ramp[1:2]]  # every repeat of the stutter, the snap to fast
            budget = max(len(hits), round(len(timeline) // 4 * ensure_choice(ctx).get("hits", 1.0)))
            song = ctx.song
            drop_seg = next((e.index for e in timeline if song is not None and song.drop is not None
                             and abs(e.start - song.drop) < 0.15), None)
            if drop_seg is not None and drop_seg not in hits:
                hits.append(drop_seg)
            strong = sorted((e for e in timeline[1:-1] if e.index not in hits and e.index not in ramp
                             and (song is None or not song.energy or song.mean_energy(e.start, e.end) >= 0.7)),
                            key=lambda e: -span_energy(e.segment.source, e.segment.in_, e.segment.out, ctx))
            for e in strong:
                if len(hits) >= budget:
                    break
                if all(abs(e.index - h) > 2 for h in hits):  # spread out: never on neighbouring cuts
                    hits.append(e.index)
            for i in sorted(hits):
                out.append(Effect(type="impact", target=i))
                why = ("stutter repeat" if i in moves.get("stutter", []) else "the ramp snaps to fast" if i in ramp
                       else "the drop" if i == drop_seg else "a strong cut on a loud part")
                ctx.decide("impact hit", f"segment {i}", f"zoom blur + RGB split on {why}", "velocity_moves")
        if it.flash_accents:
            # the strongest moments (most picture change) get the flash — not the first shot
            song = ctx.song
            first = [e for e in timeline if song is not None and song.drop is not None and abs(e.start - song.drop) < 0.15]
            scored = first + sorted((e for e in timeline[1:] if e.index not in stutter and e not in first),
                            key=lambda e: -span_energy(e.segment.source, e.segment.in_, e.segment.out, ctx))[: it.flash_accents]
            for e in scored:
                out.append(Effect(type="flash", target=e.index))
                ctx.decide("flash", f"segment {e.index}", "one of the most energetic shots", "flash_accent")
        return out

    def _copy_effects(self, ctx: AgentContext, effects: list[Effect], timeline: list[TimelineEntry]) -> list[Effect]:
        """Copy an Edit: B&W, white flashes and zoom moves on the same shots as in the video the user liked."""
        bp = ctx.blueprint
        if bp is None or not bp.shots or not timeline:
            return effects
        out = list(effects)
        counts = {"black & white": 0, "flash": 0, "zoom": 0}
        for e in timeline:
            shot = min(bp.shots, key=lambda s: abs(s.start - e.start))
            if abs(shot.start - e.start) > 0.35:
                continue
            if shot.bw and bp.color != "bw":
                out.append(Effect(type="mono", target=e.index))
                counts["black & white"] += 1
            if shot.flash:
                out.append(Effect(type="flash", target=e.index))
                counts["flash"] += 1
            cam = shot.camera or {}
            if cam.get("kind", "static") != "static" and len(cam.get("path", [])) >= 3:
                # the same camera move as that shot: push-in / pan / tilt / roll, on the user's footage
                out.append(Effect(type="camera_move", target=e.index, points=cam["path"][:600]))
                counts["camera move"] = counts.get("camera move", 0) + 1
                if "shake" in cam["kind"]:
                    out.append(Effect(type="shake", target=e.index, strength=round(min(2.0, max(0.5, cam["shake"] / 0.006)), 2)))
            elif shot.camera is None and shot.zoom and not any(x.target == e.index and x.type in ("zoom", "zoom_out")
                                                               for x in out):
                out.append(Effect(type="zoom" if shot.zoom == "in" else "zoom_out", target=e.index))
                counts["zoom"] += 1
        done = [f"{n} {k}" for k, n in counts.items() if n]
        if done:
            ctx.decide("same effects as the liked video", ", ".join(done),
                       "placed on the same shots as in the video you liked", "copy_edit")
        return out

    def _copy_texts(self, ctx: AgentContext, total: float, aspect: str) -> list[TextItem]:
        """Copy an Edit: the liked video's on-screen texts at the same moments, same place, similar size."""
        bp = ctx.blueprint
        it = ctx.intent
        if bp is None or not bp.texts or (it is not None and any(x in it.avoid for x in ("text", "captions", "title"))):
            return []
        tall = 1920 if aspect == "9:16" else 1080 if aspect in ("16:9", "1:1") else 1350
        items = []
        for c in bp.texts:
            a, b = c.start, min(c.end, total)
            if b - a < 0.3:
                continue
            size = int(max(28, min(150, c.size * tall / 0.72)))
            items.append(TextItem(kind="title", text=c.text, start=round(a, 3), end=round(b, 3),
                                  style=TextStyle(position=c.position, size=size, box_color=None, outline=2.0,
                                                  shadow=2.0, animation="fade")))
        if items:
            ctx.decide("same texts as the liked video", f"{len(items)} text(s)",
                       "read from the video you liked (OCR) and put at the same time and place — change them with a "
                       "prompt like 'text me mera naam likho'", "copy_edit")
        return items

    def _kinetic(self, ctx: AgentContext, timeline: list[TimelineEntry], total: float, aspect: str) -> list[TextItem]:
        """Big single words landing on the beat (kinetic typography). With a song the words move WITH it: calm
        parts get slow animations and stay 4 beats, loud parts get fast ones for 2 beats, a word hits the drop
        exactly; animations are varied per edit (seeded) and never repeat back to back."""
        it = ctx.intent
        assert it is not None
        words = it.kinetic_words or ["LET'S", "GO"]
        song = ctx.song
        beats = sorted(b for b in ctx.music_beats if 0.4 <= b < total)
        if len(beats) < 4:
            beats = [0.4 + k * 0.8 for k in range(int(max(0.0, total - 0.4) / 0.8))]
        stop = timeline[-1].start if len(timeline) > 2 else total
        w = 720 if aspect == "9:16" else 1280 if aspect == "16:9" else 1080
        short = min(w, 1280 if aspect == "9:16" else 720 if aspect == "16:9" else 1080)
        rng = random.Random(f"{ctx.job_id}|{'/'.join(words)}")
        last_anim = ""
        n_words = [0]

        mood = ensure_choice(ctx).get("text_mood", 0.0)  # learned: calmer / punchier text than the song suggests

        def level(t: float) -> str:
            order = ("slow", "medium", "fast")
            if song is None or not song.energy:
                base = 1
            else:
                e = song.mean_energy(t, t + song.period)
                base = 2 if e >= 0.75 else 1 if e >= 0.45 else 0
            return order[max(0, min(2, base + int(mood)))]

        def item(word: str, a: float, b: float, lvl: str) -> TextItem:
            nonlocal last_anim
            # fill ~85 % of the width: heavy sans letters are ~0.36 x the font size wide under libass; the poster's
            # condensed Anton ~0.31 (measured: 6 letters at 213 px = 400 px), and a poster word may be huge
            poster = it.text_style == "poster"
            px = 0.85 * w / ((0.31 if poster else 0.36) * max(3, len(word)))
            size = int(min(480 if poster else 320, max(110, px * 1080 / short)))
            palette = SONG_STYLE[lvl]["anims"] if b - a >= 0.45 else QUICK_ANIMS  # a quick word can't fly in
            anim = rng.choice([x for x in palette if x != last_anim])  # type: ignore[attr-defined]
            last_anim = anim
            look = it.text_style if it.text_style in ("poster", "bold_pop", "comic", "action", "neon", "love") else "glass"
            style = apply_look(TextStyle(position="center", size=size, box_color=None), look, it.text_color, anim)
            if look == "poster" and not it.text_color:  # each word its own colour: red, black, yellow
                fill, edge = POSTER_COLORS[n_words[0] % len(POSTER_COLORS)]
                style = style.model_copy(update={"color": fill, "outline_color": edge})
            n_words[0] += 1
            return TextItem(kind="text", text=word, start=round(a, 3), end=round(b, 3), style=style, behind=it.text_behind)

        if ctx.lyrics:
            return self._lyric_words(ctx, total, stop, item, level)
        items: list[TextItem] = []
        i, k = 0, 0
        while i < len(beats) and len(items) < 16:
            lvl = level(beats[i])
            hold = int(SONG_STYLE[lvl]["hold_beats"])  # type: ignore[call-overload]
            if i + hold >= len(beats) or beats[i + hold] > stop:
                break
            items.append(item(words[k % len(words)], beats[i], beats[i + hold], lvl))
            k += 1
            i += hold if k % len(words) else hold + 4  # after the last word: 4 beats of picture only, then again
        if song is not None and song.drop is not None and song.drop < stop - 0.5:
            near = [x for x in items if abs(x.start - song.drop) < 0.12]
            if not near:  # the drop gets the first word, landing exactly on it
                after = [b for b in beats if b > song.drop + 0.1]
                end = after[1] if len(after) > 1 else min(stop, song.drop + 1.0)
                items = [x for x in items if x.end <= song.drop or x.start >= end]
                items.append(item(words[0], song.drop, end, "fast"))
                items.sort(key=lambda x: x.start)
            ctx.decide("word on the drop", f"{song.drop:.1f}s", "the song drops here: the title word lands with it",
                       "song_driven")
        if items:
            anims = sorted({x.style.animation for x in items})
            ctx.decide("kinetic words", f"{items[0].start:.1f}-{items[-1].end:.1f}s ({len(items)} hits)",
                       f"'{' / '.join(words)}' on the beat, animations follow the song ({', '.join(anims)})"
                       + ("; drawn behind the person" if it.text_behind else ""), "kinetic_words")
        return items

    def _lyric_words(self, ctx: AgentContext, total: float, stop: float, item: Any, level: Any) -> list[TextItem]:
        """The song's own words, each one on screen while it is sung (moved by where the music starts)."""
        it = ctx.intent
        assert it is not None
        ws = [w for w in ctx.lyrics if 0.15 <= w.start - ctx.music_start < stop]
        items: list[TextItem] = []
        for n, w in enumerate(ws[:48]):
            a = w.start - ctx.music_start
            nxt = ws[n + 1].start - ctx.music_start if n + 1 < len(ws) else stop
            b = min(nxt, stop, a + 1.2, max(w.end - ctx.music_start, a + 0.4))
            if b - a >= 0.18:
                items.append(item(w.text.upper(), a, b, level(a)))
        song = ctx.song
        if song is not None and song.drop is not None and song.drop < stop - 0.5 and it.kinetic_words \
                and not any(abs(x.start - song.drop) < 0.6 for x in items):
            # no sung word on the drop: the subject's name lands there instead
            end = min(stop, song.drop + 2 * song.period)
            items = [x for x in items if x.end <= song.drop or x.start >= end]
            items.append(item(it.kinetic_words[0], song.drop, end, "fast"))
            items.sort(key=lambda x: x.start)
        if items:
            ctx.decide("lyrics on screen", f"{items[0].start:.1f}-{items[-1].end:.1f}s ({len(items)} words)",
                       "each sung word appears while it is sung; animation follows the song's energy"
                       + ("; behind the person" if it.text_behind else ""), "kinetic_words")
        return items

    def _subjects(self, ctx: AgentContext, effects: list[Effect], timeline: list[TimelineEntry]
                  ) -> tuple[list[Effect], dict[int, list[list[float]]]]:
        """Follow / zoom-on-person / spotlight and tracked text: track the person in each used clip (cached) and
        give every affected segment its path (segment-local seconds, normalised source coordinates)."""
        it = ctx.intent
        assert it is not None
        wanted = [e for e in effects if e.type in SUBJECT_TYPES]
        if not wanted and not it.tracked_text:
            return effects, {}
        if not any(e.type in ("follow", "person_zoom") for e in wanted):
            # spotlight / a name label on someone the crop cuts in half looks broken: frame on the person too
            # (subject-aware reframe; only applied where the person is really found)
            wanted.append(Effect(type="follow", target=-1))
            effects = [*effects, wanted[-1]]
            ctx.log(self.name, "info", f"subject-aware reframe: the crop follows the {it.track_target}")
        clips = {c.id: c for c in ctx.clips}
        cache = (ctx.work_dir.parent.parent / "analysis") if ctx.work_dir is not None else None
        tracks: dict[str, Track | None] = {}
        seg_points: dict[int, list[list[float]]] = {}
        for entry in timeline:
            seg = entry.segment
            if seg.reverse or seg.source not in clips:
                continue
            if seg.source not in tracks:
                try:
                    tracks[seg.source] = track_clip(clips[seg.source].media, it.track_target, cache)
                    tr = tracks[seg.source]
                    ctx.log(self.name, "info", f"tracking {it.track_target} in {clips[seg.source].filename}: "
                                               f"found in {tr.found:.0%} of frames ({tr.detector})")
                except (FileNotFoundError, OSError) as exc:
                    tracks[seg.source] = None
                    ctx.log(self.name, "warn", f"tracking unavailable: {exc}")
            tr = tracks[seg.source]
            if tr is None or tr.found < MIN_FOUND:
                continue
            first, last = tr.at(seg.in_), tr.at(seg.out)
            pts = [[0.0, *first]] if first else []
            pts += [[round((p[0] - seg.in_) / seg.speed, 3), *p[1:]] for p in tr.points if seg.in_ < p[0] < seg.out]
            if last:
                pts.append([round(entry.duration, 3), *last])
            seg_points[entry.index] = [[round(v, 4) for v in p] for p in pts]
        out = [e for e in effects if e.type not in SUBJECT_TYPES]
        for e in wanted:
            hit = [x.index for x in timeline if e.target in (-1, x.index) and x.index in seg_points]
            out += [Effect(type=e.type, target=i, strength=e.strength, points=seg_points[i]) for i in hit]
            if not hit:
                ctx.log(self.name, "warn", f"{e.type}: no {it.track_target} found clearly in the footage — left centred")
        # one subject effect per segment and type (a timed + a global request can overlap)
        seen: set[tuple[str, int]] = set()
        deduped = []
        for e in out:
            key = (e.type, e.target)
            if e.type in SUBJECT_TYPES and key in seen:
                continue
            seen.add(key)
            deduped.append(e)
        return deduped, seg_points

    def _tracked_text(self, ctx: AgentContext, words: str, timeline: list[TimelineEntry],
                      seg_points: dict[int, list[list[float]]], effects: list[Effect], canvas: Canvas, reframe: str,
                      total: float) -> TextItem | None:
        """A label that sits just above the tracked person's head and moves with them."""
        it = ctx.intent
        assert it is not None and ctx.analysis is not None
        w, h = canvas.size
        track: list[list[float]] = []
        for entry in timeline:
            pts = seg_points.get(entry.index)
            if not pts:
                continue
            a = ctx.analysis.get(entry.segment.source)
            follow = next((e for e in effects if e.type in ("person_zoom", "follow") and e.target == entry.index), None)
            if follow is not None:
                fr = Frame(a.width, a.height, w, h, "follow",
                           follow_zoom(a.width, a.height, w, h) * (1.6 if follow.type == "person_zoom" else 1.0))
            else:
                fr = Frame(a.width, a.height, w, h, reframe)
            for t, cx, cy, _bw, bh in pts:
                x, y = fr.to_output(cx, cy - bh / 2, (cx, cy) if follow is not None else None)
                track.append([round(entry.start + t, 3), round(min(max(x, w * 0.12), w * 0.88), 1),
                              round(min(max(y - h * 0.02, h * 0.1), h * 0.95), 1)])
        if len(track) < 2:
            ctx.log(self.name, "warn", f"text '{words}' can't follow anyone: no {it.track_target} found — placed at the top")
        base = TextStyle(position="top", size=60, box_color=None)
        anim = it.text_animation if it.text_animation not in ("karaoke", "typewriter") else "pop"
        style = apply_look(base, it.text_style or "name_tag", it.text_color, anim)
        return TextItem(kind="text", text=words[:60], start=0.0, end=round(total, 3), style=style, track=track)

    def rules(self, ctx: AgentContext, feedback: list[Feedback] | None) -> dict[str, Any]:
        it = ctx.intent
        assert it is not None
        d = EffectsDecision(captions=it.captions, transition=it.transition, effects=list(it.effects), title=it.title)
        return self.build(ctx, d, feedback)

    def from_decision(self, ctx: AgentContext, decision: BaseModel, feedback: list[Feedback] | None) -> dict[str, Any]:
        return self.build(ctx, EffectsDecision.model_validate(decision), feedback)
