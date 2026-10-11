"""A guard found the hard way twice: a "\b" written through a shell heredoc became a real backspace character
inside regexes (api.py, fx_catalog.py, resolve.py), silently breaking them. No source file may contain one."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BAD = {chr(c) for c in range(0, 32)} - {"\n", "\r", "\t"}


def test_no_control_characters_in_source_files():
    found = []
    for base in ("backend/cutmind", "eval", "tests", "skills", "mobile/src", "mobile/__tests__"):
        for p in (ROOT / base).rglob("*"):
            if p.suffix in {".py", ".ts", ".tsx", ".yaml", ".json"} and "__pycache__" not in p.parts and p.is_file():
                text = p.read_text(encoding="utf-8", errors="ignore")
                if BAD & set(text):
                    found.append(str(p.relative_to(ROOT)))
    assert not found, found
