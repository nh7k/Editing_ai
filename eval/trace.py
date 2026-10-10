"""Trace one prompt through the understanding pipeline: normalised words, exact matcher, scored shortlist, policy
decision and the tool calls that would run.

    backend/.venv/Scripts/python.exe eval/trace.py "yaha screen white kar do nomal jasia tha" --marker 4.3 --fx grade:3:5.5
    backend/.venv/Scripts/python.exe eval/trace.py "zoom karo aur dragon wala video bana do"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from cutmind.tools.fuzzy import canonical_words  # noqa: E402
from cutmind.tools.resolve import resolve  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--marker", type=float)
    ap.add_argument("--playhead", type=float)
    ap.add_argument("--fx", action="append", default=[], help="type:start:end of an effect on screen")
    ap.add_argument("--recent", action="append", default=[], help="a recent tool call as JSON")
    a = ap.parse_args()
    ctx: dict = {}
    if a.marker is not None:
        ctx["marker_time"] = a.marker
    if a.playhead is not None:
        ctx["playhead"] = a.playhead
        ctx["comment"] = False
    if a.fx:
        ctx["effects_present_at_time"] = [{"type": f.split(":")[0], "label": f.split(":")[0],
                                           "start": float(f.split(":")[1]), "end": float(f.split(":")[2])} for f in a.fx]
    if a.recent:
        ctx["recent_edits"] = [json.loads(r) for r in a.recent]
    t = time.perf_counter()
    r = resolve(a.prompt, ctx)
    ms = (time.perf_counter() - t) * 1000
    print(f"prompt      {a.prompt}")
    print(f"context     {json.dumps(ctx, ensure_ascii=False)}")
    print(f"normalised  {' '.join(canonical_words(a.prompt))}")
    for k, v in r.trace.items():
        if k != "words":
            print(f"{k:11} {json.dumps(v, ensure_ascii=False)}")
    print(f"decision    {r.decision}   ({ms:.0f} ms)")
    for i, c in enumerate(r.choices):
        print(f"  {'★' if i == 0 else ' '} {c['label']}  [score {c['score']}]")
        for call in c["calls"]:
            print(f"      → {json.dumps(call, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
