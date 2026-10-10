"""What every Tier 1 patch must keep true. A failed check = the call is refused, the old plan stays.

Plan-level (checked here, before rendering):
  1. the plan validates (no negative / zero-length segments, transitions shorter than their shots, text inside)
  2. the length is unchanged unless the skill changes the length (`changes_duration` in its YAML)
  3. every segment reads inside its source (no "out" beyond the clip's end) from a known source
  4. the original media files are never written (the engine only gets their paths; checked by tests with
     size + modification time before / after)
Render-level (checked after rendering, tests/integration/test_tier1_*.py and the job's quality gate):
  5. the file decodes, has an audio stream, and audio and video lengths agree within 0.1 s
"""

from __future__ import annotations

from typing import Any

from ..ffmpeg_utils import probe
from ..plan import EditPlan
from .timeline import ToolError

DURATION_TOL = 0.05
_DUR_CACHE: dict[str, float] = {}


def source_duration(path: Any) -> float:
    key = str(path)
    if key not in _DUR_CACHE:
        _DUR_CACHE[key] = probe(path).duration
    return _DUR_CACHE[key]


def check(before: EditPlan, after: EditPlan, s: dict[str, Any], ctx: Any) -> None:
    after = EditPlan.model_validate(after.to_json())  # 1
    if not s.get("changes_duration"):
        d0, d1 = before.total_duration(), after.total_duration()
        if abs(d0 - d1) > DURATION_TOL:  # 2
            raise ToolError(f"internal: {s['id']} changed the length ({d0:.2f}s → {d1:.2f}s) but must not")
    for seg in after.clips:  # 3
        src = ctx.sources.get(seg.source)
        if src is None:
            raise ToolError(f"internal: {s['id']} used an unknown clip '{seg.source}'")
        dur = source_duration(src)
        if seg.hold:  # a freeze frame reads one frame at `in`
            if seg.in_ > dur - 0.03:
                raise ToolError(f"internal: {s['id']} holds a frame at {seg.in_:.2f}s but {seg.source} is {dur:.2f}s long")
            continue
        if seg.out > dur + 0.06:
            raise ToolError(f"internal: {s['id']} reads {seg.source} up to {seg.out:.2f}s but it is {dur:.2f}s long")
