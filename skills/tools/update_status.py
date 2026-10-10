"""Turns render-test passes into `status: tested` in the registry (and a failing tested skill back to untested).

    python skills/tools/update_status.py        # reads skills/test_results.json (written by test_skill_renders.py)

Edits the YAML text line by line so comments and layout stay as they are. Only skills with status tested/untested
are touched (planned / blocked never change here). The generated catalog files are edited too; the generator keeps
these statuses (it reads the same results file).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "skills" / "test_results.json"
TEST = "tests/integration/test_skill_renders.py"


def main() -> None:
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    changed = {"tested": [], "untested": []}
    for f in sorted((ROOT / "skills" / "registry").glob("*.yaml")):
        lines = f.read_text(encoding="utf-8").splitlines()
        out, sid = [], None
        for line in lines:
            m = re.match(r"^- id: (\S+)", line)
            if m:
                sid = m.group(1)
            if sid and re.match(r"^  test: ", line) and sid in results:
                continue  # rewritten after the status line
            st = re.match(r"^  status: (tested|untested)\s*$", line)
            if st and sid in results:
                new = "tested" if results[sid]["ok"] else "untested"
                if new != st.group(1):
                    changed[new].append(sid)
                out.append(f"  status: {new}")
                if new == "tested":
                    out.append(f"  test: {TEST}")
                continue
            out.append(line)
        text = "\n".join(out) + "\n"
        if text != f.read_text(encoding="utf-8"):
            f.write_text(text, encoding="utf-8")
    print(f"now tested: {len(changed['tested'])} {changed['tested']}")
    print(f"back to untested: {len(changed['untested'])} {changed['untested']}")


if __name__ == "__main__":
    main()
