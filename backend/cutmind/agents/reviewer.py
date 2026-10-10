"""Reviewer agent: checks the RENDERED file against the prompt and scores every agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..ffmpeg_utils import decode_check, detect_silence, extract_frame, measure_loudness, probe
from ..fx_catalog import BW_PASS
from ..intent import Intent
from ..plan import FADE_IN, EditPlan
from ..renderer import extra_path
from ..styles import STYLES
from .analyzer import ProjectAnalysis
from .cutter import window, word_cut_inside

PASS_POINTS = 10
FAIL_POINTS = -15
SCORED_AGENTS = ("director", "analyzer", "cutter", "audio", "color", "effects")
# Core instructions weigh more in the 0-100 scores: one failed core check must be able to trigger a retry.
CHECK_WEIGHTS = {"duration": 3, "captions_present": 3, "aspect_ratio": 3, "file_plays": 3, "silence_removed": 2,
                 "color_applied": 2, "music_present": 2, "transitions_present": 2, "resolution": 2,
                 "no_unrequested_trim": 3, "orientation": 2, "reverse_playback": 2, "muted": 2, "extras_exported": 2,
                 "idle_removed": 2}


@dataclass
class Check:
    name: str
    owner: str
    passed: bool
    detail: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def points(self) -> int:
        return PASS_POINTS if self.passed else FAIL_POINTS

    @property
    def weight(self) -> int:
        return CHECK_WEIGHTS.get(self.name, 1)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["points"] = self.points
        d["weight"] = self.weight
        return d


def _weighted(checks: list[Check]) -> float:
    total = sum(c.weight for c in checks)
    return round(100.0 * sum(c.weight for c in checks if c.passed) / total, 1)


@dataclass
class Review:
    checks: list[Check]

    @property
    def agent_scores(self) -> dict[str, float]:
        scores: dict[str, float] = {}
        for agent in SCORED_AGENTS:
            mine = [c for c in self.checks if c.owner == agent]
            scores[agent] = 100.0 if not mine else _weighted(mine)
        return scores

    @property
    def match_percent(self) -> float:
        return _weighted(self.checks) if self.checks else 0.0

    def failed_for(self, agent: str) -> list[Check]:
        return [c for c in self.checks if c.owner == agent and not c.passed]

    def fixable_failures(self, agent: str) -> list[Check]:
        """Failed checks a retry could change (not e.g. "no speech in the footage")."""
        return [c for c in self.failed_for(agent) if c.data.get("fixable", True)]

    def to_dict(self) -> dict[str, Any]:
        return {"checks": [c.to_dict() for c in self.checks], "agent_scores": self.agent_scores,
                "match_percent": self.match_percent}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Review:
        """Back from a checkpoint / to_dict()."""
        return cls([Check(c["name"], c["owner"], c["passed"], c["detail"], c.get("data") or {}) for c in d["checks"]])


# ---- pixel helpers ---------------------------------------------------------------------------------
BOX_RGB = np.array([124, 92, 255], dtype=np.int16)  # caption box colour (#7C5CFF)


def box_fraction(frame: np.ndarray, position: str, box_hex: str | None = None) -> float:
    """Fraction of pixels in the caption band that match the caption box colour."""
    h, w = frame.shape[:2]
    band = {"bottom": (0.62, 0.99), "center": (0.30, 0.70), "top": (0.01, 0.38)}[position]
    # captions are centred: look at the middle 40% of the width so short captions still register
    region = frame[int(h * band[0]): int(h * band[1]), int(w * 0.3): int(w * 0.7)].astype(np.int16)
    target = BOX_RGB if not box_hex else np.array([int(box_hex[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.int16)
    close = np.all(np.abs(region - target) < np.array([45, 45, 60]), axis=2)
    return float(close.mean())


def center_crop_to_aspect(frame: np.ndarray, w: int, h: int) -> np.ndarray:
    fh, fw = frame.shape[:2]
    target = w / h
    if fw / fh > target:
        nw = int(fh * target)
        x = (fw - nw) // 2
        return frame[:, x:x + nw]
    nh = int(fw / target)
    y = (fh - nh) // 2
    return frame[y:y + nh]


def color_stats(frame: np.ndarray) -> dict[str, float]:
    """Stats on the central region (avoids captions/titles at the edges)."""
    h, w = frame.shape[:2]
    c = frame[int(h * 0.3): int(h * 0.6), int(w * 0.2): int(w * 0.8)].astype(np.float32)
    r, g, b = c[..., 0].mean(), c[..., 1].mean(), c[..., 2].mean()
    chroma = (c.max(axis=2) - c.min(axis=2)).mean()
    return {"r": float(r), "g": float(g), "b": float(b), "luma": float(0.299 * r + 0.587 * g + 0.114 * b),
            "chroma": float(chroma), "warm": float(r - b)}


# ---- the reviewer -------------------------------------------------------------------------------------
class ReviewerAgent:
    name = "reviewer"

    def review(self, plan: EditPlan, output: Path, intent: Intent, analysis: ProjectAnalysis,
               sources: dict[str, Path], positions: dict[str, int], available: float | None,
               options: dict[str, Any] | None = None, llm_disagreements: list[str] | None = None) -> Review:
        options = options or {}
        checks: list[Check] = []
        add = checks.append

        copy_mode = bool(options.get("copy_edit"))  # Copy an Edit: the liked video is the instruction
        add(Check("intent_understood", "director", not intent.is_empty() or copy_mode,
                  f"understood: {', '.join(intent.recognized)}" if not intent.is_empty()
                  else "copying the liked video (Copy an Edit)" if copy_mode
                  else "no editing instruction recognised in the prompt; a default clean edit was made"))

        if llm_disagreements is not None:
            add(Check("llm_intent_correct", "director", not llm_disagreements,
                      "LLM read every explicit instruction" if not llm_disagreements
                      else f"LLM misread (auto-corrected): {'; '.join(llm_disagreements)[:250]}"))

        bad = [cid for cid, a in analysis.clips.items() if a.duration <= 0 or a.transcription.startswith("error")]
        add(Check("analysis_complete", "analyzer", not bad,
                  "all clips measured" if not bad else f"analysis problems on {bad}"))

        if not output.exists():
            add(Check("file_plays", "director", False, "no output file was produced"))
            return Review(checks)
        ok, err = decode_check(output)
        add(Check("file_plays", "director", ok, "full decode without errors" if ok else f"decode errors: {err[:200]}"))
        info = probe(output)

        # duration
        total_plan = plan.total_duration()
        overlaps = sum(t.duration for t in plan.transitions if t.after >= 0)
        if intent.target_duration:
            expected = intent.target_duration
            if available is not None and available - overlaps < expected:
                expected = available - overlaps  # not enough material: use everything
            tol = max(1.0, 0.1 * expected)
            passed = abs(info.duration - expected) <= tol
            add(Check("duration", "cutter", passed,
                      f"{info.duration:.2f}s vs expected {expected:.2f}s (+/-{tol:.1f}s)",
                      {"actual": round(info.duration, 3), "expected": round(expected, 3)}))
        render_ok = abs(info.duration - total_plan) <= 0.35
        add(Check("render_matches_plan", "director", render_ok,
                  f"rendered {info.duration:.2f}s, plan says {total_plan:.2f}s"))

        # canvas
        w, h = plan.canvas.size
        wanted_aspect = options.get("aspect_ratio") or intent.aspect_ratio
        aspect_ok = (info.width, info.height) == (w, h) and (wanted_aspect is None or wanted_aspect == plan.canvas.aspect_ratio)
        add(Check("aspect_ratio", "effects", aspect_ok,
                  f"{info.width}x{info.height}, canvas {plan.canvas.aspect_ratio} {w}x{h}, requested {wanted_aspect or 'any'}"))
        wanted_res = options.get("resolution") or intent.resolution
        if wanted_res:
            add(Check("resolution", "effects", min(info.width, info.height) == wanted_res,
                      f"short side {min(info.width, info.height)}px, requested {wanted_res}px"))

        # audio
        add(Check("audio_stream", "audio", info.has_audio, "audio stream present" if info.has_audio else "no audio stream"))
        if info.has_audio:
            loud = measure_loudness(output)
            src_audible = any(a.loudness.get("lufs", -99) > -60 for a in analysis.clips.values()) or bool(plan.audio.music)
            lufs = loud.get("lufs", float("-inf"))
            peak = loud.get("max_volume", 0.0)
            if not src_audible:
                add(Check("audio_levels", "audio", True, "sources have no audible audio; nothing to balance"))
            elif plan.audio.mute and not plan.audio.music:
                # muted as asked and no music: silence IS the right level (it once failed as "-99 LUFS")
                add(Check("audio_levels", "audio", peak < -50, f"original sound muted as asked (peak {peak:.1f} dB)",
                          {"lufs": lufs, "peak": peak}))
            else:
                ok_l = abs(lufs - plan.audio.target_lufs) <= 3.0 and peak <= -0.1
                add(Check("audio_levels", "audio", ok_l,
                          f"{lufs:.1f} LUFS (target {plan.audio.target_lufs}), peak {peak:.1f} dB",
                          {"lufs": lufs, "peak": peak}))

        if intent.music:
            has_track = bool(plan.audio.music)
            add(Check("music_present", "audio", has_track,
                      f"music: {plan.audio.music}" if has_track else "music was requested but no track was added"))

        # captions
        if intent.captions:
            # nobody speaks in the footage: captions are impossible, and no retry can change that
            add(Check("speech_detected", "analyzer", analysis.any_words,
                      "speech transcribed" if analysis.any_words
                      else "people talk but speech-to-text could not read clear words" if analysis.any_speech
                      else "nobody speaks in these clips, so there is nothing to caption", {"fixable": False}))
            caps = [t for t in plan.text if t.kind == "caption"]
            if not caps:
                add(Check("captions_present", "effects", False, "captions requested but none in the plan",
                          {"fixable": analysis.any_words}))
            else:
                samples = caps[: min(3, len(caps))]
                fracs = []
                for c in samples:
                    frame = extract_frame(output, (c.start + c.end) / 2, info.width, info.height)
                    # boxed captions: look for the box colour; outline-style captions (presets): the letter colour
                    fracs.append(box_fraction(frame, c.style.position, c.style.box_color or c.style.color))
                visible = sum(f > (0.01 if samples[0].style.box_color else 0.002) for f in fracs)
                add(Check("captions_present", "effects", visible * 3 >= len(fracs) * 2,
                          f"{len(caps)} captions; visible in {visible}/{len(fracs)} sampled frames",
                          {"fractions": [round(f, 4) for f in fracs]}))
        if intent.title:
            ok_t = any(t.kind == "title" for t in plan.text)
            add(Check("title_present", "effects", ok_t, "title added" if ok_t else "title missing"))

        # silence & word boundaries
        words_cut = []
        for seg in plan.clips:
            words = analysis.get(seg.source).words
            for t in (seg.in_, seg.out):
                w = word_cut_inside(t, words)
                if w:
                    words_cut.append(f"'{w.text}'@{t:.2f}s")
        if any(a.words for a in analysis.clips.values()):
            add(Check("no_mid_word_cuts", "cutter", not words_cut,
                      "all cuts fall between words" if not words_cut else f"cuts inside words: {words_cut[:4]}"))
        if intent.remove_silence:
            left = []
            speech_only = intent.auto or "remove_silence" in intent.inferred_fields
            for seg in plan.clips:
                if speech_only and not analysis.get(seg.source).has_speech:
                    continue  # the editor only tightens talking clips; quiet scenery is not "dead air"
                for s, e in analysis.get(seg.source).silences:
                    overlap = min(e, seg.out) - max(s, seg.in_)
                    if overlap > 0.8:
                        left.append(f"{overlap:.1f}s in {seg.source}")
            out_sil: list[tuple[float, float]] = []
            if not plan.audio.music and info.has_audio:
                out_sil = [(s, e) for s, e in detect_silence(output, -35.0, 1.0) if s > 0.6 and e < info.duration - 0.6]
            passed = not left and not out_sil
            add(Check("silence_removed", "cutter", passed,
                      "no long silences left" if passed else f"silence left: plan={left[:3]} output={out_sil[:3]}"))

        # colour
        if intent.color_preset or abs(intent.brightness) > 0:
            add(self._color_check(plan, output, info, intent, sources))

        # transitions / effects
        if intent.transition:
            kinds = {t.type for t in plan.transitions}
            ok_tr = intent.transition in kinds or (len(plan.clips) == 1 and any(t.after < 0 for t in plan.transitions))
            detail = f"transitions in plan: {sorted(kinds) or 'none'} ({len(plan.transitions)})"
            fade_in = next((t for t in plan.transitions if t.after == FADE_IN), None)
            if ok_tr and fade_in is not None:
                first = color_stats(extract_frame(output, 0.02, info.width, info.height))["luma"]
                later = color_stats(extract_frame(output, min(fade_in.duration + 0.3, info.duration - 0.1), info.width, info.height))["luma"]
                ok_tr = first < max(20.0, later * 0.5)
                detail += f"; fade-in luma {first:.0f} -> {later:.0f}"
            if len(plan.clips) == 1 and intent.transition != "fade":
                ok_tr, detail = True, "single segment: no transition possible"
            add(Check("transitions_present", "effects", ok_tr, detail))
        checks.extend(self._extra_op_checks(plan, output, info, intent, analysis))
        for e in intent.effects:
            ok_e = any(x.type == e for x in plan.effects)
            add(Check(f"effect_{e}", "effects", ok_e, f"{e} {'applied' if ok_e else 'missing'}"))

        # no length requested and nothing that removes material → the edit must keep (almost) everything
        if not intent.target_duration and not intent.fast_cuts and available:
            keeps_all = not (intent.remove_silence or intent.remove_fillers or intent.slow_motion or intent.remove_idle
                             or any(e.type == "speed_ramp" for e in plan.effects)
                             # the editor chose a length for a story piece (logged with its reason)
                             or any(d.decision in ("length", "slow motion length") for d in plan.decisions))
            if keeps_all:
                floor = 0.85 * (available - overlaps)
                add(Check("no_unrequested_trim", "director", info.duration >= floor,
                          f"{info.duration:.2f}s kept of {available - overlaps:.2f}s available (no length was requested)"))

        # doing things nobody asked for is also a prompt mismatch (LLM agents sometimes "decorate")
        extras = []
        copying = any(d.skill == "copy_edit" for d in plan.decisions)
        if not intent.transition and plan.transitions:
            extras.append(f"{len(plan.transitions)} transitions")
        from_style = set(STYLES[plan.style].effects) if plan.style in STYLES else set()
        unasked = sorted({e.type for e in plan.effects} - set(intent.effects) - from_style
                         - set(options.get("manual_effects") or [])  # added by hand in the Effects panel
                         - {t.effect for t in intent.timed_effects} - ({"pulse"} if intent.bass_boost else set())
                         # subject-aware reframing that comes with spotlight / a tracked label
                         - ({"follow"} if "spotlight" in intent.effects or intent.tracked_text else set())
                         # editorial effects placed on chosen moments, each with a logged reason
                         - ({"punch"} if intent.emphasis_punch else set()) - ({"punch_static"} if intent.jumpcut_cover else set())
                         - ({"flash"} if intent.flash_accents else set())
                         - (set(BW_PASS) if intent.color_pass else set())
                         - ({"impact"} if intent.impact_hits else set())
                         # song-driven motion: slow drift on calm parts, a hit + flash on the drop
                         - ({"drift", "impact", "flash"} if any(d.skill == "song_driven" for d in plan.decisions) else set())
                         # Copy an Edit: the liked video's own zooms / B&W / flashes
                         - ({"zoom", "zoom_out", "mono", "flash", "camera_move", "shake"} if copying else set()))
        if unasked:
            extras.append(f"effects {unasked}")
        if (plan.canvas.rotate, plan.canvas.flip) != (intent.rotate, intent.flip):
            extras.append(f"rotate {plan.canvas.rotate}/flip {plan.canvas.flip}")
        if not intent.reverse_playback and any(s.reverse for s in plan.clips):
            extras.append("reverse playback")
        if not intent.watermark and any(t.kind == "watermark" for t in plan.text):
            extras.append("a watermark")
        if not intent.title and not intent.end_text and not copying and any(t.kind == "title" for t in plan.text):
            extras.append("a title")
        if not intent.captions and any(t.kind == "caption" for t in plan.text):
            extras.append("captions")
        add(Check("no_unrequested_effects", "effects", not extras,
                  "only requested effects" if not extras else f"added without being asked: {', '.join(extras)}"))
        if not intent.music:
            add(Check("no_unrequested_music", "audio", not plan.audio.music,
                      "no music (not requested)" if not plan.audio.music else f"music {plan.audio.music} was not requested"))

        # effects for part of the video: present on the segments in their window, and only there
        if intent.timed_effects:
            tl = plan.timeline()
            total = plan.total_duration()
            for t in intent.timed_effects:
                a, b = window(t, total)
                inside = {e.index for e in tl if a - 0.05 <= e.start + e.duration / 2 < b + 0.05}
                has = {e.target for e in plan.effects if e.type == t.effect}
                # the same effect asked at other moments too (timeline comments add up), or for the whole video
                allowed = set(inside) | {e.index for o in intent.timed_effects if o.effect == t.effect for e in tl
                                         if window(o, total)[0] - 0.05 <= e.start + e.duration / 2
                                         < window(o, total)[1] + 0.05}
                if t.effect in intent.effects:
                    allowed.add(-1)
                ok_t = bool(inside) and (inside <= has or -1 in has) and not (has - allowed)
                add(Check("timed_effects", "effects", ok_t,
                          f"{t.effect} {a:.1f}-{b:.1f}s: segments {sorted(inside)}, effect on {sorted(has)}"))
        # person tracking: the subject effects got a real path; footage without a person can't be fixed by retrying
        subj = [e for e in intent.effects if e in ("follow", "person_zoom", "spotlight")]
        subj += [t.effect for t in intent.timed_effects if t.effect in ("follow", "person_zoom", "spotlight")]
        for kind in dict.fromkeys(subj):
            tracked = [e for e in plan.effects if e.type == kind and len(e.points) >= 2]
            add(Check("subject_tracked", "effects", bool(tracked),
                      f"{kind}: following the {intent.track_target} in {len(tracked)} segment(s)" if tracked
                      else f"{kind}: no {intent.track_target} found clearly in the footage", {"fixable": False}))
        if intent.tracked_text:
            items = [t for t in plan.text if t.kind == "text" and t.text == intent.tracked_text[:60]]
            moving = [t for t in items if len(t.track) >= 2]
            add(Check("tracked_text", "effects", bool(moving),
                      f"'{intent.tracked_text}' follows the {intent.track_target} ({len(moving[0].track)} keyframes)"
                      if moving else f"'{intent.tracked_text}' could not follow anyone (no {intent.track_target} found)",
                      {"fixable": bool(items) and False}))
        if intent.text_style or intent.text_color:
            styled = [t for t in plan.text if t.kind in ("caption", "title", "text")]
            ok_s = all((not intent.text_style or t.style.preset == intent.text_style)
                       and (not intent.text_color or t.style.color == intent.text_color) for t in styled)
            if styled:
                add(Check("text_style", "effects", ok_s, f"{len(styled)} text item(s) styled "
                          f"{intent.text_style or ''} {intent.text_color or ''}".strip()))
        if intent.bass_boost:
            beats = sum(len(e.times) for e in plan.effects if e.type == "pulse")
            add(Check("bass_boost", "audio", plan.audio.bass_boost > 0 and beats > 0,
                      f"bass +{plan.audio.bass_boost:g} dB, {beats} beat punches"))

        # editorial skills: restraint limits, pacing, hook, ending (only for what the editorial brain decided)
        inferred = set(intent.inferred_fields)
        if "max_transitions" in intent.limits and not intent.transition:
            cross = [t for t in plan.transitions if t.after >= 0]
            add(Check("restraint_limits", "effects", len(cross) <= intent.limits["max_transitions"],
                      f"{len(cross)} transition(s), limit {intent.limits['max_transitions']} (hard cuts unless they mean something)"))
        tl_e = plan.timeline()
        if "cut_length" in inferred and intent.fast_cuts and len(tl_e) > 2:
            avg = sum(e.duration for e in tl_e) / len(tl_e)
            add(Check("pacing_fits", "cutter", avg <= max(2.5, (intent.cut_length or 1) * 2.2),
                      f"average shot {avg:.2f}s for a fast edit"))

        def energy(e: Any) -> float:
            a = analysis.clips.get(e.segment.source)
            if a is None:
                return 0.0
            lo, hi = int(e.segment.in_ * 2), max(int(e.segment.in_ * 2) + 1, int(e.segment.out * 2))
            win = a.motion_curve[lo:hi]
            return sum(win) / len(win) if win else a.motion

        if len(tl_e) >= 3 and (intent.hook_first or intent.ending_peak):
            # a stutter shows one moment three times: rank each piece of footage once
            unique = {(e.segment.source, e.segment.in_, e.segment.out): e for e in tl_e}
            ranked = sorted(energy(e) for e in unique.values())
            median = ranked[len(ranked) // 2]
            if intent.hook_first:
                add(Check("hook_strength", "cutter", energy(tl_e[0]) >= median,
                          f"opening shot movement {energy(tl_e[0]):.1f} vs median {median:.1f}"))
            if intent.ending_peak:
                q3 = ranked[int(len(ranked) * 0.75)]
                # 5 % tolerance: motion is sampled every 0.5 s, so a short stutter slice can measure a bit above
                # the whole piece it was cut from
                add(Check("ending_strength", "cutter", energy(tl_e[-1]) >= 0.95 * min(q3, ranked[-1]),
                          f"closing shot movement {energy(tl_e[-1]):.1f} vs top quarter {q3:.1f}"))

        if intent.color_pass and len(tl_e) >= 4:
            passed_bw = {e.target for e in plan.effects if e.type in BW_PASS}
            add(Check("colour_pass", "effects", 0 < len(passed_bw) < len(tl_e) and 0 not in passed_bw,
                      f"{len(passed_bw)} of {len(tl_e)} shots black & white"))
        if intent.kinetic_text:
            kin = [t for t in plan.text if t.kind == "text" and t.style.position == "center"]
            need = 2 if info.duration >= 6 else 1  # a 4 s edit has room for one word on the beat
            add(Check("kinetic_text", "effects", len(kin) >= need, f"{len(kin)} kinetic word(s)"))

        # clip order & coverage
        order = [positions[s.source] for s in plan.ordered_clips()]
        if copy_mode:
            pass  # shots follow the liked video's rhythm (busiest footage where it is busiest), not the file order
        elif intent.reverse_playback:
            # the whole edit plays backwards: the last clip comes first (cutter: last piece first)
            ok_o = order == sorted(order, reverse=True)
            add(Check("clip_order", "cutter", ok_o, f"clip order {order} (played backwards)"))
        elif intent.order == "original":
            # "best part pehle": the hook shot is pulled to the front; the rest stays in order
            rest = order[1:] if intent.hook_first else order
            ok_o = rest == sorted(rest)
            add(Check("clip_order", "cutter", ok_o, f"clip order {order}" + (" (hook first)" if intent.hook_first else "")))
        elif intent.order == "reverse":
            ok_o = order == sorted(order, reverse=True)
            add(Check("clip_order", "cutter", ok_o, f"clip order {order} (reverse requested)"))
        elif intent.order == "smart":
            segs = plan.ordered_clips()[1 if intent.auto else 0:]  # auto edits may open with a hook shot
            times = [analysis.get(s.source).recorded_at for s in segs if s.source in analysis.clips]
            known = [t for t in times if t is not None]
            ok_o = known == sorted(known)
            add(Check("clip_order", "cutter", ok_o, f"{len(known)} segments with a known filming time, "
                                                    f"{'in' if ok_o else 'NOT in'} filming order"))
        n_clips = len(positions)
        if (not intent.target_duration or intent.target_duration >= 2 * n_clips) and not intent.drop_clips:
            used = {s.source for s in plan.clips}
            usable = {cid for cid in positions if cid in analysis.clips}
            missing = sorted(usable - used)
            add(Check("all_clips_used", "cutter", not missing,
                      "every clip appears" if not missing else f"{len(missing)} clip(s) unused"))
        return Review(checks)

    def _color_check(self, plan: EditPlan, output: Path, info: Any, intent: Intent, sources: dict[str, Path]) -> Check:
        tl = plan.timeline()
        texts = [(t.start, t.end) for t in plan.text]
        entry = max(tl, key=lambda e: e.duration)
        t_out = None
        for frac in (0.5, 0.3, 0.7, 0.15, 0.85):
            cand = entry.start + frac * entry.duration
            if not any(s - 0.1 <= cand <= e + 0.1 for s, e in texts):
                t_out = cand
                break
        if t_out is None:
            t_out = entry.start + 0.5 * entry.duration
        seg = entry.segment
        t_src = seg.in_ + (t_out - entry.start) / entry.duration * seg.source_duration
        src_frame = extract_frame(sources[seg.source], t_src)
        w, h = plan.canvas.size
        src = color_stats(center_crop_to_aspect(src_frame, w, h))
        out = color_stats(extract_frame(output, t_out, info.width, info.height))
        preset = intent.color_preset or "none"
        d_warm, d_chroma, d_luma = out["warm"] - src["warm"], out["chroma"] - src["chroma"], out["luma"] - src["luma"]
        diff = abs(out["r"] - src["r"]) + abs(out["g"] - src["g"]) + abs(out["b"] - src["b"])
        if preset == "warm":
            passed = d_warm >= 4
        elif preset == "cool":
            passed = d_warm <= -4
        elif preset == "bw":
            passed = out["chroma"] < 12
        elif preset == "vivid":
            passed = d_chroma >= max(3.0, 0.08 * src["chroma"])
        elif preset == "sepia":
            passed = out["r"] > out["g"] > out["b"] and out["warm"] > 15
        elif preset in ("cinematic", "vintage"):
            passed = diff >= 4 or abs(d_chroma) >= 4
        else:
            passed = True
        if intent.brightness:
            passed = passed and (d_luma * intent.brightness > 0 and abs(d_luma) >= 2)
        return Check("color_applied", "color", passed,
                     f"preset {preset}: dWarm {d_warm:+.1f}, dChroma {d_chroma:+.1f}, dLuma {d_luma:+.1f} at {t_out:.2f}s",
                     {"src": src, "out": out})


    @staticmethod
    def _extra_op_checks(plan: EditPlan, output: Path, info: Any, intent: Intent,
                         analysis: ProjectAnalysis) -> list[Check]:
        """Rotate / flip / reverse / fps / gamma / mute / fades / watermark / idle removal / GIF & MP3."""
        out: list[Check] = []
        if intent.rotate or intent.flip != "none":
            ok = (plan.canvas.rotate, plan.canvas.flip) == (intent.rotate, intent.flip)
            out.append(Check("orientation", "effects", ok,
                             f"rotate {plan.canvas.rotate}, flip {plan.canvas.flip} (asked {intent.rotate}/{intent.flip})"))
        if intent.reverse_playback:
            ok = all(s.reverse for s in plan.clips)
            out.append(Check("reverse_playback", "cutter", ok, f"{sum(s.reverse for s in plan.clips)}/{len(plan.clips)} segments reversed"))
        if intent.fps:
            out.append(Check("frame_rate", "effects", abs(info.fps - intent.fps) < 0.5, f"{info.fps:g} fps (asked {intent.fps})"))
        if abs(intent.gamma - 1) > 1e-3:
            out.append(Check("gamma", "color", abs(plan.color.gamma - intent.gamma) < 1e-3, f"gamma {plan.color.gamma:g}"))
        if intent.mute:
            loud = measure_loudness(output) if info.has_audio else {}
            ok = plan.audio.mute and (bool(plan.audio.music) or loud.get("max_volume", 0.0) < -50)
            out.append(Check("muted", "audio", ok, f"mute={plan.audio.mute}, peak {loud.get('max_volume', 'n/a')} dB"))
        if intent.loudness != "normal":
            want = {"louder": -11.0, "quieter": -23.0}[intent.loudness]
            out.append(Check("loudness_change", "audio", plan.audio.target_lufs == want,
                             f"target {plan.audio.target_lufs} LUFS for '{intent.loudness}'"))
        if intent.audio_fade:
            ok = plan.audio.fade_in > 0 and plan.audio.fade_out > 0
            out.append(Check("audio_fade", "audio", ok, f"fade in {plan.audio.fade_in}s / out {plan.audio.fade_out}s"))
        if intent.watermark:
            ok = any(t.kind == "watermark" and t.text == intent.watermark for t in plan.text)
            out.append(Check("watermark_present", "effects", ok, f"watermark '{intent.watermark}' {'added' if ok else 'missing'}"))
        if intent.remove_idle:
            left = []
            for seg in plan.clips:
                for s, e in analysis.get(seg.source).idle:
                    if min(e, seg.out) - max(s, seg.in_) > 1.5:
                        left.append(f"{s:.1f}-{e:.1f}s in {seg.source}")
            out.append(Check("idle_removed", "cutter", not left, "no frozen stretches kept" if not left else f"idle kept: {left[:3]}"))
        if intent.style:
            ok = plan.style == intent.style and len(plan.overlays) > 0
            out.append(Check("style_applied", "effects", ok,
                             f"look '{plan.style}' with {len(plan.overlays)} graphic track(s) (asked {intent.style})"))
        wanted = [x for x, on in (("gif", intent.export_gif), ("mp3", intent.export_mp3)) if on]
        if wanted:
            missing = [x for x in wanted if not extra_path(output, x).exists()]
            out.append(Check("extras_exported", "effects", not missing,
                             f"{', '.join(wanted).upper()} exported" if not missing else f"missing: {missing}"))
        return out
