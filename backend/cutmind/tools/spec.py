"""Tier 1 skill specs: skills/tier1/<id>.yaml, validated against skills/tier1.schema.json.

The spec is the single source for a Tier 1 skill: its parameters (types, ranges, defaults), time modes, the
builder that patches the Edit Plan, synonyms and examples (the language tests), and its render test.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
TIER1_DIR = ROOT / "skills" / "tier1"
SCHEMA = ROOT / "skills" / "tier1.schema.json"


class SpecError(ValueError):
    """A Tier 1 YAML file is invalid."""


@lru_cache(maxsize=1)
def load() -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for f in sorted(TIER1_DIR.glob("*.yaml")):
        s = yaml.safe_load(f.read_text(encoding="utf-8"))
        if not isinstance(s, dict) or s.get("id") != f.stem:
            raise SpecError(f"{f.name}: the id must equal the file name")
        specs[s["id"]] = s
    return specs


def problems() -> list[str]:
    """Schema errors + cross checks (builder exists, defaults inside ranges, examples parse). Empty = all good."""
    import jsonschema

    from . import engine

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    out: list[str] = []
    for sid, s in load().items():
        for err in jsonschema.Draft202012Validator(schema).iter_errors(s):
            out.append(f"{sid}: {'/'.join(map(str, err.path))}: {err.message[:160]}")
        if s["builder"] not in engine.builder_names():
            out.append(f"{sid}: builder {s['builder']} is not registered")
        for k, p in s.get("params", {}).items():
            d = p.get("default")
            if d is not None and p["type"] in ("number", "integer"):
                if "min" in p and d < p["min"] or "max" in p and d > p["max"]:
                    out.append(f"{sid}: default of {k} ({d}) is outside [{p.get('min')}, {p.get('max')}]")
            if p["type"] == "choice" and d is not None and d not in p.get("choices", []):
                out.append(f"{sid}: default of {k} ({d}) is not one of its choices")
        syn = s.get("synonyms", {})
        n = sum(len(v) for v in syn.values())
        if n < 15:
            out.append(f"{sid}: only {n} synonyms (need 15+)")
        if s.get("same_engine_as") and s["same_engine_as"] not in load():
            out.append(f"{sid}: same_engine_as {s['same_engine_as']} is not a Tier 1 skill")
    # the same phrase may not name two skills (the parser would pick one at random)
    from .parse import _norm, _syn_tokens

    owner: dict[tuple[str, ...], str] = {}
    for sid, s in load().items():
        for group in s["synonyms"].values():
            for syn in group:
                tk = _syn_tokens(_norm(syn))
                if tk in owner and owner[tk] != sid:
                    out.append(f"synonym '{syn}' names both {owner[tk]} and {sid}")
                owner.setdefault(tk, sid)
    return out
