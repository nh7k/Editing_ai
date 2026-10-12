"""Editorial brain: rough words + the footage → a professional, explainable edit specification.

    prompt ──► language normalisation (Hinglish / creator slang → concepts)
           ──► content classification (prompt hints + footage analysis → genres)
           ──► platform (Reels / TikTok / Shorts / YouTube / LinkedIn)
           ──► skill retrieval (genre packs + concepts + direct triggers; only the relevant skills)
           ──► ProfessionalEditSpec: EXPLICIT (the user said it) / INFERRED (with reason + skill) / UNKNOWN
           ──► applied to the Intent the agents execute — inferred values never override explicit ones.

Knowledge lives in backend/video_editing_knowledge/*.yaml (skills, genres, platforms, language, taste) so editors
can extend it without code. Deterministic and instant: no model call, runs on any CPU.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .intent import Intent

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "video_editing_knowledge"

# Intent fields a skill may set (everything else in `apply` is ignored)
APPLYABLE = {"fast_cuts", "beat_sync", "cut_length", "remove_silence", "remove_fillers", "remove_idle", "music",
             "music_mood", "color_preset", "transition", "emphasis_punch", "jumpcut_cover", "flash_accents",
             "ending_peak", "hook_first", "captions", "text_animation", "text_style", "target_lufs", "slow_motion",
             "voice_cleanup", "caption_words", "color_pass", "kinetic_text", "kinetic_words",
             "speed_moves", "impact_hits", "text_behind"}


@lru_cache(maxsize=1)
def knowledge() -> dict[str, Any]:
    def load(name: str) -> Any:
        return yaml.safe_load((KNOWLEDGE_DIR / name).read_text(encoding="utf-8"))

    return {"skills": {s["id"]: s for s in load("skills.yaml")["skills"]},
            "genres": {g["id"]: g for g in load("genres.yaml")["genres"]},
            "platforms": {p["id"]: p for p in load("platforms.yaml")["platforms"]},
            "language": load("language.yaml"), "taste": load("taste.yaml")}


@dataclass
class Decision:
    field: str
    value: Any
    reason: str
    skill: str = ""
    source: str = "inferred"   # explicit | inferred | taste | footage


@dataclass
class EditSpec:
    concepts: list[str] = field(default_factory=list)
    genres: list[dict[str, str]] = field(default_factory=list)     # {id, name, why}
    platform: dict[str, Any] | None = None
    skills: list[dict[str, str]] = field(default_factory=list)     # {id, name, why}
    explicit: list[str] = field(default_factory=list)
    inferred: list[Decision] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    limits: dict[str, int] = field(default_factory=dict)
    structure: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["inferred"] = [asdict(x) for x in self.inferred]
        return d


# ---- 1. language ---------------------------------------------------------------------------------------------
# "colour ko cinematic teal orange karo": cinematic says how the COLOUR looks, not how the video is paced — it made a
# slow 4 s-shot piece of 9 s out of 16 s of football (the cinematic genre)
COLOUR_ADJ = re.compile(r"\b(?:colou?r|rang|grade|grading|lut|tone)(?:\s+(?:ko|me|mein|to|in))?\s+(?:cinematic|filmy)\b|"
                        r"\b(?:cinematic|filmy)\s+(?:colou?r|rang|grade|grading|look|lut|tone|teal|orange)\b")


def _colour_said_out(prompt: str) -> str:
    return COLOUR_ADJ.sub(" ", prompt.lower())


def concepts_in(prompt: str) -> list[str]:
    p = _colour_said_out(prompt)
    out: list[str] = []
    for entry in knowledge()["language"]["phrases"]:
        if any(re.search(x, p) for x in entry["patterns"]):
            out += [c for c in entry["concepts"] if c not in out]
    return out


def is_adjustment(prompt: str) -> bool:
    """"thoda dark", "captions hata de": change the current edit instead of starting a new one."""
    p = prompt.lower().strip()
    return len(p.split()) <= 8 and any(re.search(x, p) for x in knowledge()["language"]["adjustments"])


# ---- 2. content type -----------------------------------------------------------------------------------------
def footage_profile(analysis: Any) -> dict[str, Any] | None:
    if analysis is None or not analysis.clips:
        return None
    clips = list(analysis.clips.values())
    dur = sum(c.duration for c in clips) or 1.0
    wps = sum(len(c.words) for c in clips) / dur
    talking = sum(1 for c in clips if len(c.words) / max(c.duration, 0.1) > 0.8)
    motion = sum(c.motion * c.duration for c in clips) / dur
    return {"speech": "high" if wps > 0.8 else "low" if wps > 0.05 else "none", "words_per_second": round(wps, 2),
            "motion": "high" if motion > 12 else "low" if motion < 4 else "mid", "motion_value": round(motion, 1),
            "clips": len(clips), "seconds": round(dur, 1), "talking_clips": talking}


def _footage_fits(rule: dict[str, Any], prof: dict[str, Any]) -> bool:
    if not rule:
        return False
    if "speech" in rule:
        want = rule["speech"]
        if want == "none" and prof["speech"] != "none":
            return False
        if want == "low" and prof["speech"] == "high":
            return False
        if want == "high" and prof["speech"] != "high":
            return False
    if "motion" in rule:
        order = {"low": 0, "mid": 1, "high": 2}
        if rule["motion"] == "high" and prof["motion"] != "high":
            return False
        if rule["motion"] == "low" and prof["motion"] != "low":
            return False
        if rule["motion"] == "mid" and order[prof["motion"]] == 0:
            return False
    return prof["clips"] >= rule.get("min_clips", 1)


def classify(prompt: str, analysis: Any = None) -> list[dict[str, str]]:
    p = _colour_said_out(prompt)
    kn = knowledge()["genres"]
    found = [{"id": g["id"], "name": g["name"], "why": "you said it"} for g in kn.values()
             if any(re.search(x, p) for x in g.get("prompt", []))]
    prof = footage_profile(analysis)
    if prof and not [g for g in found if g["id"] not in ("reel", "youtube")]:
        # nothing said about the content: guess ONE type from the footage, and say why
        if prof["speech"] == "high" or prof["talking_clips"]:
            # someone talks: one talking clip on its own = talking head; mixed with other footage = vlog
            gid = "talking_head" if prof["talking_clips"] == prof["clips"] and prof["motion"] != "high" else "vlog"
        elif prof["motion"] == "high":
            gid = "montage"
        elif prof["clips"] >= 2:
            gid = "travel"
        else:
            gid = ""
        if gid:
            found.append({"id": gid, "name": kn[gid]["name"],
                          "why": f"footage: speech {prof['speech']} ({prof['words_per_second']} words/s), "
                                 f"motion {prof['motion']} ({prof['motion_value']}), {prof['clips']} clip(s)"})
    return found


def platform_for(prompt: str) -> dict[str, Any] | None:
    p = prompt.lower()
    for pl in knowledge()["platforms"].values():
        if any(re.search(x, p) for x in pl["prompt"]):
            return pl
    return None


# ---- 3. skills -----------------------------------------------------------------------------------------------
def retrieve(prompt: str, concepts: list[str], genres: list[dict[str, str]]) -> list[tuple[dict[str, Any], str, int]]:
    """(skill, why, score) — highest score first. Only relevant skills: no skill without a reason to be here."""
    p = prompt.lower()
    sk = knowledge()["skills"]
    picked: dict[str, tuple[str, int]] = {}

    def add(sid: str, why: str, score: int) -> None:
        if sid in sk and (sid not in picked or picked[sid][1] < score):
            picked[sid] = (why, score)

    for s in sk.values():
        if any(re.search(x, p) for x in s.get("triggers", [])):
            add(s["id"], "your words", 3)
        hit = [c for c in s.get("concepts", []) if c in concepts]
        if hit:
            add(s["id"], f"you asked for {', '.join(hit)}", 2)
    for g in genres:
        for sid in knowledge()["genres"][g["id"]]["skills"]:
            add(sid, f"{g['name']} editing", 1)
    return sorted(((sk[k], why, sc) for k, (why, sc) in picked.items()), key=lambda t: -t[2])


# ---- 4. compile ------------------------------------------------------------------------------------------------
def needs_footage_words(prompt: str, it: Intent) -> bool:
    """Must speech-to-text run so the brain can tell talking footage from scenery? Only when the words don't say."""
    return wants_editorial(prompt, it) and not [g for g in classify(prompt) if g["id"] not in ("reel", "youtube")]


def wants_editorial(prompt: str, it: Intent) -> bool:
    """Only vague / creative requests get the editorial brain. "trim to 15 seconds" is done exactly as said."""
    return bool(it.auto or concepts_in(prompt) or classify(prompt) or platform_for(prompt))


def compile_spec(prompt: str, it: Intent, analysis: Any = None) -> EditSpec:
    concepts = concepts_in(prompt)
    # the footage only decides the content type for vague / creative requests ("mast bana", auto edit) — a concrete
    # request like "9:16 reel with warm color" must not grow silence removal because the clip happens to talk
    genres = classify(prompt, analysis if (concepts or it.auto) else None)
    plat = platform_for(prompt)
    spec = EditSpec(concepts=concepts, genres=genres,
                    platform={k: plat[k] for k in ("id", "name", "aspect", "safe_bottom", "loudness", "hook_seconds")}
                    if plat else None)
    defaults = Intent().model_dump()
    explicit = {k for k, v in it.model_dump().items() if k not in ("recognized",) and v != defaults[k]}
    spec.explicit = sorted(explicit)
    taken: set[str] = set(explicit)
    limits: dict[str, int] = {}
    prof = footage_profile(analysis)
    talky = bool(prof and prof["speech"] == "high")

    def decide(fld: str, value: Any, reason: str, skill: str, source: str = "inferred") -> None:
        if fld in taken or fld not in APPLYABLE:
            return
        norm = None if (fld == "transition" and value == "none") else value
        if norm == defaults.get(fld):  # already so: not a decision, just noise in the spec
            taken.add(fld)
            return
        taken.add(fld)
        spec.inferred.append(Decision(fld, value, reason, skill, source))

    if plat:
        if "aspect_ratio" not in explicit:
            spec.inferred.append(Decision("aspect_ratio", plat["aspect"], f"{plat['name']} format", "platform", "inferred"))
            taken.add("aspect_ratio")
        decide("target_lufs", plat["loudness"], f"{plat['name']} normalises loudness to {plat['loudness']} LUFS", "platform")
    for skill, why, _score in retrieve(prompt, concepts, genres):
        # skills that would chop speech are wrong for footage where people talk, whatever the genre says
        if talky and skill["id"] in ("fast_paced_reel", "beat_cut", "fan_edit_style", "beat_punch", "colour_pass",
                                        "velocity_moves"):
            spec.unknown.append(f"skipped '{skill['name']}': people talk in this footage — cutting to the beat would chop sentences")
            continue
        if skill["id"] == "jump_cut_talking" and prof and prof["speech"] == "none":
            continue
        spec.skills.append({"id": skill["id"], "name": skill["name"], "why": why})
        for k, v in (skill.get("limits") or {}).items():
            limits[k] = min(limits.get(k, v), v)
        for k, v in (skill.get("apply") or {}).items():
            if k == "effects_add":
                continue
            decide(k, v, f"{skill['name']}: {skill.get('why', '')}".strip(), skill["id"])
        spec.avoid += [a for a in skill.get("avoid", []) if a not in spec.avoid]
    # restraint: transitions / effects the user didn't ask for stay within the limits
    effects_budget = limits.get("max_effects", knowledge()["taste"]["effects"]["max_per_video"])
    added = 0
    for skill_d in spec.skills:
        for e in (knowledge()["skills"][skill_d["id"]].get("apply") or {}).get("effects_add", []):
            if "effects" in explicit or added >= effects_budget:
                break
            spec.inferred.append(Decision("effects_add", e, knowledge()["skills"][skill_d["id"]]["why"], skill_d["id"]))
            added += 1
    if (it.kinetic_text or any(d.field == "kinetic_text" for d in spec.inferred)) and not it.kinetic_words:
        # also when words were asked for directly ("lyrics on screen"): the subject's name still hits the drop
        words = kinetic_words_from(prompt, it)
        if words:
            spec.inferred.append(Decision("kinetic_words", words, "the subject of the edit, one word per beat",
                                          "kinetic_words"))
        elif it.kinetic_text:  # text was asked for and no name was said
            spec.inferred.append(Decision("kinetic_words", ["LET'S", "GO"], "text was asked for, no name was said",
                                          "kinetic_words"))
        else:  # only inferred, and no name to show: no words at all beats random words from the prompt
            spec.inferred = [d for d in spec.inferred if d.field != "kinetic_text"]
            spec.unknown.append("kinetic text: no name to show (say it in quotes: 'RONALDO')")
    spec.limits = limits
    spec.structure = " | ".join(knowledge()["genres"][g["id"]]["structure"] for g in genres[:2])
    if not genres:
        spec.unknown.append("content type: not said and not clear from the footage")
    if not plat:
        spec.unknown.append("platform: not said (aspect kept as the footage / your choice)")
    return spec


_STOP = {"bhai", "isko", "iska", "a", "an", "the", "me", "my", "make", "edit", "with", "and", "nice", "cool", "animations", "animation", "of", "for",
         "that", "is", "very", "super", "mast", "sa", "ek", "ka", "ki", "bana", "do", "de", "please", "video", "reel"}


# words that say what KIND of edit, never a name to put on screen ("make it look like a pro football edit" showed
# IT / LOOK / LIKE / PRO / FOOTBALL on a Ronaldo edit)
_KIND = {"it", "look", "looks", "like", "feel", "feels", "seem", "pro", "professional", "football", "soccer", "cricket",
         "sports", "sport", "travel", "wedding", "gym", "car", "bike", "anime", "fan", "cinematic", "velocity", "beat",
         "beats", "sigma", "hype", "epic", "viral", "flash", "flashes", "edits", "style", "type", "wala", "wali", "jaisa",
         "jaisi", "on", "in", "to", "proper", "good", "best", "high", "quality", "level", "montage", "highlight",
         "highlights", "music", "song", "transition", "transitions", "effect", "effects", "phonk", "slowmo", "shake"}


def kinetic_words_from(prompt: str, it: Intent) -> list[str]:
    """Words for kinetic text: what is quoted, else the subject of "make a <subject> edit", else the title."""
    m = re.search(r"[\"“']([^\"”']{2,40})[\"”']", prompt)
    if m:
        src = m.group(1)
    else:
        m = re.search(r"(?:make|bana\w*)\s+(?:a|an|me a|ek)?\s*(.{2,40}?)\s+edit\b", prompt.lower())
        if not m:  # Hinglish: "virat kohli ka edit bana do"
            m = re.search(r"(?:bhai\s+|isko\s+|ek\s+)?([a-z][\w .'-]{1,40}?)\s+(?:ka|ki|ke)\s+edit\b", prompt.lower())
        src = m.group(1) if m else (it.title or "")
    words = [w.upper() for w in re.findall(r"[\w']+", src) if w.lower() not in _STOP | _KIND]
    return words[:6]


# "X mat karo" → the inferred fields that would bring X back
AVOID_FIELDS = {"bw": {"color_pass"}, "text": {"kinetic_text", "kinetic_words", "text_behind"},
                "zoom": {"emphasis_punch", "impact_hits"}, "impact": {"impact_hits"}, "flash": {"flash_accents"},
                "slow_motion": {"slow_motion", "speed_moves"}, "punch": {"emphasis_punch"}}


def apply_spec(it: Intent, spec: EditSpec) -> Intent:
    """The Intent the agents execute: explicit fields untouched, inferred fields filled in."""
    upd: dict[str, Any] = {}
    effects = list(it.effects)
    avoid = set(it.avoid)
    blocked = {f for a, fs in AVOID_FIELDS.items() if a in avoid for f in fs} | ({"text_behind"} if it.text_front else set())
    spec.inferred = [d for d in spec.inferred if d.field not in blocked
                     and not (d.field == "effects_add" and d.value in avoid)
                     and not (d.field == "color_preset" and d.value == "bw" and "bw" in avoid)]
    for d in spec.inferred:
        if d.field == "effects_add":
            if d.value not in effects:
                effects.append(d.value)
            continue
        if d.field == "transition":
            upd["transition"] = None if d.value == "none" else d.value
            continue
        upd[d.field] = d.value
    if "emphasis_punch" in spec.concepts and "zoom" in effects and "emphasis_punch" in {d.field for d in spec.inferred}:
        effects.remove("zoom")  # "jab important baat bole tab zoom" = punch on key words, not a zoom on everything
    if effects != list(it.effects):
        upd["effects"] = effects
    if "hook_first" in upd and upd["hook_first"] and it.order == "original":
        upd["order"] = "smart"
    upd["inferred_fields"] = sorted({d.field for d in spec.inferred})
    upd["limits"] = dict(spec.limits)
    upd["genres"] = [g["id"] for g in spec.genres]
    upd["platform"] = spec.platform["id"] if spec.platform else it.platform
    upd["recognized"] = [*it.recognized, *(f"{d.field}={d.value} ({d.skill})" for d in spec.inferred)]
    data = {**it.model_dump(), **upd}
    return Intent.model_validate(data)
