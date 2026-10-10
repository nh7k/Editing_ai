"""One-time generator: registry entries for every engine effect / transition / LUT look / text animation that has no
hand-written skill yet (skills/registry/catalog_*.yaml). Synonyms come from the catalog's own names and keyword
patterns; hand-written skills always win (ids already in the registry are skipped). Re-run after adding effects:

    backend/.venv/Scripts/python.exe skills/tools/generate_catalog_skills.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from cutmind import fx_catalog  # noqa: E402

TIER2_EFFECTS = {"swing", "pulse", "rotate_slow", "camera_move", "spotlight", "person_zoom", "follow", "sharpen", "blur",
                 "glitch", "rgb_split", "vhs", "old_film", "flash", "strobe", "mirror", "pixelate", "ghost_trail",
                 "dreamy", "letterbox", "film_bw", "duotone_teal_gold", "impact", "neon_edges", "negative", "posterize"}
TIER2_LOOKS = {"golden_hour", "moody_blue", "noir", "faded_film"}
STAGE = {"motion": "geometry", "video_effect": "effect"}
MEDIA3 = {"motion": "MatrixTransformation per frame — NOT TESTED", "video_effect": "custom GlEffect shader port — NOT TESTED",
          "transition": "custom GlEffect on the overlap of two sequences — NOT TESTED",
          "color": "SingleColorLut from our generated .cube — NOT TESTED",
          "text_animation": "TextOverlay with per-frame alpha/scale — NOT TESTED"}


def words(pattern: str) -> str | None:
    """A readable phrase from a keyword regex ("zoom.?out" → "zoom out"); None when it is not plain words."""
    s = re.sub(r"\\b|\(\?[!=][^)]*\)|\^|\$", "", pattern)
    s = s.replace(".?", " ").replace("\\s+", " ").replace("\\s*", " ").replace("\\s", " ").replace("s?", "s")
    s = re.sub(r"\(([^|()]+)\|[^)]*\)", r"\1", s)  # (a|b) → a
    s = re.sub(r"[?*+\\]", "", s).strip()
    return s if re.fullmatch(r"[a-z0-9 &'-]{3,40}", s) else None


def entry(fx_id: str, name: str, cat: str, desc: str, keywords: tuple[str, ...]) -> dict:
    syn_en = list(dict.fromkeys([name.lower(), fx_id.replace("_", " ")] + [w for k in keywords if (w := words(k))]))[:6]
    kind = {"motion": "effect", "video_effect": "effect", "transition": "transition", "color": "look",
            "text_animation": "text_anim"}[cat]
    category = {"motion": "motion", "video_effect": "color" if fx_id in ("mono", "film_bw", "duotone_teal_gold",
                                                                          "duotone_blue_pink", "posterize", "negative",
                                                                          "invert_mono", "silhouette", "thermal",
                                                                          "night_vision") else "motion" if False else "color",
                "transition": "transition", "color": "color", "text_animation": "text"}[cat]
    if cat == "video_effect" and fx_id in ("glitch", "rgb_split", "vhs", "scanlines", "flash", "strobe", "mirror",
                                           "kaleidoscope", "pixelate", "ghost_trail", "echo", "fisheye", "dreamy",
                                           "neon_edges", "sketch", "letterbox", "impact", "blur", "sharpen"):
        category = "motion" if fx_id in ("mirror", "kaleidoscope", "fisheye", "ghost_trail", "echo") else "color"
    tier = 2 if fx_id in TIER2_EFFECTS | TIER2_LOOKS else 3
    nm = name.lower()
    return {
        "id": f"{'tr_' if cat == 'transition' else 'anim_' if cat == 'text_animation' else ''}{fx_id}",
        "tier": tier, "category": category, "name": name, "description": desc,
        "synonyms": {"en": syn_en, "hinglish": [f"{nm} lagao", f"{nm} effect daal do" if kind == "effect" else f"{nm} wala"]},
        "params": {"strength": {"type": "number", "default": 1.0, "min": 0.3, "max": 3.0}} if kind == "effect" else
                  {"duration": {"type": "number", "default": 0.5, "min": 0.1, "max": 2.0}} if kind == "transition" else {},
        "time_modes": ["whole", "segment", "between_times", "at_moment"] if kind == "effect" else ["whole", "segment"]
                      if kind == "transition" else ["whole"],
        "impl": {"kind": kind, "ref": fx_id, **({"strength_param": "strength"} if kind == "effect" else {})},
        "stage": {"effect": STAGE.get(cat, "effect"), "transition": "transition", "look": "look",
                  "text_anim": "text"}[kind],
        "conflicts": [], "cost": "medium" if cat == "video_effect" else "cheap",
        "media3": MEDIA3[cat], "licence": "own code (FFmpeg filters / generated LUT)", "preview": "same at 360p",
        "examples": [f"add {nm}", f"{nm} lagao", f"{nm} effect on the intro", f"use {fx_id.replace('_', ' ')}",
                     f"thoda {nm} daal do"],
        "status": "untested",
    }


def _hand_written() -> dict[str, dict]:
    """Skills of the hand-written registry files (NOT our own catalog_*.yaml output: counting those made a re-run
    skip every generated skill and write empty files)."""
    out: dict[str, dict] = {}
    for f in (ROOT / "skills" / "registry").glob("*.yaml"):
        if not f.stem.startswith("catalog_"):
            out.update({s["id"]: s for s in yaml.safe_load(f.read_text(encoding="utf-8"))["skills"]})
    return out


def main() -> None:
    import json

    hand = _hand_written()
    have = set(hand)
    res = ROOT / "skills" / "test_results.json"
    results = json.loads(res.read_text(encoding="utf-8")) if res.exists() else {}
    cat = fx_catalog.catalog()
    reg = {f.id: f for f in fx_catalog._REGISTRY + fx_catalog._REGISTRY_T}  # noqa: SLF001
    out: dict[str, list[dict]] = {"catalog_effects": [], "catalog_transitions": [], "catalog_looks": [],
                                  "catalog_text_anims": []}
    for group, file in (("motion", "catalog_effects"), ("video_effect", "catalog_effects"),
                        ("transition", "catalog_transitions"), ("color", "catalog_looks"),
                        ("text_animation", "catalog_text_anims")):
        for x in cat[group]:
            f = reg.get(x["id"])
            e = entry(x["id"], x["name"], group, x["description"], f.keywords if f else ())
            hand_written = {s["impl"].get("ref") for s in hand.values()}
            if e["id"] in have or (group != "transition" and x["id"] in hand_written and group != "text_animation"):
                continue
            if group == "transition" and x["id"] in {s["impl"].get("ref") for s in hand.values()
                                                     if s["impl"]["kind"] == "transition"}:
                continue
            if results.get(e["id"], {}).get("ok"):  # keep what the render tests proved
                e["status"], e["test"] = "tested", "tests/integration/test_skill_renders.py"
            out[file].append(e)
    for file, skills in out.items():
        path = ROOT / "skills" / "registry" / f"{file}.yaml"
        path.write_text("# generated by skills/tools/generate_catalog_skills.py — hand-written skills win\n"
                        + yaml.safe_dump({"skills": skills}, allow_unicode=True, sort_keys=False, width=120),
                        encoding="utf-8")
        print(file, len(skills))


if __name__ == "__main__":
    main()
