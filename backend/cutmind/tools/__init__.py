"""Tier 1 tool engine: every Tier 1 skill is a deterministic patch on the Edit Plan (no AI step).

    spec.py        skills/tier1/<id>.yaml (schema-validated) — parameters, time modes, synonyms, tests
    engine.py      run(plan, calls, ctx): validate params → time windows → builder → invariants → explain-back
    timeline.py    output-time operations on a plan (split, isolate a window, remove / keep a range)
    timewin.py     time modes → output windows (whole, segment, between_times, intermittent, at_beats, …)
    invariants.py  what every patch must keep true (duration, audio, sources untouched)
    parse.py       prompt → tool calls with parameters (synonyms + extractors), deterministic
    generated.py   media the tools make (title cards, whoosh) — never the user's originals
    b_*.py         the builders, one module per category
"""
