"""Cutter agent: selects, trims and orders segments. Removes silence/fillers, fits duration,
and never cuts inside a spoken word."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..learning import ensure_choice
from ..plan import ClipSegment
from .analyzer import ClipAnalysis, Word
from .base import AgentContext, BaseAgent, ClipRef, Feedback

FILLERS = {"um", "uh", "erm", "er", "uhm", "hmm", "ah", "umm"}
SILENCE_PAD = 0.12      # keep a little air around speech
MIN_PIECE = 0.3
DEFAULT_CHUNK = 1.2     # fast-cut chunk length (s)


class CutterDecision(BaseModel):
    order: Literal["original", "reverse", "best", "smart"] = "original"
    chunk_seconds: float = Field(1.2, ge=0.5, le=4.0, description="segment length for fast cuts")
    slow_motion: bool = False


@dataclass
class Piece:
    clip: ClipRef
    start: float
    end: float
    speed: float = 1.0
    tag: str = ""  # "stutter" / "ramp": a velocity move (the Effects agent puts its hits there)

    @property
    def dur(self) -> float:
        return (self.end - self.start) / self.speed


def _word_clean(w: Word) -> str:
    return "".join(ch for ch in w.text.lower() if ch.isalpha())


def snap_out(t: float, words: list[Word], is_start: bool) -> float:
    """Move a cut point outwards so it is never inside a word."""
    for w in words:
        if w.start < t < w.end:
            return w.start if is_start else w.end
    return t


def snap_in(t: float, words: list[Word], lo: float) -> float:
    """Move an END cut point earlier to the closest word gap (not before `lo`); fallback: word end."""
    for w in words:
        if w.start < t < w.end:
            return w.start if w.start - lo >= MIN_PIECE else w.end
    return t


def word_cut_inside(t: float, words: list[Word], tol: float = 0.04) -> Word | None:
    for w in words:
        if w.start + tol < t < w.end - tol:
            return w
    return None


def speech_pieces(a: ClipAnalysis, remove_silence: bool, remove_fillers: bool) -> list[tuple[float, float]]:
    """Usable [start, end] intervals of one clip after silence / filler removal."""
    dur = a.duration
    pieces: list[tuple[float, float]] = [(0.0, dur)]
    if remove_silence and a.has_audio and a.silences:
        keep: list[tuple[float, float]] = []
        cursor = 0.0
        for s, e in sorted(a.silences):
            if s - cursor > 0:
                keep.append((max(0.0, cursor - SILENCE_PAD if cursor > 0 else 0.0), min(dur, s + SILENCE_PAD)))
            cursor = e
        if dur - cursor > 0.05:
            keep.append((max(0.0, cursor - SILENCE_PAD), dur))
        pieces = keep
    # never cut mid-word: widen each piece to whole words
    snapped = [(snap_out(s, a.words, True), snap_out(e, a.words, False)) for s, e in pieces]
    # merge overlaps / tiny gaps, drop slivers
    merged: list[tuple[float, float]] = []
    for s, e in sorted(snapped):
        if merged and s - merged[-1][1] < 0.25:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    pieces = merged
    # fillers are cut AFTER merging, otherwise the tiny gap they leave would be merged away again
    if remove_fillers and a.words:
        fillers = [w for w in a.words if _word_clean(w) in FILLERS]
        for f in fillers:
            nxt: list[tuple[float, float]] = []
            for s, e in pieces:
                if f.end <= s or f.start >= e:
                    nxt.append((s, e))
                    continue
                if f.start - s > 0:
                    nxt.append((s, f.start))
                if e - f.end > 0:
                    nxt.append((f.end, e))
            pieces = nxt
    return [(round(s, 3), round(e, 3)) for s, e in pieces if e - s >= MIN_PIECE]


def split_at_scenes(p: Piece, a: ClipAnalysis) -> list[Piece]:
    """Split a piece at the scene cuts inside it (never through a word); slivers shorter than MIN_PIECE are dropped."""
    cuts = [x for x in a.scenes if p.start + 1e-3 < x < p.end - 1e-3 and not word_cut_inside(x, a.words)]
    edges = [p.start, *cuts, p.end]
    return [Piece(p.clip, s, e, p.speed, p.tag) for s, e in zip(edges, edges[1:], strict=False) if e - s >= MIN_PIECE]


def chunk_piece(p: Piece, chunk: float, words: list[Word]) -> list[Piece]:
    """Split a piece into ~chunk-long parts, moving each boundary to a word gap."""
    out: list[Piece] = []
    cur = p.start
    step = chunk * p.speed  # chunk is in output seconds
    while p.end - cur > step * 1.4:
        cut = snap_out(cur + step, words, is_start=False)
        if p.end - cut < MIN_PIECE:
            break
        out.append(Piece(p.clip, cur, cut, p.speed))
        cur = cut
    out.append(Piece(p.clip, cur, p.end, p.speed))
    return out


class CutterAgent(BaseAgent):
    name = "cutter"
    system_prompt = (
        "You are the Cutter agent of a video editor. Choose the clip order (original|reverse|best), the segment "
        "length for fast cuts (seconds) and whether non-speech parts should be slow motion. Exact cut points are "
        "computed by code so words are never cut. Reply with JSON only."
    )
    decision_model = CutterDecision

    def task_payload(self, ctx: AgentContext) -> dict[str, Any]:
        clips = []
        for c in ctx.clips:
            a = ctx.analysis.get(c.id) if ctx.analysis else None
            clips.append({"file": c.filename, "duration": a and round(a.duration, 2), "speech_words": a and len(a.words),
                          "quality": a and a.quality})
        it = ctx.intent
        return {"prompt": ctx.prompt, "clips": clips,
                "requested": it.model_dump(include={"target_duration", "fast_cuts", "order", "remove_silence",
                                                     "slow_motion", "beat_sync"}) if it else {}}

    # ------------------------------------------------------------------------------------------
    def transition_budget(self, ctx: AgentContext, fast: bool) -> float:
        it = ctx.intent
        if not it or not it.transition:
            return 0.0
        return 0.3 if fast else 0.5

    def build(self, ctx: AgentContext, order: str, chunk: float, slow_motion: bool,
              feedback: list[Feedback] | None) -> dict[str, Any]:
        it = ctx.intent
        assert it is not None and ctx.analysis is not None
        if not ctx.clips:
            raise ValueError("no clips to cut")
        clips = sorted(ctx.clips, key=lambda c: c.position)
        if it.drop_clips:  # "pehla clip hata do": positions in the upload order (1-based, -1 = the last one)
            gone = {clips[k - 1].id if k > 0 else clips[k].id for k in it.drop_clips if -len(clips) <= k <= len(clips) and k}
            kept = [c for c in clips if c.id not in gone]
            if kept:
                clips = kept
                ctx.decide("clips left out", ", ".join(c.filename for c in ctx.clips if c.id in gone),
                           "you asked to leave them out", "selection")
        if order == "reverse":
            clips = list(reversed(clips))
        elif order == "best":
            clips = sorted(clips, key=lambda c: -ctx.analysis.get(c.id).quality)
        elif order == "smart":
            clips = smart_order(clips, ctx)

        # beat-synced fast cuts: chunk = whole number of music beats closest to the requested length
        period = 0.0
        if it.beat_sync and ctx.music_beats and len(ctx.music_beats) > 2:
            period = median(b - a for a, b in zip(ctx.music_beats, ctx.music_beats[1:], strict=False))
            if period > 0.2 and it.fast_cuts:
                chunk = max(1, round(chunk / period)) * period
                ctx.log(self.name, "info", f"beat-sync: chunk {chunk:.2f}s ({period:.3f}s/beat)")

        # an editorial "let shots breathe" length (travel, cinematic) — not for talking clips (it would cut sentences)
        breathe = (it.cut_length if it.cut_length and it.cut_length >= 2 and "cut_length" in it.inferred_fields
                   and not ctx.analysis.any_speech else 0.0)
        if breathe and it.pace_change:
            breathe = max(1.0, breathe * it.pace_change)
        bp = ctx.blueprint  # Copy an Edit: the liked video's shots are the cut list
        per_clip: dict[str, list[Piece]] = {}
        shots: dict[str, list[Piece]] = {}  # scene-split pieces before chunking (used by song-driven cutting)
        for c in clips:
            a = ctx.analysis.get(c.id)
            speed = 0.5 if slow_motion and not a.has_speech else 1.0
            # auto edit: silence removal is for talking clips only (a quiet landscape shot is not "dead air")
            inferred = it.auto or "remove_silence" in it.inferred_fields
            spans = speech_pieces(a, it.remove_silence and (a.has_speech or not inferred), it.remove_fillers)
            if it.remove_idle and a.idle:
                spans = remove_intervals(spans, a.idle, a.words)
            pieces = [Piece(c, s, e, speed) for s, e in spans]
            if breathe and not it.fast_cuts:
                # "let shots breathe, ~4 s each" (travel / cinematic): shots of that length, one per scene part
                pieces = [q for p in pieces for q in split_at_scenes(p, a)]
                pieces = [ch for p in pieces for ch in chunk_piece(p, breathe, a.words)]
                long_enough = [p for p in pieces if p.dur >= 0.4 * breathe]  # no 0.4 s slivers between 4 s shots
                pieces = long_enough or pieces
            if bp is not None:
                shots[c.id] = [q for p in pieces for q in split_at_scenes(p, a)]
            if it.fast_cuts:
                # footage that is already cut (many shots in one file): every fast cut shows ONE shot
                pieces = [q for p in pieces for q in split_at_scenes(p, a)]
                shots[c.id] = list(pieces)
                pieces = [ch for p in pieces for ch in chunk_piece(p, chunk, a.words)]
                if period > 0.2:  # whole beats BEFORE choosing, so the length budget counts what is really kept
                    pieces = beat_quantize(pieces, period, ctx, keep_last=False)
            if pieces:
                per_clip[c.id] = pieces
        if not per_clip:
            raise ValueError("every clip is silent or too short after silence removal — nothing to keep")

        available = sum(p.dur for ps in per_clip.values() for p in ps)
        target = it.target_duration
        if target is None and it.length_change:  # "chhota karo" on a first edit: a share of the footage
            target = round(max(3.0, min(600.0, available * min(1.0, it.length_change))), 1)
            ctx.decide("length", f"{target:g}s", "you asked for a " + ("shorter" if it.length_change < 1 else "longer")
                       + " video", "pacing")
        if target is None and it.fast_cuts:
            target = max(10.0, available * 0.5)  # fast cuts without a length: keep the punchiest half
        elif target is None and breathe and available > 30:
            target = 30.0  # a travel / cinematic piece without a length: the best ~30 s, spread over every clip
            ctx.decide("length", "30s", f"shots of ~{breathe:g}s from every clip; a story piece of about 30 s holds "
                       "attention better than all the raw footage", "slow_cinematic")
        elif target is None and slow_motion:
            # slow motion doesn't make the video twice as long: same length as the footage, the best parts slowed
            source = sum(p.end - p.start for ps in per_clip.values() for p in ps)
            if available > source * 1.2:
                target = source
                ctx.decide("slow motion length", f"{source:.1f}s", "slowed down, but kept as long as your footage "
                           "(not twice as long) - the strongest parts", "slow_cinematic")
        correction = sum(float(f.data.get("expected", 0)) - float(f.data.get("actual", 0))
                         for f in feedback or [] if f.check == "duration")
        if target is not None:
            # a wildly-off previous attempt must not make us aim for a negative length: bound the nudge
            limit = max(0.5, 0.15 * target)
            correction = max(-limit, min(limit, correction))
        td = self.transition_budget(ctx, it.fast_cuts)

        selected: list[Piece] = [p for ps in per_clip.values() for p in ps]
        knob = ensure_choice(ctx)
        if "pace" in knob:  # learned from the user's reactions: a bit slower / faster than the default
            chunk *= knob["pace"]
        pace = float(knob.get("pace", 1.0))
        change = it.pace_change or 1.0  # "thoda slow / fast karo"
        if it.pace_change:
            chunk *= it.pace_change
            ctx.decide("pace", f"shots x{it.pace_change:g}", "you asked for a " + ("slower" if it.pace_change > 1
                       else "faster") + " pace: every shot " + ("longer" if it.pace_change > 1 else "shorter"), "pacing")
        song = ctx.song
        music_start = 0.0
        ctx.music_start = 0.0
        if song is not None and getattr(ctx, "song_base", None) is not None:
            song = ctx.song = ctx.song_base  # a retry starts again from the whole song
            ctx.music_beats = list(song.beats)
        song_mode = bool(song is not None and song.beats and song.energy and it.beat_sync and it.fast_cuts
                         and not ctx.analysis.any_speech and shots)
        if song_mode and it.target_duration is None:
            footage = sum(p.dur for ps in shots.values() for p in ps)
            target = min(song.duration, footage)  # the edit runs with the song (not "the punchiest half")
        elif (song is not None and it.lyrics and it.kinetic_text and it.target_duration is None and not it.length_change
              and song.duration >= 3.0 and (target is None or target > song.duration)):
            # a lyrics edit ends with the song: a 13.7 s song on 33 s of footage looped and showed no words for 20 s
            target = round(min(song.duration, available), 1)
            ctx.decide("length", f"{target:g}s", "a lyrics video runs as long as the song, so every second has its words "
                       "and the song is never repeated", "kinetic_words")
        if bp is not None and bp.shots:
            from ..blueprint import ShotRhythm

            song_mode = True  # the order and lengths are the liked video's: no hook / beat re-ordering
            selected = song_cut([q for c in clips for q in shots.get(c.id, [])], ShotRhythm(bp), bp.duration, ctx,
                                slots=bp.slots())
            slowed = sum(1 for p in selected if p.speed < 1.0)
            ctx.decide("same cuts as the liked video", f"{len(selected)} shots over {bp.duration:.1f}s",
                       "every shot as long as the matching shot of the video you liked, in the same order; the "
                       "busiest footage goes where that video is busiest"
                       + (f"; {slowed} short shot(s) slowed to fill their place" if slowed else ""), "copy_edit")
        elif song_mode:
            start = song.start_for(target or available)
            if start > 0:  # the drop would come after the end: start the song later so it lands inside
                ctx.song_base = song
                ctx.song = song = song.shifted(start)
                ctx.music_beats = list(song.beats)
                music_start = round(start, 3)
                ctx.music_start = music_start
                ctx.decide("song start", f"{start:.1f}s into the song", f"the drop now lands at {song.drop:.1f}s of "
                           "the edit instead of after its end", "song_driven")
            target = min(target or available, song.duration)
            ctx.music_beats = song.grid(target + song.period)  # punches and words need beats everywhere
            # crossfades overlap neighbouring shots: cut that much more song so the edit keeps its length
            t_song = target or available
            if td:
                t_song = min(song.duration, t_song + td * max(0, len(song_slots(song, t_song, pace, change)) - 1))
            selected = song_cut([q for c in clips for q in shots.get(c.id, [])], song, t_song, ctx, pace, change=change)
        elif target is not None:
            for _ in range(2):  # second pass budgets for the number of transition overlaps
                n_est = max(1, len(selected))
                t_eff = target + correction + td * (n_est - 1)
                selected = self.fit(ctx, per_clip, clips, t_eff, it.fast_cuts,
                                    max(MIN_PIECE, 0.4 * breathe))
        if not selected:
            raise ValueError("could not select any segment")
        if (it.auto or it.hook_first) and not song_mode:  # song mode already put the strongest shots on the loud parts
            selected = hook_first(selected, ctx)
        if it.ending_peak and not song_mode:
            selected = peak_last(selected, ctx)
        if period > 0.2 and it.fast_cuts and not song_mode:
            selected = beat_quantize(selected, period, ctx)
        if it.slow_end and selected and selected[-1].speed == 1.0 and selected[-1].end - selected[-1].start >= 0.4:
            # "end me slow motion": the closing shot plays at half speed (same length on screen, half the footage)
            last = selected[-1]
            mid = round(last.start + (last.end - last.start) / 2, 3)
            # keep the half where more happens: the ending is the strongest moment, held
            later = span_energy(last.clip.id, mid, last.end, ctx) > span_energy(last.clip.id, last.start, mid, ctx)
            selected[-1] = (Piece(last.clip, mid, last.end, 0.5, last.tag) if later
                            else Piece(last.clip, last.start, mid, 0.5, last.tag))
            ctx.decide("slow-motion ending", f"{last.clip.filename} {last.start:.1f}s", "the closing shot slowed down so "
                       "the edit ends on a held moment", "strong_ending")
        if it.speed_moves:
            selected = velocity_moves(selected, ctx)
        if it.exclude_ranges:  # timeline comment "ye part hata do": that shot's footage is left out
            kept = cut_out_ranges(selected, it.exclude_ranges)
            if kept:
                ctx.decide("part cut out", f"{len(it.exclude_ranges)} part(s)", "you commented 'hata do' on the "
                           "timeline there", "selection")
                selected = kept
        if it.timed_effects:
            # "zoom in for the first 3 s, then zoom out": cut the timeline at 3 s so each part gets its own effect
            out_total = sum(p.dur for p in selected)
            points = sorted({x for t in it.timed_effects for x in window_points(t, out_total)})
            selected = split_at_output_times(selected, points, ctx)
        if it.reverse_playback:
            # play the whole edit backwards: short pieces (reverse buffers frames in RAM), last piece first
            short = [q for p in selected for q in split_piece(p, REVERSE_CHUNK)]
            selected = list(reversed(short))
        segs = [
            ClipSegment(source=p.clip.id, **{"in": round(p.start, 3)}, out=round(p.end, 3), order=i, speed=p.speed,
                        reverse=it.reverse_playback)
            for i, p in enumerate(selected)
        ]
        moves: dict[str, list[int]] = {}
        for i, p in enumerate(selected):
            if p.tag:
                moves.setdefault(p.tag, []).append(i)
        total = sum(p.dur for p in selected)
        ctx.log(self.name, "info", f"{len(segs)} segments, {total:.2f}s of {available:.2f}s available "
                                   f"(target {target and round(target, 2)}, order={order})")
        return {"clips": [s.model_dump(by_alias=True) for s in segs], "available_duration": round(available, 3),
                "moves": moves, "music_start": music_start}

    def fit(self, ctx: AgentContext, per_clip: dict[str, list[Piece]], clips: list[ClipRef], t_eff: float,
            fast: bool, min_len: float = MIN_PIECE) -> list[Piece]:
        """Pick pieces so the summed output duration ≈ t_eff, spread fairly over all clips."""
        assert ctx.analysis is not None
        available = {cid: sum(p.dur for p in ps) for cid, ps in per_clip.items()}
        total_avail = sum(available.values())
        if total_avail <= t_eff + 0.05:
            return [p for c in clips for p in per_clip.get(c.id, [])]
        # budget per clip proportional to its material, but every clip gets at least ~1.5s
        ids = [c.id for c in clips if c.id in per_clip]
        floor = min(1.5, t_eff / len(ids))
        budget = {cid: max(min(floor, available[cid]), t_eff * available[cid] / total_avail) for cid in ids}
        scale = t_eff / sum(budget.values())
        budget = {cid: b * scale for cid, b in budget.items()}

        chosen: list[Piece] = []
        for cid in ids:
            pieces = per_clip[cid]
            words = ctx.analysis.get(cid).words
            remaining = budget[cid]
            if fast and len(pieces) > 1:
                # evenly spaced chunks across the clip (keeps variety), in time order
                need = sum(1 for _ in pieces)
                avg = available[cid] / need
                k = max(1, min(need, round(remaining / avg)))
                idxs = sorted({round(i * (need - 1) / max(1, k - 1)) for i in range(k)}) if k > 1 else [0]
                # evenly spaced first; if those are short (many small shots) the rest fill the budget
                candidates = [pieces[i] for i in idxs] + [q for j, q in enumerate(pieces) if j not in idxs]
            else:
                candidates = pieces
            first = len(chosen)
            for p in candidates:
                if remaining <= 0.25:
                    break
                if p.dur <= remaining + 0.05:
                    chosen.append(p)
                    remaining -= p.dur
                else:
                    new_end = snap_in(p.start + remaining * p.speed, words, p.start)
                    if new_end - p.start >= min_len:  # a leftover budget never becomes a sliver shot
                        chosen.append(Piece(p.clip, p.start, new_end, p.speed))
                        remaining -= (new_end - p.start) / p.speed
                    break
            chosen[first:] = sorted(chosen[first:], key=lambda q: q.start)  # keep each clip in time order
        # final exact trim of the last segment if we overshot (only where no word is cut)
        over = sum(p.dur for p in chosen) - t_eff
        if chosen and over > 0.05:
            last = chosen[-1]
            words = ctx.analysis.get(last.clip.id).words
            new_end = snap_in(last.end - over * last.speed, words, last.start)
            if new_end - last.start >= MIN_PIECE:
                chosen[-1] = Piece(last.clip, last.start, new_end, last.speed)
        return chosen

    # ------------------------------------------------------------------------------------------
    def rules(self, ctx: AgentContext, feedback: list[Feedback] | None) -> dict[str, Any]:
        it = ctx.intent
        assert it is not None
        return self.build(ctx, it.order, it.cut_length or DEFAULT_CHUNK, it.slow_motion, feedback)

    def from_decision(self, ctx: AgentContext, decision: BaseModel, feedback: list[Feedback] | None) -> dict[str, Any]:
        d = CutterDecision.model_validate(decision)
        return self.build(ctx, d.order, d.chunk_seconds, d.slow_motion, feedback)


def smart_order(clips: list[ClipRef], ctx: AgentContext) -> list[ClipRef]:
    """Messy uploads → the order they were filmed (file-name / metadata time); unknown times keep upload order."""
    assert ctx.analysis is not None
    known = [c for c in clips if ctx.analysis.get(c.id).recorded_at is not None]
    if len(known) < 2:
        return clips
    # clips without a time keep their upload slot relative to their neighbours
    ranked = sorted(known, key=lambda c: (ctx.analysis.get(c.id).recorded_at, c.position))  # type: ignore[union-attr]
    it = iter(ranked)
    return [next(it) if c in known else c for c in clips]


HOOK_SECONDS = 2.0


def hook_first(selected: list[Piece], ctx: AgentContext) -> list[Piece]:
    """Cut the most eye-catching ~2 s (most picture change, nobody talking) out of the edit and open with it.
    The total length doesn't change: the hook is moved, not copied."""
    assert ctx.analysis is not None
    if len(selected) < 2 or sum(p.dur for p in selected) < 8:
        return selected
    best: tuple[float, int, float, float] | None = None
    for i, p in enumerate(selected):
        a = ctx.analysis.get(p.clip.id)
        span = min(HOOK_SECONDS * p.speed, p.end - p.start)  # fast cuts: a whole short chunk can be the hook
        if not a.motion_curve or span < 0.8 * p.speed:
            continue
        t = p.start
        while t + span <= p.end + 1e-6:
            if not any(w.end > t and w.start < t + span for w in a.words):  # never chop a sentence
                lo, hi = int(t * 2), max(int(t * 2) + 1, int((t + span) * 2))
                window = a.motion_curve[lo:hi]
                score = sum(window) / len(window) if window else 0.0
                if best is None or score > best[0]:
                    best = (score, i, t, t + span)
            t += 0.5
    if best is None or best[1] == 0 and best[2] - selected[0].start < 0.01:
        return selected
    _score, i, hs, he = best
    p = selected[i]
    # a scrap under ~1 s left behind would flash by on its own later (seen on the user's trip reel): the hook
    # takes it along instead
    if (p.end - he) / p.speed < 1.0:
        he = p.end
    if (hs - p.start) / p.speed < 1.0:
        hs = p.start
    if i == 0 and hs == p.start:
        return selected  # the best moment already opens the edit
    rest = [q for q in (Piece(p.clip, p.start, hs, p.speed), Piece(p.clip, he, p.end, p.speed)) if q.end - q.start >= MIN_PIECE]
    ctx.log("cutter", "info", f"hook: {hs:.1f}-{he:.1f}s of {p.clip.filename} moved to the start")
    ctx.decide("opening shot", f"{hs:.1f}-{he:.1f}s of {p.clip.filename}",
               f"most picture change with nobody talking (motion {_score:.1f})", "strong_hook")
    return [Piece(p.clip, hs, he, p.speed), *selected[:i], *rest, *selected[i + 1:]]


def window(t: Any, total: float) -> tuple[float, float]:
    """Output-time [start, end) of a TimedEffect for an edit of length `total`."""
    if t.from_end:
        return max(0.0, total - t.start), total
    return min(t.start, total), total if t.end is None else min(t.end, total)


def window_points(t: Any, total: float) -> list[float]:
    a, b = window(t, total)
    return [x for x in (a, b) if 0.0 < x < total]


def cut_out_ranges(selected: list[Piece], ranges: list[list[Any]]) -> list[Piece]:
    """The pieces without the footage in `ranges` ([clip id, source in, out]); leftovers under MIN_PIECE go too."""
    out: list[Piece] = []
    for p in selected:
        parts = [(p.start, p.end)]
        for cid, a, b in ranges:
            if cid != p.clip.id:
                continue
            parts = [x for s, e in parts for x in ((s, min(e, float(a))), (max(s, float(b)), e)) if x[1] > x[0]]
        out += [Piece(p.clip, s, e, p.speed, p.tag) for s, e in parts if (e - s) / p.speed >= MIN_PIECE]
    return out


def split_at_output_times(selected: list[Piece], points: list[float], ctx: AgentContext) -> list[Piece]:
    """Split pieces at output times (snapped to a gap between words); joining them again is seamless."""
    assert ctx.analysis is not None
    out: list[Piece] = []
    t0 = 0.0
    for p in selected:
        t1 = t0 + p.dur
        cur = p
        for x in points:
            if t0 + MIN_PIECE <= x <= t1 - MIN_PIECE:
                cut = snap_out(p.start + (x - t0) * p.speed, ctx.analysis.get(p.clip.id).words, is_start=False)
                if cur.start + MIN_PIECE <= cut <= cur.end - MIN_PIECE:
                    out.append(Piece(cur.clip, cur.start, cut, cur.speed))
                    cur = Piece(cur.clip, cut, cur.end, cur.speed)
        out.append(cur)
        t0 = t1
    return out


def piece_energy(p: Piece, ctx: AgentContext) -> float:
    return span_energy(p.clip.id, p.start, p.end, ctx)


def span_energy(clip_id: str, start: float, end: float, ctx: AgentContext) -> float:
    """Mean picture change of start-end in a clip (the motion curve has 2 values per second)."""
    assert ctx.analysis is not None
    a = ctx.analysis.get(clip_id)
    lo, hi = int(start * 2), max(int(start * 2) + 1, int(end * 2))
    win = a.motion_curve[lo:hi]
    return sum(win) / len(win) if win else a.motion


def peak_last(selected: list[Piece], ctx: AgentContext) -> list[Piece]:
    """End on one of the strongest moments: the piece with the most movement (not the opening hook) goes last."""
    assert ctx.analysis is not None
    if len(selected) < 3:
        return selected
    i = max(range(1, len(selected)), key=lambda k: piece_energy(selected[k], ctx))
    if i == len(selected) - 1 or any(w.end > selected[i].start and w.start < selected[i].end
                                     for w in ctx.analysis.get(selected[i].clip.id).words):
        return selected  # already last, or it is part of a sentence (moving it would break the speech)
    ctx.decide("ending", f"{selected[i].start:.1f}-{selected[i].end:.1f}s of {selected[i].clip.filename}",
               "the most energetic moment closes the video", "strong_ending")
    return [*selected[:i], *selected[i + 1:], selected[i]]


def beat_quantize(selected: list[Piece], period: float, ctx: AgentContext, keep_last: bool = True) -> list[Piece]:
    """Beat-synced cuts: the leftover end of a clip and budget-trimmed pieces are rounded to whole beats, so every
    cut after them still lands on the music. Never cuts a word, never reuses footage of another piece."""
    assert ctx.analysis is not None
    out: list[Piece] = []
    for i, p in enumerate(selected):
        beats = p.dur / period
        if (keep_last and i == len(selected) - 1) or abs(beats - round(beats)) < 0.03:
            out.append(p)
            continue
        a = ctx.analysis.get(p.clip.id)
        others = [q for q in selected if q is not p and q.clip.id == p.clip.id]
        nxt_scene = min((x for x in a.scenes if x > p.end - 1e-3), default=a.duration)  # never grow into the next shot
        fixed = None
        # nearest whole number of beats first, then one more / one fewer (a word may sit on the nearest one)
        lo = int(beats)
        for n in sorted({lo - 1, lo, lo + 1, lo + 2} - {-1, 0}, key=lambda n: abs(n - beats)):
            end = p.start + n * period * p.speed
            if (end <= min(a.duration - 0.02, max(p.end, nxt_scene)) and end - p.start >= MIN_SEG and not word_cut_inside(end, a.words)
                    and not any(q.start < end and q.end > p.start for q in others)):
                fixed = Piece(p.clip, p.start, round(end, 3), p.speed, p.tag)
                break
        if fixed is not None:
            out.append(fixed)
        elif beats >= 1 or not out:
            out.append(p)  # words or footage don't allow it: keep (the next cuts drift by this piece only)
        # else: a sliver under one beat that can't be fixed is dropped
    return out


# song energy at the start of a cut → seconds per cut (loud = short cuts, quiet = long ones)
ENERGY_CUTS = ((0.75, 0.5), (0.45, 1.0), (0.0, 2.0))


def song_slots(song: Any, target: float, pace: float = 1.0, change: float = 1.0) -> list[tuple[float, float]]:
    """(start, end) of every cut along the song: each cut is a whole number of real beats, its length set by the
    song's energy there; the drop always starts a new cut."""
    # every beat (gaps of a drum-less intro filled, continued to the end); the drop is on it
    bounds = [0.0, *[b for b in song.grid(target + song.period) if b > max(0.15, 0.6 * song.period)]]
    slots: list[tuple[float, float]] = []
    i = 0
    while i < len(bounds) - 1 and bounds[i] < target - 0.15:
        t = bounds[i]
        e = song.mean_energy(t, t + song.period)
        secs = next(sec for lo, sec in ENERGY_CUTS if e >= lo) * pace
        n = max(1, round(round(secs / max(song.period, 0.2)) * change))  # "thoda slow": more beats per shot
        if song.drop is not None:  # never run across the drop
            ahead = [k for k in range(i + 1, min(i + n, len(bounds) - 1) + 1) if bounds[k] >= song.drop - 0.05]
            if ahead and bounds[i] < song.drop - 0.05:
                n = ahead[0] - i
        j = min(i + n, len(bounds) - 1)
        slots.append((t, bounds[j]))
        i = j
    if slots and slots[-1][1] > target + 0.3 and len(slots) > 1 and target - slots[-1][0] < 0.3:
        slots.pop()
    return slots


def song_cut(shots: list[Piece], song: Any, target: float, ctx: AgentContext, pace: float = 1.0,
             slots: list[tuple[float, float]] | None = None, change: float = 1.0) -> list[Piece]:
    """Cut to the song: slots from `song_slots`; the most energetic footage goes to the loudest slots, calm
    footage to quiet ones; a shot shorter than its slot is slowed down (≥ 0.5x) to fill it.
    `slots` given (Copy an Edit): exactly those cuts, `song` is then the liked video's ShotRhythm."""
    copying = slots is not None
    slots = slots if slots is not None else song_slots(song, target, pace, change)
    if not slots or not shots:
        return shots
    longest = max(b - a for a, b in slots)
    cands: list[Piece] = []
    for p in shots:  # windows no longer than the longest slot, so one shot can feed several cuts
        start = p.start
        while p.end - start >= MIN_SEG:
            end = min(p.end, start + longest * p.speed)
            cands.append(Piece(p.clip, start, end, p.speed))
            start = end
    energy = {id(c): piece_energy(c, ctx) for c in cands}
    originals = list(cands)
    rest_order = sorted(range(1, len(slots) - 1), key=lambda k: -song.mean_energy(*slots[k]))
    # the opening (hook) gets the best shot, the closing slot the next best, then by how loud the song is
    order = [0, *([len(slots) - 1] if len(slots) > 1 else []), *rest_order]
    reused = 0
    used_clips: set[str] = set()
    picked: dict[int, Piece] = {}
    used_src: dict[int, tuple[str, float, float]] = {}
    for k in order:
        need = slots[k][1] - slots[k][0]
        if not cands:  # more song than footage: the strongest shots come back (common in fan edits)
            cands = [Piece(c.clip, c.start, c.end, c.speed) for c in originals]
            energy.update({id(c): piece_energy(c, ctx) for c in cands})
            reused += 1

        def score(c: Piece, k: int = k, need: float = need) -> tuple[bool, bool, float]:
            near = any(src[0] == c.clip.id and (abs(src[2] - c.start) < 0.05 or abs(src[1] - c.end) < 0.05)
                       for kk, src in used_src.items() if abs(kk - k) == 1)  # neighbour shows the next frames
            head = span_energy(c.clip.id, c.start, min(c.end, c.start + need * c.speed), ctx)  # the part really used
            fresh = 1.6 if c.clip.id not in used_clips else 1.0  # every clip gets into the edit (like a pro would)
            return (c.dur >= need * 0.5, not near, head * fresh)
        best = max(cands, key=score)
        cands.remove(best)
        speed = 1.0 if best.dur >= need else max(0.5, best.dur / need)
        end = best.start + need * speed
        if end > best.end + 1e-6:
            end = best.end  # still short at half speed: this cut ends a little early
        piece = Piece(best.clip, best.start, round(end, 3), round(speed, 3))
        if best.end - end >= max(MIN_PIECE, song.period * 0.9):  # the rest of the window stays available
            rest = Piece(best.clip, end, best.end, best.speed)
            energy[id(rest)] = piece_energy(rest, ctx)
            cands.append(rest)
        picked[k] = piece
        used_src[k] = (best.clip.id, piece.start, piece.end)
        used_clips.add(best.clip.id)
    # every clip gets at least one shot: the calmest middle slot held by an over-used clip goes to a missing clip
    counts: dict[str, int] = {}
    for q in picked.values():
        counts[q.clip.id] = counts.get(q.clip.id, 0) + 1
    for cid in dict.fromkeys(c.clip.id for c in originals):
        if cid in counts:
            continue
        mine = [c for c in originals if c.clip.id == cid]
        spots = sorted((k for k in picked if 0 < k < len(slots) - 1 and counts[picked[k].clip.id] >= 2),
                       key=lambda k: song.mean_energy(*slots[k]))
        if not mine or not spots:
            continue
        k = spots[0]
        need = slots[k][1] - slots[k][0]
        c = max(mine, key=lambda c: (c.dur >= need * 0.5, span_energy(cid, c.start, min(c.end, c.start + need), ctx)))
        speed = 1.0 if c.dur >= need else max(0.5, c.dur / need)
        counts[picked[k].clip.id] -= 1
        picked[k] = Piece(c.clip, c.start, round(min(c.end, c.start + need * speed), 3), round(speed, 3))
        counts[cid] = 1
        ctx.decide("every clip used", f"{c.clip.filename} at {slots[k][0]:.1f}s",
                   "a calm part of the song gets this clip so none of your footage is left out", "song_driven")
    out = [picked[k] for k in range(len(slots)) if k in picked]
    if copying:
        return out
    loud = sum(1 for a, b in slots if song.mean_energy(a, b) >= ENERGY_CUTS[0][0])
    ctx.decide("song-driven cuts", f"{len(out)} cuts over {slots[-1][1]:.1f}s",
               f"{loud} short cuts on the loud parts, longer shots on the quiet parts"
               + (f"; the drop at {song.drop:.1f}s starts a new shot" if song.drop else "")
               + "; the most energetic footage is placed on the loudest moments", "song_driven")
    if reused:
        ctx.decide("shots reused", f"{reused} round(s)", "the song is longer than the footage: the strongest shots "
                   "come back instead of leaving beats empty", "song_driven")
    slowed = [p for p in out if p.speed < 1.0]
    if slowed:
        ctx.decide("slow motion to fit", f"{len(slowed)} shot(s)", "shot shorter than its beat slot: slowed down "
                   "instead of cutting off the beat", "song_driven")
    return out


MIN_SEG = 0.2  # shortest segment a plan allows (s of source)


def velocity_moves(selected: list[Piece], ctx: AgentContext) -> list[Piece]:
    """Fan-edit moves, like the reference edits: one STUTTER (a moment shown three times, then the shot goes on at
    half speed) and one TAKEOFF RAMP (half speed, then snapping to 2x). Each move keeps the output length of the
    piece it replaces, so every later cut stays on the beat. Never on the hook, the ending or speech."""
    assert ctx.analysis is not None
    if len(selected) < 5:
        return selected

    def silent(p: Piece) -> bool:
        return not any(w.end > p.start and w.start < p.end for w in ctx.analysis.get(p.clip.id).words)  # type: ignore[union-attr]

    ranked = sorted((k for k in range(1, len(selected) - 1) if selected[k].speed == 1.0 and silent(selected[k])),
                    key=lambda k: -piece_energy(selected[k], ctx))
    song = ctx.song
    starts = [sum(q.dur for q in selected[:k]) for k in range(len(selected))]
    if song is not None and song.energy:
        # with a song: the stutter goes on a loud part; the takeoff ramp is the shot that leads into the drop
        loud = [k for k in ranked if song.mean_energy(starts[k], starts[k] + selected[k].dur) >= 0.7]
        ranked = loud + [k for k in ranked if k not in loud]
        if song.drop is not None:
            into = [k for k in ranked if abs(starts[k] + selected[k].dur - song.drop) < 0.15]
            ramp_first = into[:1]
        else:
            ramp_first = []
    else:
        ramp_first = []
    out: dict[int, list[Piece]] = {}
    st = next((k for k in ranked if selected[k].dur >= 4 * MIN_SEG), None)
    merged: set[int] = set()  # pieces swallowed by a move that spans two short beat cuts
    if st is None:  # every cut is one short beat: the stutter takes this cut and the next one
        st = next((k for k in ranked if k + 2 < len(selected) and selected[k + 1].speed == 1.0
                   and selected[k].dur + selected[k + 1].dur >= 6 * MIN_SEG
                   and selected[k].end - selected[k].start >= (selected[k].dur + selected[k + 1].dur) * 5 / 12), None)
        if st is not None:
            merged.add(st + 1)
    if st is not None:
        p = selected[st]
        d = p.dur + (selected[st + 1].dur if st + 1 in merged else 0.0)
        if d >= 6 * MIN_SEG:  # 3 × d/6 repeats (= d/2), then d/4 of source at half speed (= d/2)
            r = d / 6
            tail = Piece(p.clip, p.start + r, p.start + r + d / 4, 0.5, "stutter")
        else:  # short beat: 3 × d/4 repeats, then the next d/4 at normal speed
            r = d / 4
            tail = Piece(p.clip, p.start + r, p.start + 2 * r, 1.0, "stutter")
        out[st] = [*(Piece(p.clip, p.start, p.start + r, 1.0, "stutter") for _ in range(3)), tail]
        ctx.decide("stutter", f"{p.start:.1f}s of {p.clip.filename}", "the most energetic moment repeats 3x "
                   "on the beat, then carries on slower", "velocity_moves")
    for k in [*ramp_first, *ranked]:
        if k in ramp_first and selected[k].dur / 4 < MIN_SEG and k - 1 >= 1 and selected[k - 1].speed == 1.0 \
                and k - 1 not in out and k - 1 not in merged and k not in out and k not in merged:
            k = k - 1  # the cut into the drop is one short beat: the ramp starts a beat earlier, still ends on the drop
        p, d = selected[k], selected[k].dur
        if k in out or k in merged or k - 1 in out or k + 1 in out or k - 1 in merged:
            continue
        two = d / 4 < MIN_SEG and k + 2 < len(selected) and k + 1 not in out and k + 1 not in merged
        if two:  # a one-beat cut is too short for a ramp: take the next cut too
            d += selected[k + 1].dur
        if d / 4 < MIN_SEG:
            continue
        end = p.start + 1.25 * d
        a = ctx.analysis.get(p.clip.id)
        if end > a.duration - 0.05 or any(p.end - 1e-3 < x < end for x in a.scenes) or any(
                q is not p and q.clip.id == p.clip.id and q.start < end and q.end > p.start for q in selected):
            continue  # not enough footage after the piece, it runs into another shot, or it is shown elsewhere
        # d/4 of source at 0.5x (= d/2) + d of source at 2x (= d/2): same length on screen
        out[k] = [Piece(p.clip, p.start, p.start + d / 4, 0.5, "ramp"), Piece(p.clip, p.start + d / 4, p.start + 1.25 * d, 2.0, "ramp")]
        if two:
            merged.add(k + 1)
        into = k in ramp_first or (two and k + 1 in ramp_first)
        ctx.decide("speed ramp", f"{p.start:.1f}s of {p.clip.filename}", "half-speed takeoff that snaps to 2x"
                   + (" right into the drop" if into else ""), "velocity_moves")
        break
    return [q for i, p in enumerate(selected) if i not in merged for q in out.get(i, [p])]


REVERSE_CHUNK = 8.0  # seconds of source per reversed segment (must stay ≤ plan.MAX_REVERSE_SECONDS)


def split_piece(p: Piece, max_len: float) -> list[Piece]:
    """Cut a piece into parts of at most `max_len` seconds of source."""
    out: list[Piece] = []
    start = p.start
    while p.end - start > max_len + 1e-6:
        out.append(Piece(p.clip, start, start + max_len, p.speed))
        start += max_len
    if p.end - start >= 0.2 or not out:
        out.append(Piece(p.clip, start, p.end, p.speed))
    else:  # a sliver left over: give it to the previous part (still ≤ max_len + 0.2)
        last = out.pop()
        out.append(Piece(p.clip, last.start, p.end, p.speed))
    return out


def remove_intervals(spans: list[tuple[float, float]], cut: list[tuple[float, float]],
                     words: list[Word]) -> list[tuple[float, float]]:
    """Remove `cut` intervals (e.g. frozen picture) from spans — but never through the middle of a word."""
    out = spans
    for cs, ce in cut:
        cs, ce = snap_out(cs, words, False), snap_out(ce, words, True)  # shrink the cut to word gaps
        if ce - cs < 0.3:
            continue
        nxt: list[tuple[float, float]] = []
        for s, e in out:
            if ce <= s or cs >= e:
                nxt.append((s, e))
                continue
            if cs - s >= MIN_PIECE:
                nxt.append((s, cs))
            if e - ce >= MIN_PIECE:
                nxt.append((ce, e))
        out = nxt
    return out
