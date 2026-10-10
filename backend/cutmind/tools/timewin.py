"""Time modes → output windows / instants.

    whole            the whole video                            (None = the skill's whole-video setting)
    segment          shot number `index` (0-based, output order)
    between_times    start..end seconds
    intermittent     `length` s every `every` s ("beech beech me": 1 s every 4 s — said back as an assumption)
    at_time          one instant `at` (+ `length` for things that last)
    at_beats         the music's beats (instants)
    on_words         when given words are said (instants at the word start; `length` for windows)
    on_scene_change  at each cut between shots / scenes (instants)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..plan import EditPlan
from .timeline import ToolError

INTERMITTENT_ON = 1.0
INTERMITTENT_EVERY = 4.0
MOMENT = 1.0


@dataclass
class When:
    mode: str
    windows: list[tuple[float, float]] = field(default_factory=list)  # output seconds; empty for "whole"
    instants: list[float] = field(default_factory=list)               # for at_beats / on_words / scene cuts
    assumed: list[str] = field(default_factory=list)                  # said back to the user

    @property
    def whole(self) -> bool:
        return self.mode == "whole"

    def describe(self) -> str:
        if self.whole:
            return "whole video"
        if self.instants and not self.windows:
            head = ", ".join(f"{t:.1f}s" for t in self.instants[:6])
            return f"{self.mode.replace('_', ' ')}: {head}{' …' if len(self.instants) > 6 else ''}"
        head = ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in self.windows[:4])
        return f"{head}{' …' if len(self.windows) > 4 else ''}"


def resolve(time: dict[str, Any] | None, allowed: list[str], plan: EditPlan,
            beats: Callable[[], list[float]] | None = None,
            words: Callable[[], list[tuple[str, float, float]]] | None = None) -> When:
    time = dict(time or {})
    mode = time.get("mode") or "whole"
    if mode not in allowed:
        raise ToolError(f"this skill can't be used '{mode.replace('_', ' ')}' (it works: "
                        f"{', '.join(m.replace('_', ' ') for m in allowed)})")
    total = plan.total_duration()
    if mode == "whole":
        return When("whole")
    if mode == "segment":
        tl = plan.timeline()
        i = int(time.get("index", 0))
        if i < 0:  # "last shot"
            i += len(tl)
        if not 0 <= i < len(tl):
            raise ToolError(f"there is no shot {i + 1} (the edit has {len(tl)})")
        return When(mode, [(tl[i].start, tl[i].end - plan.overlap_after(i))])
    if mode == "between_times":
        a, b = float(time.get("start", 0.0)), float(time.get("end", total))
        if a < 0 or (b <= 0 and "end" in time):  # "end me": relative to the end (start -3, end 0 = last 3 s)
            a, b = max(0.0, total + a), total + b if b <= 0 else b
        if b > total + 0.05 and a < total:
            b = total
        if not 0 <= a < b <= total + 0.05:
            raise ToolError(f"{a:g}-{b:g}s is outside the video (it is {total:.1f}s long)")
        return When(mode, [(a, min(b, total))])
    if mode == "intermittent":
        assumed = []
        if "length" not in time:
            assumed.append(f"{INTERMITTENT_ON:g}s at a time")
        if "every" not in time:
            assumed.append(f"every {INTERMITTENT_EVERY:g}s")
        length = float(time.get("length", INTERMITTENT_ON))
        every = float(time.get("every", INTERMITTENT_EVERY))
        if every <= length or length <= 0:
            raise ToolError("'beech beech me' needs a gap longer than the effect")
        start = float(time.get("start", min(every / 2, max(0.0, total - length))))
        wins, t = [], start
        while t + 0.3 < total and len(wins) < 60:
            wins.append((round(t, 3), round(min(t + length, total), 3)))
            t += every
        if not wins:
            raise ToolError(f"the video ({total:.1f}s) is too short for 'beech beech me'")
        return When(mode, wins, assumed=assumed)
    if mode == "at_time":
        at = float(time.get("at", 0.0))
        if not 0 <= at < total:
            raise ToolError(f"{at:g}s is outside the video (it is {total:.1f}s long)")
        length = float(time.get("length", MOMENT))
        return When(mode, [(at, min(total, at + length))], [at])
    if mode == "at_beats":
        bt = [b for b in (beats() if beats else []) if 0 <= b < total]
        if not bt:
            raise ToolError("no beats found: add music first (or pick another time)")
        every = max(1, int(time.get("every", 1)))
        bt = bt[::every]
        return When(mode, [(b, min(total, b + 0.25)) for b in bt], bt)
    if mode == "on_words":
        ws = words() if words else []
        want = {w.lower() for w in time.get("words", [])}
        hits = [(s, e) for w, s, e in ws if not want or w.lower().strip(".,!?") in want]
        if not hits:
            raise ToolError("those words are not said in the video" if want else "nobody speaks in this video")
        return When(mode, [(s, max(e, s + 0.3)) for s, e in hits], [s for s, _ in hits])
    if mode == "on_scene_change":
        cuts = [e.start for e in plan.timeline()[1:]]
        if not cuts:
            raise ToolError("the edit has only one shot: there is no cut to use")
        return When(mode, [(c, min(total, c + 0.3)) for c in cuts], cuts)
    raise ToolError(f"unknown time mode '{mode}'")
