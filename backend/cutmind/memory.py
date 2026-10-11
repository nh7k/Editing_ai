"""Long-term memory for the agent team.

Every finished edit is remembered (prompt → what was understood → what was delivered), plus which version the
user picked and their 👍/👎. From that the Director derives preferences across all projects (favourite look,
usual aspect ratio, caption habit, looks the user disliked) and can repeat the previous edit on request
("same as before", "pichli baar jaisa"). Stored in the same SQLite database as everything else.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from .db import Database, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS edit_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, job_id TEXT NOT NULL UNIQUE,
    prompt TEXT NOT NULL, intent TEXT NOT NULL, delivered TEXT NOT NULL, chosen_style TEXT, rating TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_project ON edit_memory(project_id, id);
"""

REPEAT_PATTERNS = (r"same as (before|last time|last|previous)", r"like (last time|before|the last one|previous)",
                   r"\bagain\b", r"repeat (the )?(last|previous)", r"pichh?l[aie] (baar|wala|wali|vala|edit|video)",
                   r"pehle (jaisa|jaise|wala)", r"\bwahi\b", r"\bwaisa hi\b", r"\bsame edit\b", r"\bsame style\b",
                   r"\bdobara\b(?!.{0,20}\b(naya|new|alag)\b)")
# a message that starts a NEW edit (instead of changing the current one)
# Only an explicit "start again" makes a follow-up a NEW edit (scope GLOBAL_REBUILD). Everything else on a project
# that has an edit is an INCREMENTAL patch of it: "make it a 9:16 reel" after "warm colour + music" used to start
# over and drop both (stability probe, 2026-10-08).
FRESH_PATTERNS = (r"\b(naya|nayi|new|fresh|alag|dusra|doosra)\b.{0,15}\b(edit|video|bana|banao|style|version)",
                  r"\bshuru se\b", r"\bfrom scratch\b", r"\bstart (over|again|fresh)\b", r"\bsab (hata|reset)\w*",
                  r"\breset\b", r"\bphir se (shuru|bana)\w*",
                  # a whole-edit brief ("pro editor jaisa poora edit karo") starts from the footage, not from the
                  # remembered edit: merged, its old effects (fisheye, scanlines…) came back unasked
                  r"\b(poora|pura|puri|poori|full|whole|complete)\b.{0,12}\b(edit|video)\b.{0,12}\b(karo|kar do|bana\w*|edit)",
                  r"\bpro (editor|edit)\w*")
# words that mark a message as a change to the current edit ("bhi", "ab", "hata do", "thoda", "mat")
CHANGE_WORDS = r"\b(bhi|ab|aur|bas|thoda|thodi|zara|hata\w*|nikal\w*|mat|nahi|nhi|instead|also|now|change|badal\w*|kar do|karo)\b"


def is_follow_up(prompt: str, it: Any) -> bool:
    """Is this message a change to the current edit? A chat with an editor goes on: "ab black and white kar do",
    "text bhi daal do", "warm color karo" change what is there; a full new brief ("15 sec ka insta reel bana do")
    or "naya edit" starts again."""
    from .editorial import is_adjustment

    p = prompt.lower().strip()
    if any(re.search(x, p) for x in FRESH_PATTERNS):
        return False
    if is_adjustment(prompt) or it.restore_audio or it.pace_change:
        return True  # a complaint / tweak about the edit that is there ("audio nahi aa raha", "thoda slow")
    if it.auto:
        return False  # "accha sa bana do", "full josh wala edit": a whole new edit, the agents decide again
    if it.genres or it.platform:
        return False  # a new kind of video
    asked = [r for r in it.recognized if not r.startswith("auto edit")]
    if len(asked) >= 4 and not re.search(CHANGE_WORDS, p):
        return False  # a whole brief ("15 sec, 9:16, warm, captions, music" with no "ab / bhi / thoda")
    # otherwise a message on a project that has an edit CHANGES that edit (non-destructive by default). A long
    # message used to start a new edit and threw away the song and every earlier change (seen in the app with
    # "2 sec me hi ruk gayi video kyu, … ek ronaldo text ko hata do", 24 words)
    return bool(asked)


# what a "don't" in this message switches off in the remembered edit
_AVOID_RESET = {"bw": {"color_pass": False}, "text": {"kinetic_text": False, "title": None, "kinetic_words": []},
                "kinetic": {"kinetic_text": False, "kinetic_words": []},
                "slow_motion": {"slow_motion": False, "slow_end": False}}


def merge_with_last(it: Any, last: dict[str, Any], defaults: dict[str, Any], repeat: bool) -> Any:
    """The remembered edit with this message's changes on top. Things the message says explicitly win; "hata do" /
    "mat karo" switch remembered things off; "thoda slow" twice is slower than once."""
    data = it.model_dump()
    asked = {k for k, v in data.items() if k in defaults and v != defaults[k]}
    if data.get("auto") and not [r for r in it.recognized if not r.startswith("auto edit")] or repeat:
        asked.discard("auto")  # "bana do" alone reads as "auto edit": the remembered edit decides instead
        data["auto"] = defaults["auto"]
    for k, v in last.items():
        # "3 versions" is a one-time ask: carried over, every later chat message rendered 3 looks again
        if k in defaults and k not in ("recognized", "remove", "avoid", "variations") and k not in asked:
            data[k] = v
    # timeline comments add up: every earlier comment's text / sticker / cut stays, this one's comes on top
    data["from_comment"] = it.from_comment
    keys = ["timed_texts", "moment_stickers", "exclude_ranges", "text_restyles"] + (["timed_effects"] if it.from_comment else [])
    new_items = it.model_dump()
    for k in keys:
        both = [*(last.get(k) or []), *new_items.get(k, [])]
        data[k] = [x for i, x in enumerate(both) if x not in both[:i]]
    if "word_stickers" in it.remove:
        data["moment_stickers"] = []
    # one-time actions of an earlier message are not repeated by every later message ("audio wapas lao" once)
    data["restore_audio"] = it.restore_audio
    data["restore_color"] = it.restore_color
    if it.restore_color:  # "color wapas lao": the remembered B&W / grade goes
        data.update(color_preset=None, color_pass=False)
        data["effects"] = [e for e in data.get("effects") or [] if e not in ("mono", "film_bw", "invert_mono", "silhouette")]
        data["avoid"] = [a for a in data.get("avoid") or [] if a != "bw"]
    if it.no_music:  # "gaana hata do": the remembered song goes too
        data.update(music=False, use_my_song=False, music_volume=None, music_mood=None)
    if it.length_change and last.get("target_duration"):  # "thoda chhota karo": shorter than what is there now
        data["target_duration"] = round(max(3.0, min(600.0, float(last["target_duration"]) * it.length_change)), 1)
        data["length_change"] = None
    if it.text_scale and last.get("text_scale"):
        data["text_scale"] = max(0.3, min(3.0, it.text_scale * float(last["text_scale"])))
    if it.pace_change and last.get("pace_change"):
        data["pace_change"] = max(0.25, min(4.0, it.pace_change * float(last["pace_change"])))
    # don'ts: this message's, plus the remembered ones it does not overrule
    keep = []
    for a in last.get("avoid") or []:
        if (a == "bw" and (data.get("color_preset") == "bw" and "color_preset" in asked or "color_pass" in asked)) or (
                a == "text" and ("title" in asked or "kinetic_text" in asked)) or (
                a == "slow_motion" and ("slow_motion" in asked or "slow_end" in asked)) or a in it.effects:
            continue
        keep.append(a)
    avoid = list(dict.fromkeys([*it.avoid, *keep]))
    data["avoid"] = avoid
    if "bw" in it.avoid and data.get("color_preset") in ("bw", "noir") and "color_preset" not in asked:
        data["color_preset"] = None
    for a in it.avoid:
        for k, v in _AVOID_RESET.get(a, {}).items():
            if k not in asked and k in data:
                data[k] = v
    data["effects"] = [e for e in data.get("effects") or [] if e not in it.avoid]
    for f in it.remove:  # "captions hata de": the remembered edit without them
        if f in defaults and f not in asked:
            data[f] = defaults[f]
    if it.restore_audio:  # "audio wapas lao": whatever muted / lowered it before is undone
        data["mute"], data["voice_boost"] = False, data.get("voice_boost", False)
        if data.get("music_volume") is not None and data["music_volume"] > 0.3:
            data["music_volume"] = 0.3
    if data.get("color_preset") in ("bw", "noir"):
        data["color_pass"] = False  # the whole video is black & white: no separate B&W shots
    data["recognized"] = list(it.recognized) + [
        "the same edit as last time (from memory)" if repeat else "changes on top of your current edit (from memory)"]
    return type(it).model_validate(data)
MY_STYLE_PATTERNS = (r"\bmy (usual |favou?rite )?(style|look)\b", r"\busual (style|look)\b", r"\bmera (style|look)\b",
                     r"jo mujhe pasand", r"\bfavou?rite (style|look)\b")


def wants_repeat(prompt: str) -> bool:
    p = prompt.lower()
    return any(re.search(x, p) for x in REPEAT_PATTERNS)


def wants_my_style(prompt: str) -> bool:
    p = prompt.lower()
    return any(re.search(x, p) for x in MY_STYLE_PATTERNS)


class Memory:
    def __init__(self, db: Database) -> None:
        self.db = db
        with db.conn() as c:
            c.executescript(SCHEMA)

    # ---- writing ---------------------------------------------------------------------------------------
    def remember_edit(self, project_id: str, job_id: str, prompt: str, intent: dict[str, Any],
                      delivered: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO edit_memory(project_id, job_id, prompt, intent, delivered, chosen_style, rating, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (project_id, job_id, prompt, json.dumps(intent), json.dumps(delivered), delivered.get("style"), None, now_iso()),
        )

    # ---- hand-made changes (manual ops) are part of the current edit too ---------------------------------------
    def _ops_table(self) -> None:
        self.db.execute("CREATE TABLE IF NOT EXISTS manual_ops (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, "
                        "job_id TEXT, op TEXT, created_at TEXT)")

    def remember_manual(self, project_id: str, job_id: str, ops: list[dict[str, Any]]) -> None:
        """A change made by hand (Effects panel "Apply now", text edits): replayed on every later chat edit of the
        project, so asking the agent for something else does not throw it away."""
        self._ops_table()
        for op in ops:
            self.db.execute("INSERT INTO manual_ops(project_id, job_id, op, created_at) VALUES (?,?,?,?)",
                            (project_id, job_id, json.dumps(op), now_iso()))

    def manual_ops(self, project_id: str) -> list[dict[str, Any]]:
        self._ops_table()
        return [json.loads(r["op"]) for r in self.db.all(
            "SELECT op FROM manual_ops WHERE project_id=? ORDER BY id", (project_id,))]

    def forget_manual(self, project_id: str) -> None:
        """A new edit from scratch ("shuru se", "naya edit"): hand-made changes of the old edit no longer apply."""
        self._ops_table()
        self.db.execute("DELETE FROM manual_ops WHERE project_id=?", (project_id,))

    def forget_tool_calls(self, project_id: str) -> None:
        """A restore ("normal karo"): the skill changes made before it no longer belong to the current edit."""
        self._ops_table()
        self.db.execute("DELETE FROM manual_ops WHERE project_id=? AND op LIKE '%\"op\": \"tool_call\"%'", (project_id,))

    def remember_choice(self, job_id: str, style: str | None) -> None:
        self.db.execute("UPDATE edit_memory SET chosen_style=? WHERE job_id=?", (style, job_id))

    def remember_rating(self, job_id: str, rating: str) -> None:
        self.db.execute("UPDATE edit_memory SET rating=? WHERE job_id=?", (rating, job_id))

    # ---- reading ---------------------------------------------------------------------------------------
    def history(self, project_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        if project_id:
            rows = self.db.all("SELECT * FROM edit_memory WHERE project_id=? ORDER BY id DESC LIMIT ?", (project_id, limit))
        else:
            rows = self.db.all("SELECT * FROM edit_memory ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["intent"] = json.loads(r["intent"])
            r["delivered"] = json.loads(r["delivered"])
        return rows

    def last_intent(self, project_id: str) -> dict[str, Any] | None:
        """The previous edit of this project (falls back to the user's last edit anywhere)."""
        rows = self.history(project_id, 1) or self.history(None, 1)
        return rows[0]["intent"] if rows else None

    def reset_taste(self) -> None:
        """"Reset my taste": earlier edits no longer count for the preferences (the edits themselves stay)."""
        self.db.execute("CREATE TABLE IF NOT EXISTS taste_reset (at TEXT)")
        self.db.execute("DELETE FROM taste_reset")
        self.db.execute("INSERT INTO taste_reset (at) VALUES (?)", (now_iso(),))

    def _taste_since(self) -> str:
        try:
            row = self.db.all("SELECT at FROM taste_reset LIMIT 1")
        except Exception:  # noqa: BLE001 — no reset yet
            return ""
        return row[0]["at"] if row else ""

    def preferences(self) -> dict[str, Any]:
        since = self._taste_since()
        rows = [r for r in self.history(None, 200) if not since or str(r.get("created_at", "")) > since]
        if not rows:
            return {"edits_remembered": 0}
        liked_styles: Counter[str] = Counter()
        disliked_styles: Counter[str] = Counter()
        aspects: Counter[str] = Counter()
        looks: Counter[str] = Counter()
        captions = 0
        for r in rows:
            style = r["chosen_style"] or r["delivered"].get("style")
            if style:
                weight = 2 if r["chosen_style"] else 1          # an explicit "Use this" counts double
                if r["rating"] == "down":
                    disliked_styles[style] += 1
                else:
                    liked_styles[style] += weight + (1 if r["rating"] == "up" else 0)
            if r["delivered"].get("aspect_ratio"):
                aspects[r["delivered"]["aspect_ratio"]] += 1
            if r["delivered"].get("color_preset") not in (None, "none"):
                looks[r["delivered"]["color_preset"]] += 1
            captions += bool(r["intent"].get("captions"))
        fav = next((s for s, _ in liked_styles.most_common() if disliked_styles[s] < liked_styles[s]), None)
        return {
            "edits_remembered": len(rows),
            "favourite_style": fav,
            "disliked_styles": [s for s, n in disliked_styles.items() if n >= liked_styles[s]],
            "usual_aspect_ratio": aspects.most_common(1)[0][0] if aspects else None,
            "favourite_colour_look": looks.most_common(1)[0][0] if looks else None,
            "captions_share": round(captions / len(rows), 2),
        }

    def summary(self, project_id: str) -> str:
        """Short text the Director logs and gives to the LLM."""
        prefs = self.preferences()
        if not prefs.get("edits_remembered"):
            return "no previous edits yet"
        parts = [f"{prefs['edits_remembered']} past edits"]
        if prefs.get("favourite_style"):
            parts.append(f"favourite look: {prefs['favourite_style']}")
        if prefs.get("usual_aspect_ratio"):
            parts.append(f"usual aspect: {prefs['usual_aspect_ratio']}")
        if prefs.get("favourite_colour_look"):
            parts.append(f"often uses colour look: {prefs['favourite_colour_look']}")
        if prefs.get("disliked_styles"):
            parts.append(f"disliked looks: {', '.join(prefs['disliked_styles'])}")
        last = self.history(project_id, 1)
        if last:
            parts.append(f"last prompt here: \"{last[0]['prompt'][:80]}\"")
        return "; ".join(parts)
