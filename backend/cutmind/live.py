"""Live editing view: what the agents are thinking and the timeline as it fills up, sent to the app while a job runs.

Every agent's decisions become `thought` events (plain words), and after an agent finishes, the part of the timeline
it owns becomes a `timeline` event (see docs/LIVE_COPY_TEMPLATES_API.md). Nothing here changes the edit: it only
reports what the agents really decided, so the app can draw the edit being built — like watching an editor work.
"""

from __future__ import annotations

from typing import Any

# what each agent is doing, shown when it starts (the real details follow as its decisions arrive)
INTRO = {
    "director": "Reading your prompt and turning it into an editor's brief",
    "analyzer": "Watching every clip: scenes, motion, speech, loudness",
    "audio": "Listening: choosing the song and setting voice / music levels",
    "cutter": "Cutting: choosing the shots and their order",
    "color": "Grading the colour",
    "effects": "Adding text, transitions and effects",
    "render": "Rendering the video",
    "review": "Watching the result and checking it against your prompt",
}


def _emit(tracker: Any, kind: str, **data: Any) -> None:
    ev = getattr(tracker, "event", None)
    if callable(ev):
        ev(kind, **data)


def started(tracker: Any, agent: str) -> None:
    if agent in INTRO:
        _emit(tracker, "thought", agent=agent, text=INTRO[agent] + "…")


def thoughts(ctx: Any, tracker: Any, agent: str) -> None:
    """Every decision not sent yet, as one plain sentence."""
    sent: set[tuple[str, str]] = ctx.__dict__.setdefault("_sent_thoughts", set())
    for d in list(getattr(ctx, "decisions", []) or []):
        key = (d.get("decision", ""), d.get("where", ""))
        if key in sent:
            continue
        sent.add(key)
        where = f" ({d['where']})" if d.get("where") and d["where"] != "whole edit" else ""
        reason = f" — {d['reason']}" if d.get("reason") else ""
        _emit(tracker, "thought", agent=agent, text=f"{d.get('decision', '')}{where}{reason}"[:300])


def _thumb(pid: str | None, cid: str, t: float) -> str | None:
    return f"/projects/{pid}/clips/{cid}/frame?t={t:.2f}" if pid else None


def video_items(ctx: Any, segments: list[dict[str, Any]], timing: list[tuple[float, float]] | None = None
                ) -> list[dict[str, Any]]:
    names = {c.id: c.filename for c in getattr(ctx, "clips", [])}
    out, cursor = [], 0.0
    ordered = sorted(segments, key=lambda s: s.get("order", 0))
    for i, s in enumerate(ordered):
        a, b, speed = float(s["in"]), float(s["out"]), float(s.get("speed", 1.0))
        start, dur = timing[i] if timing and i < len(timing) else (cursor, (b - a) / speed)
        cursor = start + dur
        out.append({"clip_id": s["source"], "filename": names.get(s["source"], s["source"]), "start": round(start, 3),
                    "dur": round(dur, 3), "in": round(a, 3), "out": round(b, 3), "speed": speed,
                    "thumb": _thumb(getattr(ctx, "project_id", None), s["source"], (a + b) / 2)})
    return out


def finished(ctx: Any, tracker: Any, agent: str) -> None:
    """After an agent: its thoughts, then the timeline tracks it filled."""
    thoughts(ctx, tracker, agent)
    sec = getattr(ctx, "sections", {}) or {}
    try:
        if agent == "cutter" and sec.get("cutter"):
            items = video_items(ctx, sec["cutter"]["clips"])
            _emit(tracker, "timeline", track="video", items=items)
            total = sum(i["dur"] for i in items)
            music = (sec.get("audio") or {}).get("music")
            if music:
                _emit(tracker, "timeline", track="music",
                      items=[{"start": 0.0, "dur": round(total, 3), "name": str(music).split("/")[-1]}])
        elif agent == "color" and sec.get("color"):
            c = sec["color"]
            _emit(tracker, "timeline", track="color", items=[{"preset": c.get("preset"), "lut": c.get("lut")}])
        elif agent == "effects" and sec.get("effects") and sec.get("cutter") and sec.get("color") is not None:
            plan_tracks(ctx, tracker)
    except Exception as exc:  # noqa: BLE001 — the live view must never break an edit
        log = getattr(ctx, "log", None)
        if callable(log):
            log("director", "warn", f"live timeline skipped: {str(exc)[:160]}")


def plan_tracks(ctx: Any, tracker: Any) -> None:
    """The whole plan is known: exact output times (transitions overlap, ramps change lengths)."""
    from .agents.director import DirectorAgent

    plan = DirectorAgent.merge(ctx.sections, ctx.decisions)
    tl = plan.timeline()
    segs = [{"source": e.segment.source, "in": e.segment.in_, "out": e.segment.out, "speed": e.segment.speed,
             "order": e.index} for e in tl]
    _emit(tracker, "timeline", track="video", items=video_items(ctx, segs, [(e.start, e.duration) for e in tl]))
    _emit(tracker, "timeline", track="text", items=[
        {"start": round(t.start, 3), "dur": round(t.end - t.start, 3), "text": t.text,
         "kind": "word" if t.kind == "text" else t.kind} for t in plan.text][:300])
    fx: list[dict[str, Any]] = []
    for e in plan.effects:
        spots = tl if e.target == -1 else [x for x in tl if x.index == e.target]
        if e.target == -1 and len(tl) > 1:
            fx.append({"start": 0.0, "dur": round(tl[-1].end, 3), "type": e.type})
            continue
        for x in spots:
            if e.times:  # punches / pulses at their own moments
                fx.extend({"start": round(x.start + t, 3), "dur": 0.2, "type": e.type} for t in e.times[:40])
            else:
                fx.append({"start": round(x.start, 3), "dur": round(x.duration, 3), "type": e.type})
    for t in plan.transitions:
        if t.after == -1:
            fx.append({"start": 0.0, "dur": t.duration, "type": f"{t.type} in"})
        elif t.after == -2 and tl:
            fx.append({"start": round(tl[-1].end - t.duration, 3), "dur": t.duration, "type": f"{t.type} out"})
        elif 0 <= t.after < len(tl):
            fx.append({"start": round(tl[t.after].end - t.duration, 3), "dur": t.duration, "type": t.type})
    fx += [{"start": s.start, "dur": round(s.end - s.start, 3), "type": f"sticker {s.emoji}"} for s in plan.stickers]
    _emit(tracker, "timeline", track="fx", items=sorted(fx, key=lambda f: f["start"])[:400])
    if plan.audio.music:
        _emit(tracker, "timeline", track="music", items=[
            {"start": 0.0, "dur": round(plan.total_duration(), 3), "name": plan.audio.music.split("/")[-1]}])


def analysis_done(ctx: Any, tracker: Any) -> None:
    a = getattr(ctx, "analysis", None)
    if a is None:
        return
    try:
        clips = list(getattr(ctx, "clips", []))
        total = sum(a.get(c.id).duration for c in clips)
        scenes = sum(len(a.get(c.id).scenes) for c in clips)
        speech = "people talk in it" if a.any_speech else "nobody speaks (a montage)"
        _emit(tracker, "thought", agent="analyzer",
              text=f"Watched {len(clips)} clip(s), {total:.0f}s of footage, {scenes} scene change(s); {speech}")
    except Exception:  # noqa: BLE001
        pass


def brief(ctx: Any, tracker: Any) -> None:
    """The professional brief the noob prompt became."""
    try:
        from .coach import pro_brief

        bp = getattr(ctx, "blueprint", None)
        if bp is not None:
            _emit(tracker, "thought", agent="director", text=f"Copying '{bp.name}': " + "; ".join(bp.summary())[:260])
        elif ctx.intent is not None:
            _emit(tracker, "thought", agent="director", text="Editor's brief: " + pro_brief(ctx.intent, ctx.spec)[:280])
    except Exception:  # noqa: BLE001
        pass


def reviewed(tracker: Any, review: Any) -> None:
    failed = [c.name.replace("_", " ") for c in review.checks if not c.passed]
    _emit(tracker, "thought", agent="review", text=f"Watched the result: {review.match_percent}% match"
          + (f"; to fix: {', '.join(failed[:4])}" if failed else "; everything asked is in"))
