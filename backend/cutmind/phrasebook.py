"""The agent learns the user's own words.

The rule parser (intent.py) is exact but only knows the phrasing it was taught. For a part of a prompt it does not
understand, the app does NOT guess silently: it asks "did you mean …?" with up to three suggestions, and the user's
pick is stored as a new phrase → command pair. From then on that phrase (and very close variants) is understood
without asking. Every not-understood clause is logged too: it is the data for the next round of rules or for
fine-tuning a language model.

Suggestions come from a small multilingual sentence-embedding model (paraphrase-multilingual-MiniLM-L12-v2,
Apache-2.0, 115 MB ONNX, ~15 ms per sentence on CPU) over a bank of example sentences. Measured on Hinglish it is
only right about half the time, so it is used for SUGGESTIONS the user confirms — never applied on its own — except
for phrases the user taught (similarity ≥ 0.93 to a taught phrase).
"""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

import numpy as np

from .db import Database, now_iso
from .intent import AUTO_EDIT, parse_intent

EMBED_REPO = "Xenova/paraphrase-multilingual-MiniLM-L12-v2"
TAUGHT_MATCH = 0.93
SUGGEST_MIN = 0.6

# command (an English sentence the rule parser understands) → short label shown on the chip
COMMANDS: dict[str, str] = {
    "Fast cuts.": "fast cuts", "Slow motion.": "slow motion", "Cut on the beat.": "cut on the beat",
    "Zoom in effect.": "zoom in", "Strong zoom in for the first 3 seconds.": "big zoom at the start",
    "Shake effect.": "camera shake", "Pulse effect.": "zoom punch on the beat", "Glitch effect.": "glitch",
    "Flash effect.": "white flash", "Old movie black and white look.": "old-movie black & white",
    "Black and white.": "black & white", "Warm color.": "warm colours", "Cool color.": "cool colours",
    "Vivid color.": "strong colours", "Faded film look.": "faded / dull colours", "Cinematic color.": "cinematic look",
    "Brighter.": "brighter", "Darker.": "darker", "Add captions.": "captions", "Remove the captions.": "no captions",
    "Remove silences.": "cut the silent parts", "Remove filler words.": "cut um / uh", "Clean up the audio.": "remove noise",
    "Boost the voice.": "voice louder", "Add upbeat music.": "upbeat music", "Add calm music.": "calm music",
    "No music.": "no music", "Mute the original sound.": "mute the clip's sound", "Blur the background.": "blur background",
    "Speed ramp.": "speed ramp", "9:16 vertical.": "vertical 9:16", "16:9 landscape.": "landscape 16:9",
    "Fade transitions.": "fade between shots", "Auto edit: you decide everything else.": "let the AI decide",
    "Keep the text in front of the person.": "text in front", "Text behind the person.": "text behind the person",
    "Make it louder.": "louder", "Vignette effect.": "dark corners", "Film grain effect.": "film grain",
}
SEED: dict[str, list[str]] = {
    "Fast cuts.": ["cut quickly between shots", "jaldi jaldi cut karo", "scene jaldi badlo", "quick cuts chahiye"],
    "Slow motion.": ["slow down the video", "dheere chalao", "slow mo karo"],
    "Shake effect.": ["make the camera shake", "screen hilao", "camera jhatka do", "video hilna chahiye"],
    "Pulse effect.": ["zoom punch on the beat", "beat pe jhatka", "beat ke saath zoom", "screen hile jab beat aaye"],
    "Old movie black and white look.": ["make it look like an old film", "purani film jaisa", "old tv jaisa effect"],
    "Faded film look.": ["colours dull kar do", "rang halke karo", "faded colours", "desaturate it", "rang feeke",
                         "rang kam karo", "colour fika karo", "less colourful", "muted colours", "rang dabe hue"],
    "Vivid color.": ["colours tez karo", "rang gehre karo", "make colours pop", "rang chatak karo", "zyada rangeen"],
    "Cinematic color.": ["make it look like a movie", "film jaisa look do", "movie trailer jaisa look", "dramatic look"],
    "Clean up the audio.": ["remove the background noise", "awaaz saaf karo", "noise hatao", "hawa ki awaaz hatao",
                            "awaaz me khar khar hai", "sound me shor hai", "aawaz gungunati hai", "hiss remove karo"],
    "Remove silences.": ["cut the parts where nobody talks", "jahan chup hai wo hatao", "remove dead air",
                         "khali hissa hatao", "jab koi nahi bol raha"],
    "Auto edit: you decide everything else.": ["make it exciting", "isme jaan daal do", "boring hai mast bana do"],
    "Add captions.": ["jo bol raha hu wo likh do", "subtitles daalo", "words screen pe dikhao", "bolne wale shabd likho"],
    "Brighter.": ["thoda ujala karo", "andhera hai", "roshni badhao", "video kala lag raha hai"],
    "Darker.": ["thoda andhera karo", "bahut bright hai", "roshni kam karo"],
    "Warm color.": ["garam rang", "sunehra look", "peela sa warm tone", "golden look"],
    "Cool color.": ["thanda rang", "neela sa tone", "blue tone do"],
    "Boost the voice.": ["meri awaaz tez karo", "voice sunai nahi de rahi", "bolna clear sunai de"],
    "No music.": ["gaana mat lagao", "bina music ke", "music nahi chahiye"],
    "Mute the original sound.": ["video ki awaaz band karo", "original sound hatao", "clip ki awaaz mat rakho"],
    "Zoom in effect.": ["paas se dikhao", "close up karo", "andar ki taraf zoom"],
    "Glitch effect.": ["toota hua screen effect", "digital kharabi wala effect", "glitchy look"],
    "Flash effect.": ["safed chamak", "white flash do", "camera flash jaisa"],
    "Blur the background.": ["peeche ka blur karo", "background dhundhla karo"],
    "9:16 vertical.": ["reel size", "phone ke liye khada video", "instagram reel format"],
    "16:9 landscape.": ["youtube size", "leta hua video", "wide format"],
    "Remove filler words.": ["um aa hata do", "matlab matlab bolna hata do", "atakna hata do"],
    "Add upbeat music.": ["josh wala gaana", "party music lagao", "energetic song daalo"],
    "Add calm music.": ["shaant gaana lagao", "soft music", "lofi lagao"],
    "Speed ramp.": ["pehle slow phir fast", "speed badalte raho"],
    "Fade transitions.": ["dheere dheere badle scene", "smooth transition", "fade karke badlo"],
    "Vignette effect.": ["kinare kale karo", "corners dark"],
    "Film grain effect.": ["daane daar film", "grainy look"],
}
_FILLER = re.compile(r"^(bhai|yaar|please|pls|plz|ok|okay|ji|na|sir|bro|aur|and|also|bhi|edit|video|kar|karo|kar do|"
                     r"de|do|isko|isme|mera|meri|this|the|a|it|ko|ka|ki|ke|hai|h|haan|thoda|thode|thodi|zara|jara|sa|si|se)$")
_lock = threading.Lock()
_model: Any = None


def _embedder() -> Any:
    """(session, tokenizer) or None when the model can't be loaded (then suggestions use word overlap)."""
    global _model
    with _lock:
        if _model is None:
            try:
                import onnxruntime as ort
                from huggingface_hub import hf_hub_download
                from tokenizers import Tokenizer

                tok = Tokenizer.from_file(hf_hub_download(EMBED_REPO, "tokenizer.json"))
                tok.enable_truncation(128)
                tok.enable_padding()
                sess = ort.InferenceSession(hf_hub_download(EMBED_REPO, "onnx/model_quantized.onnx"),
                                            providers=["CPUExecutionProvider"])
                _model = (sess, tok)
            except Exception:  # noqa: BLE001 — offline / not downloaded: fall back
                _model = False
        return _model or None


# The translator may only say something the user's words are about: "boat wala part zyada dikhao" came back as
# "Boost the voice" (from "zyada"). (English words of the answer → words one of which the user must have used.)
TOPICS: list[tuple[str, str]] = [
    (r"\b(voice|speech|dialogue)\b", r"awaa?z|aawaa?z|awaj|voice|bol|audio|sound|baat|speech|dialog|aavaz"),
    (r"\b(music|songs?|beats?)\b", r"gaa?n|music|song|bgm|beat|dhun|track|audio|sound"),
    (r"\b(mute|sound|audio|loud|quiet|volume|noise)\b", r"awaa?z|aawaa?z|awaj|audio|sound|volume|mute|shor|noise|gaa?n|music"),
    (r"\b(captions?|subtitles?|titles?|text|words?)\b", r"text|likh|caption|subtitle|naam|title|shabd|word|lyrics"),
    (r"\b(colou?r|black|white|bright|dark|warm|cool|grade|look|vintage|cinematic|saturat)", r"rang|colou?r|bw|black|white|"
     r"bright|dark|andher|roshni|warm|cool|garam|thand|look|filter|vintage|purana|film|cinematic|tez|feeka"),
    (r"\b(slow|fast|speed|pace)\b", r"slow|fast|tez|speed|dheer|jaldi|aaram|pace|motion"),
    (r"\b(zoom|close)\b", r"zoom|paas|close|bada|chehra|face"),
    (r"\b(transitions?|crossfades?|fades?|blend)\b", r"transition|smooth|blend|fade|mix|jod|badal"),
    (r"\b(seconds?|minute|long|short|length)\b", r"sec|second|minute|min|chhota|chota|lamba|short|long|length|time"),
    (r"\b(silences?|pauses?|silent|fillers?)\b", r"chup|silence|khamosh|pause|bol|ruk|gap|um"),
]


def _topic_supported(english: str, phrase: str) -> bool:
    e, p = english.lower(), phrase.lower()
    return all(re.search(hint, p) for topic, hint in TOPICS if re.search(topic, e))


WAIT_TRANSLATION = 3.0  # s a chat message waits for the translator
_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="translator")
_TRANSLATIONS: dict[str, Future] = {}

_EMB_CACHE: dict[str, np.ndarray] = {}  # the example sentences never change: embed them once (was 5 s per message)


def embed(texts: list[str]) -> np.ndarray | None:
    m = _embedder()
    if m is None or not texts:
        return None
    todo = list(dict.fromkeys(t for t in texts if t not in _EMB_CACHE))
    if todo:
        for i in range(0, len(todo), 64):
            chunk = todo[i:i + 64]
            for t, v in zip(chunk, _embed_now(m, chunk), strict=True):
                _EMB_CACHE[t] = v
        if len(_EMB_CACHE) > 5000:
            _EMB_CACHE.clear()
            return _embed_now(m, texts)
    return np.stack([_EMB_CACHE[t] for t in texts])


def warm_up() -> None:
    """Load the model and embed the example bank in the background at server start."""
    try:
        bank = [ex for exs in SEED.values() for ex in exs] + list(COMMANDS.values())
        embed(bank)
    except Exception:  # noqa: BLE001
        pass


def _embed_now(m: Any, texts: list[str]) -> np.ndarray:
    sess, tok = m
    enc = tok.encode_batch(texts)
    ids = np.array([e.ids for e in enc], dtype=np.int64)
    mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
    feed = {"input_ids": ids, "attention_mask": mask}
    if any(i.name == "token_type_ids" for i in sess.get_inputs()):
        feed["token_type_ids"] = np.zeros_like(ids)
    out = sess.run(None, feed)[0]
    v = (out * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def normalize(phrase: str) -> str:
    """Hinglish word forms count as one: thoda/thode/thodi, feeka/feeke, karo/kar do → the same key."""
    words = [w for w in re.findall(r"[\w']+", phrase.lower()) if not _FILLER.match(w)]
    words = [re.sub(r"(.)\1+", r"\1", w) for w in words]  # spellings: aawaz / awaaz → awaz, feeka → feka
    return " ".join(w[:-1] if len(w) > 3 and w[-1] in "aeiou" else w for w in words)


def clauses(prompt: str) -> list[str]:
    # "black and white" / "black & white" is one thing, not two clauses joined by "and"
    keep = re.sub(r"(?i)black\s*(and|&|n)\s*white", "black_and_white", prompt)
    parts = re.split(r",|;|\.(?=\s|$)|\?|!|\b(?:aur|and|but|lekin|phir|then|also)\b", keep)
    return [c.strip().replace("black_and_white", "black and white") for c in parts if c and c.strip()]


def unclear(prompt: str) -> list[str]:
    """Parts of the prompt the rule parser understood nothing from (and that are not just filler words)."""
    out = []
    for c in clauses(prompt):
        words = [w for w in re.findall(r"[\w']+", c.lower()) if not _FILLER.match(w)]
        # "<anything> kar do" falls back to auto edit in the parser; that is not understanding it
        real = [r for r in parse_intent(c).recognized
                if not r.startswith("auto edit") or any(re.search(p, c.lower()) for p in AUTO_EDIT)]
        if len(words) >= 2 and not real:
            out.append(c)
    return out


REPLACE_BELOW = 0.34  # coverage under this: the model's reading REPLACES the rules' guess for that clause
HALF_UNDERSTOOD = 0.6  # coverage below this = the rules probably guessed (prenormalize.coverage)
LLM_BUDGET = 40.0  # s of model time per message at most (CPU); the rules' answer stands after that


def _llm(phrase: str, t0: float) -> str | None:
    from .llm_router import understand_phrase

    try:
        return understand_phrase(phrase, deadline=t0 + LLM_BUDGET)
    except Exception:  # noqa: BLE001 — the model never breaks an edit
        return None


class PhraseBook:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.translated: dict[str, str] = {}  # phrase → English from the trained model (shown to the user)
        db.execute("CREATE TABLE IF NOT EXISTS phrasebook (phrase TEXT PRIMARY KEY, command TEXT, created_at TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS phrase_misses (phrase TEXT PRIMARY KEY, count INTEGER, last_at TEXT)")

    def taught(self) -> dict[str, str]:
        return {r["phrase"]: r["command"] for r in self.db.all("SELECT phrase, command FROM phrasebook")}

    def teach(self, phrase: str, command: str) -> None:
        if command not in COMMANDS:
            raise ValueError(f"unknown command '{command}'")
        self.db.execute("INSERT OR REPLACE INTO phrasebook(phrase, command, created_at) VALUES (?,?,?)",
                        (phrase.strip().lower(), command, now_iso()))
        self.db.execute("DELETE FROM phrase_misses WHERE phrase=?", (phrase.strip().lower(),))

    def miss(self, phrase: str) -> None:
        p = phrase.strip().lower()
        row = self.db.one("SELECT count FROM phrase_misses WHERE phrase=?", (p,))
        self.db.execute("INSERT OR REPLACE INTO phrase_misses(phrase, count, last_at) VALUES (?,?,?)",
                        (p, (row["count"] if row else 0) + 1, now_iso()))

    def misses(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.db.all("SELECT phrase, count, last_at FROM phrase_misses ORDER BY count DESC, last_at DESC LIMIT ?",
                           (limit,))

    def resolve(self, phrase: str) -> str | None:
        """The command for a phrase the user taught (exact, or very close in meaning)."""
        taught = self.taught()
        p = phrase.strip().lower()
        if p in taught:
            return taught[p]
        norm = {normalize(k): v for k, v in taught.items()}
        if normalize(p) in norm:
            return norm[normalize(p)]
        if not taught:
            return None
        keys = list(taught)
        e = embed([p, *keys])
        if e is None:
            return None
        sims = e[1:] @ e[0]
        k = int(np.argmax(sims))
        return taught[keys[k]] if sims[k] >= TAUGHT_MATCH else None

    def suggest(self, phrase: str, n: int = 3) -> list[dict[str, Any]]:
        """Up to n commands this phrase may mean (best first), for the user to confirm."""
        bank = [(cmd, ex) for cmd, exs in SEED.items() for ex in exs] + [(c, p) for p, c in self.taught().items()]
        bank += [(cmd, label) for cmd, label in COMMANDS.items()]
        e = embed([phrase, *[b[1] for b in bank]])
        score: dict[str, float] = {}
        if e is not None:
            sims = e[1:] @ e[0]
            for (cmd, _ex), s in zip(bank, sims, strict=True):
                score[cmd] = max(score.get(cmd, -1.0), float(s))
        else:  # no model: shared words
            words = set(re.findall(r"\w+", phrase.lower()))
            for cmd, ex in bank:
                ov = len(words & set(re.findall(r"\w+", ex.lower()))) / max(1, len(words))
                score[cmd] = max(score.get(cmd, 0.0), ov)
        best = sorted(score.items(), key=lambda kv: -kv[1])[:n]
        return [{"command": c, "label": COMMANDS[c], "score": round(s, 2)} for c, s in best if s >= SUGGEST_MIN]

    def _translate(self, phrase: str) -> str | None:
        """The trained Hinglish → English model (if installed): its English must be understood by the rules."""
        from .translator import Translator, is_known, trained_available

        if not trained_available():
            return None
        # on a laptop short of RAM one translation took 5-20 s: the chat answers after WAIT_TRANSLATION seconds
        # ("samajh nahi aaya" + suggestions); the translation finishes in the background, so asking again works
        fut = _TRANSLATIONS.get(phrase)
        wait = 0.0 if fut is not None else WAIT_TRANSLATION  # already waited for once (/understand): don't again
        if fut is None:
            fut = _POOL.submit(Translator("trained").translate, phrase)
            _TRANSLATIONS[phrase] = fut
            if len(_TRANSLATIONS) > 300:
                _TRANSLATIONS.pop(next(iter(_TRANSLATIONS)))
        try:
            english = fut.result(timeout=wait) if not fut.done() else fut.result()
        except FutureTimeout:
            return None
        except Exception:  # noqa: BLE001 — a broken model file never breaks the edit
            return None
        # destructive commands (mute, remove, no X) only when the user's words also take something away — the model
        # once turned "audio sunai nahi de raha" (a complaint) into "Mute the original sound"
        takes_away = re.search(r"\b(mute|hata\w*|band|nikal\w*|remove|off|bina|mat|nahi chahiye|no|without|delete)\b",
                               phrase.lower())
        if english and re.search(r"\b(mute|remove|no|without|delete)\b", english.lower()) and not takes_away:
            return None
        if english and not _topic_supported(english, phrase):
            return None
        if english and english != "-" and is_known(english) and parse_intent(english).recognized:
            self.translated[phrase] = english
            return english
        return None

    def expand(self, prompt: str, ask: bool = True) -> tuple[str, list[dict[str, Any]]]:
        """The prompt with taught phrases turned into commands, and the parts still unclear (with suggestions when
        `ask`). Unclear parts are logged as misses when asked about."""
        from .prenormalize import coverage, normalize
        from .skill_registry import covers as skill_covers

        prompt = normalize(prompt)  # Devanagari → Hinglish, "captins" → captions (deterministic)
        extra: list[str] = []
        still: list[dict[str, Any]] = []
        t0 = time.monotonic()
        # half-understood clauses: the rules read SOMETHING but most words are not the editor's own
        # ("gaane ki awaaz dheemi" was read as "upbeat music") — the planner model reads them; its answer replaces
        # the rules' guess for that clause only
        replaced: dict[str, str] = {}
        for c in clauses(prompt):
            if c in unclear(c) or coverage(c) >= HALF_UNDERSTOOD or skill_covers(c) or self.resolve(c):
                continue
            cmd = _llm(c, t0)
            if cmd:
                # the rules mostly guessed → the model's reading replaces it; they half-knew it ("old vhs tape" →
                # vhs was right) → both readings are kept
                replaced[c] = cmd if coverage(c) < REPLACE_BELOW else f"{c}. {cmd}"
        if replaced:
            prompt = ". ".join(replaced.get(c, c) for c in clauses(prompt))
        for c in unclear(prompt):
            # the whole message gets ~6 s of translating at most: the chat must answer quickly
            # taught phrase → planner LLM (llm_router: small model, bigger one if unsure) → fine-tuned translator
            cmd = self.resolve(c) or _llm(c, t0) or (self._translate(c) if time.monotonic() - t0 < 6.0 else None)
            if cmd:
                extra.append(cmd)
            elif ask:
                self.miss(c)
                still.append({"text": c, "suggestions": self.suggest(c)})
        # added as their own sentences: a "No …" command must never merge with the user's last clause
        return (prompt.rstrip(" .") + ". " + " ".join(extra) if extra else prompt), still
