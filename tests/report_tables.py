"""Print Markdown tables from tests/results/e2e_<mode>.json (used to build TEST_REPORT.md)."""

import json
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def table(mode: str) -> str:
    path = RESULTS / f"e2e_{mode}.json"
    if not path.exists():
        return f"_no results file for {mode}_\n"
    rows = json.loads(path.read_text(encoding="utf-8"))
    out = ["| # | Prompt | Duration (s) | Size | Audio | Plays | LUFS | Segs | Caps | Trans | Match % | Failed checks | Rounds |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        lufs = f"{r['lufs']:.1f}" if isinstance(r.get("lufs"), (int, float)) else "-"
        out.append(
            f"| {i} | {r['prompt']} | {r['duration']:.2f} | {r['width']}x{r['height']} | {r['audio_codec'] if r['has_audio'] else 'none'} "
            f"| {'yes' if r['plays'] else 'NO'} | {lufs} | {r['segments']} | {r['captions']} | {r['transitions']} "
            f"| {r['match_percent']} | {', '.join(r['failed_checks']) or '-'} | {r['rounds']} |"
        )
    extras = [f"- `{r['key']}`: {json.dumps(r['extra'])}" for r in rows if r.get("extra")]
    modes = {r["key"]: r.get("modes") for r in rows}
    return "\n".join(out) + "\n\nIndependent pixel/audio measurements:\n" + "\n".join(extras) + \
        "\n\nAgent modes per job: " + json.dumps(modes) + "\n"


if __name__ == "__main__":
    for m in sys.argv[1:] or ["mock", "local"]:
        print(f"### {m}\n")
        print(table(m))
