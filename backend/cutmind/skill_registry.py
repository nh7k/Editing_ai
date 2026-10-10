"""The skill registry (skills/registry/*.yaml, schema skills/skill.schema.json).

A skill is one editing capability with its synonyms (English, Devanagari Hindi, Hinglish, slang, typos), parameters,
time modes and the engine it maps to (an FFmpeg effect, a transition, a colour look, a text preset, or a rule phrase
the planner already understands). Agents choose and parameterize skills; they never invent edits.

    load()            -> {id: skill}              (schema-validated, refs checked against the real engines)
    problems()        -> list of what is wrong     (empty = registry is consistent; a test asserts it)
    match(text)       -> [SkillMatch]              (longest synonym first, negation-aware, Devanagari + typos)
    to_phrase(id, **params) -> the rule phrase / plan op for one skill call
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY = ROOT / "skills" / "registry"
SCHEMA = ROOT / "skills" / "skill.schema.json"

NEGATION = re.compile(r"\b(mat|nahi|nahin|nhi|na|no|don'?t|do not|without|bina|never|band)\b", re.I)
STAGE_ORDER = ["structure", "time", "geometry", "color", "look", "effect", "overlay", "text", "transition", "audio"]


@dataclass
class SkillMatch:
    id: str
    phrase: str        # the synonym that matched
    start: int
    end: int
    negated: bool = False
    params: dict[str, Any] = field(default_factory=dict)


@lru_cache(maxsize=1)
def load() -> dict[str, dict[str, Any]]:
    skills: dict[str, dict[str, Any]] = {}
    for f in sorted(REGISTRY.glob("*.yaml")):
        for s in yaml.safe_load(f.read_text(encoding="utf-8"))["skills"]:
            s["_file"] = f.name
            skills[s["id"]] = s
    return skills


def _ref_values(s: dict[str, Any]) -> list[str]:
    """The concrete engine ids a skill can resolve to ("slide{direction}" → slideleft, slideright, …)."""
    ref = str(s["impl"].get("ref", ""))
    m = re.search(r"\{(\w+)\}", ref)
    if not m:
        return [ref]
    p = s["params"].get(m.group(1), {})
    choices = p.get("choices") or [p.get("default")]
    return [ref.replace("{" + m.group(1) + "}", str(c)) for c in choices]


def problems() -> list[str]:
    """Everything inconsistent in the registry: schema errors, unknown engine refs, rule phrases the parser does
    not understand, duplicate ids, conflicts naming unknown skills, too few examples."""
    import jsonschema

    from .fx_catalog import catalog as fx_catalog
    from .intent import parse_intent
    from .moment import read_comment
    from .plan import ColorPreset
    from .text_styles import TEXT_PRESETS

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    cat = fx_catalog()
    effects = {x["id"] for k in ("motion", "video_effect") for x in cat[k]} | {"speed_ramp", "blur_background"}
    transitions = {x["id"] for x in cat["transition"]}
    looks = set(ColorPreset.__args__)  # type: ignore[attr-defined]
    anims = {x["id"] for x in cat["text_animation"]}
    out: list[str] = []
    seen: dict[str, str] = {}
    for f in sorted(REGISTRY.glob("*.yaml")):
        for s in yaml.safe_load(f.read_text(encoding="utf-8"))["skills"]:
            sid = s.get("id", "?")
            if sid in seen:
                out.append(f"{sid}: duplicate id ({seen[sid]} and {f.name})")
            seen[sid] = f.name
            out += [f"{sid}: {e.message}" for e in validator.iter_errors(s)]
    for sid, s in load().items():
        kind = s["impl"]["kind"]
        for ref in _ref_values(s):
            if kind == "effect" and ref not in effects:
                out.append(f"{sid}: effect '{ref}' does not exist")
            elif kind == "transition" and ref not in transitions:
                out.append(f"{sid}: transition '{ref}' does not exist")
            elif kind == "look" and ref not in looks:
                out.append(f"{sid}: look '{ref}' does not exist")
            elif kind == "text_style" and ref not in TEXT_PRESETS:
                out.append(f"{sid}: text preset '{ref}' does not exist")
            elif kind == "text_anim" and ref not in anims:
                out.append(f"{sid}: text animation '{ref}' does not exist")
            elif kind == "intent" and parse_intent(fill(ref, s)).is_empty():
                out.append(f"{sid}: the rule parser does not understand '{fill(ref, s)}'")
            elif kind == "moment" and not read_comment(fill(ref, s))["understood"]:
                out.append(f"{sid}: a timeline comment '{fill(ref, s)}' is not understood")
        for c in s.get("conflicts", []):
            if c not in load():
                out.append(f"{sid}: conflict with unknown skill '{c}'")
        if s["status"] == "tested" and not s.get("test"):
            out.append(f"{sid}: status tested but no test named")
    return out


def fill(template: str, s: dict[str, Any], **params: Any) -> str:
    """A ref / phrase template with parameters (defaults where not given)."""
    def one(m: re.Match[str]) -> str:
        k = m.group(1)
        v = params.get(k, s["params"].get(k, {}).get("default", ""))
        return str(v)

    return re.sub(r"\{(\w+)\}", one, template)


# ---- matching ------------------------------------------------------------------------------------------------
def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s:&'ऀ-ॿ]", " ", text.lower())).strip()


@lru_cache(maxsize=2)
def _index(later: bool = False) -> list[tuple[str, str]]:
    """(normalized synonym, skill id), longest first. `later`: the planned / blocked skills instead (never used for
    an edit; only to say "that is not available yet")."""
    from .hindi import is_hindi, romanize

    pairs: set[tuple[str, str]] = set()
    for sid, s in load().items():
        if (s["impl"]["kind"] in ("planned", "blocked")) != later:
            continue
        for group in s["synonyms"].values():
            for syn in group:
                n = _norm(syn)
                if len(n) >= 3:
                    pairs.add((n, sid))
                    if is_hindi(n):
                        pairs.add((_norm(romanize(n)), sid))
    return sorted(pairs, key=lambda p: -len(p[0]))


def match(text: str) -> list[SkillMatch]:
    """Skills named in a message, left to right. A longer synonym wins over a shorter one inside it ("zoom
    transition" is the transition, not the zoom effect); "zoom mat lagao" is a negated zoom."""
    from .hindi import is_hindi, romanize

    t = _norm(text)
    variants = [t] + ([_norm(romanize(t))] if is_hindi(t) else [])
    found: list[SkillMatch] = []
    for v in variants:
        taken = [False] * len(v)
        for syn, sid in _index():
            for m in re.finditer(r"(?<![\wऀ-ॿ])" + re.escape(syn) + r"(?![\wऀ-ॿ])", v):
                if any(taken[m.start():m.end()]):
                    continue
                for i in range(m.start(), m.end()):
                    taken[i] = True
                after = v[m.end():m.end() + 20]
                before = v[max(0, m.start() - 12):m.start()]
                neg = bool(NEGATION.search(after.split(",")[0])) or bool(re.search(r"\b(no|without|bina|don'?t)\s*$", before))
                found.append(SkillMatch(sid, syn, m.start(), m.end(), neg))
        if found:
            break
    found.sort(key=lambda x: x.start)
    out, ids = [], set()
    for f in found:  # one entry per skill (the first mention)
        if f.id not in ids:
            ids.add(f.id)
            out.append(f)
    return out


_SKIP_FIELDS = {"recognized", "inferred_fields", "limits", "remove", "avoid", "auto", "order", "kinetic_text"}


@lru_cache(maxsize=1)
def _signatures() -> dict[str, dict[str, Any]]:
    """For rule-phrase skills: the Intent fields their own phrase sets (worked out by the parser itself, so the
    registry and the parser can never drift apart)."""
    from .intent import Intent, parse_intent

    default = Intent().model_dump()
    sig: dict[str, dict[str, Any]] = {}
    for sid, s in load().items():
        if s["impl"]["kind"] != "intent":
            continue
        got = parse_intent(fill(s["impl"]["ref"], s)).model_dump()
        only = s["impl"].get("fields")
        if only:
            sig[sid] = {f: (f.split(":", 1)[1] if ":" in f else got.get(f)) for f in only}
        else:
            sig[sid] = {k: v for k, v in got.items() if k not in _SKIP_FIELDS and v != default.get(k)}
    return sig


def skills_in_intent(it: Any) -> list[str]:
    """The skills an understood request (Intent) uses — the parser's reading mapped back onto the registry."""
    d = it.model_dump() if hasattr(it, "model_dump") else dict(it)
    out: list[str] = []
    for sid, s in load().items():
        kind, refs = s["impl"]["kind"], _ref_values(s)
        if kind == "effect":
            used = set(d.get("effects") or []) | {t["effect"] for t in d.get("timed_effects") or []}
            if used & set(refs):
                out.append(sid)
        elif kind == "transition" and d.get("transition") in refs:
            out.append(sid)
        elif kind == "look" and d.get("color_preset") in refs:
            out.append(sid)
        elif kind == "text_style" and d.get("text_style") in refs:
            out.append(sid)
        elif kind == "text_anim" and d.get("text_animation") in refs:
            out.append(sid)
        elif kind == "intent":
            sig = _signatures().get(sid) or {}
            if sig and all(_has_field(d, k, v) for k, v in sig.items()):
                out.append(sid)
    return out


def _has_field(d: dict[str, Any], key: str, want: Any) -> bool:
    from .intent import Intent

    if ":" in key:  # "remove:transition"
        field_, value = key.split(":", 1)
        return value in (d.get(field_) or [])
    default = Intent().model_dump().get(key)
    got = d.get(key)
    if got == default:
        return False
    return _same(got, want)


def _same(got: Any, want: Any) -> bool:
    if isinstance(want, bool):
        return bool(got) == want
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        return got is not None  # "15 seconds" and "30 seconds" are the same skill with another parameter
    if isinstance(want, list):
        if want and all(isinstance(w, str) for w in want):  # effects: the very effect, not "any effect"
            return all(w in (got or []) for w in want)
        return bool(got)
    if isinstance(want, str) and want.startswith("#"):
        return bool(got)  # any colour
    return got == want or (want is not None and got is not None and not isinstance(want, str))


def named_later(text: str) -> list[str]:
    """Planned / blocked skills a message asks for ("4k upscale", "remove the background"): reported as not
    available yet, never faked with something else."""
    from .hindi import is_hindi, romanize

    def bare(x: str) -> str:  # "remove the background" = "remove background"
        return re.sub(r"\b(the|a|an|my|this|that|meri|mera)\s+", "", x)

    t = _norm(text)
    vs = [bare(v) for v in [t] + ([_norm(romanize(t))] if is_hindi(t) else [])]
    out: list[str] = []
    for syn, sid in _index(later=True):
        syn = bare(syn)
        if sid not in out and any(re.search(r"(?<![\wऀ-ॿ])" + re.escape(syn) + r"(?![\wऀ-ॿ])", v) for v in vs):
            out.append(sid)
    return out


def covers(clause: str) -> bool:
    """True when a registry synonym of a skill we can do names this clause ("gaane ki awaaz kam" → music_level).
    Synonyms are hand-written editor phrases, more specific than the parser's guess, so such a clause does not
    need the planner LLM even when many of its words are not the editor's own."""
    reg = load()
    return any(reg[m.id]["status"] not in ("planned", "blocked") for m in match(clause))


def understand(text: str) -> dict[str, Any]:
    """The full skill reading of a message: synonym matches + the rule parser's reading (after the desi
    normalizer). Returns {"skills": [...], "negated": [...], "via": {id: "synonym"|"parser"}}."""
    from .intent import parse_intent
    from .prenormalize import normalize

    via: dict[str, str] = {}
    negated: list[str] = []
    for m in match(text):
        if m.negated:
            negated.append(m.id)
        else:
            via[m.id] = "synonym"
    it = parse_intent(normalize(text))
    for sid in skills_in_intent(it):
        if sid not in negated:
            via.setdefault(sid, "parser")
    for a in it.avoid:  # "zoom mat lagao": the parser's don'ts, as skills
        for sid, s in load().items():
            if s["impl"]["kind"] == "effect" and a in _ref_values(s) and sid not in negated:
                negated.append(sid)
                via.pop(sid, None)
    return {"skills": list(via), "negated": negated, "via": via}


def stage_of(skill_id: str) -> int:
    s = load().get(skill_id)
    return STAGE_ORDER.index(s["stage"]) if s else len(STAGE_ORDER)
