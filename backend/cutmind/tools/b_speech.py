"""talking_head_reel — "jo bolo wo screen pe aaye": the editorial talking-head edit of vlogs / YouTube / reels.

From the speech's own word times (faster-whisper, analyzer):
1. captions that follow the voice — each word lights up when it is SAID (spoken words bright, the rest of the line
   grey), short lines, on every layout;
2. the layout changes with the sentences — full frame → the shot as a card on cream paper → the shot in the top half
   with the words below — never two sentences in a row in the same layout (keeps a talking head moving);
3. keyword cards — the strongest words of what is said (numbers, long content words, repeated words), big, on the
   moment they are said, never two closer than KEY_GAP;
4. an @handle in the corner (if given) and, when the speaker says "comment X" / "type X in the comments", a call-to-
   action card "COMMENT X ↗" until the end.
Everything is placed from the measured speech; nothing is tied to one video.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..plan import EditPlan, Effect, TextItem, TextStyle
from .engine import ToolCtx, tool
from .timeline import ToolError, split_at
from .timewin import When

MARK = "talking_head"
KEY_GAP = 3.0          # s between two keyword cards
LAYOUTS = ("full", "inset_card", "full", "split_top")
STOP = set("""a an the and or but if so to of in on at for with from by is are was were be been am i you he she it we
they me my your our their this that these those there here then than as not no do does did have has had will would
can could just like really very also all any some what when where who how why which yeah okay ok um uh oh hey hi
right now get got gets going go one more most much many make makes made take takes thing things lot across about
into over after before through out off up down again ever even only still i'll i'm you're it's that's don't won't
can't let's we're they're""".split())


@dataclass
class W:
    text: str
    start: float
    end: float


def spoken_words(plan: EditPlan, ctx: ToolCtx) -> list[W]:
    """The transcript's words in OUTPUT seconds (only those inside the current cut)."""
    if ctx.analysis is None:
        raise ToolError("this edit needs speech-to-text, which is not available here")
    an = ctx.analysis()
    out: list[W] = []
    for e in plan.timeline():
        s = e.segment
        for w in an.get(s.source).words:
            if w.start >= s.in_ - 0.02 and w.end <= s.out + 0.02:
                f = lambda t: e.start + min(1.0, max(0.0, (t - s.in_) / s.source_duration)) * e.duration  # noqa: E731
                out.append(W(w.text.strip(), round(f(w.start), 3), round(f(w.end), 3)))
    out.sort(key=lambda w: w.start)
    if not out:
        raise ToolError("no speech found in this video — this edit puts what is said on screen")
    return out


def sentences(words: list[W], gap: float = 0.55, max_len: float = 7.0) -> list[list[W]]:
    """Sentences: a full stop / ? / ! ends one, so does a pause ≥ `gap`, or a run longer than `max_len` s."""
    out: list[list[W]] = []
    cur: list[W] = []
    for w in words:
        if cur and (w.start - cur[-1].end >= gap or w.end - cur[0].start > max_len):
            out.append(cur)
            cur = []
        cur.append(w)
        if w.text.endswith((".", "?", "!")):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _clean(t: str) -> str:
    return re.sub(r"[^\w'%.\-]", "", t).strip(".").lower()


def keywords(words: list[W], total: float, n: int | None = None) -> list[tuple[float, float, str]]:
    """(start, end, PHRASE) of the strongest things said: a content word (+ the next content word or a number), scored
    by length, numbers, repetition; at most one every KEY_GAP s; never in the first / last second."""
    n = n if n is not None else max(1, min(8, int(total / 6)))
    counts: dict[str, int] = {}
    for w in words:
        counts[_clean(w.text)] = counts.get(_clean(w.text), 0) + 1
    cands = []
    for i, w in enumerate(words):
        c = _clean(w.text)
        if not c or c in STOP or len(c) < 4 and not any(ch.isdigit() for ch in c):
            continue
        score = min(len(c), 10) + (4 if any(ch.isdigit() for ch in c) else 0) + 2 * (counts[c] - 1)
        phrase = [w]
        for nxt in words[i + 1:i + 3]:  # "future of video", "day 3", "every keyframe"
            cn = _clean(nxt.text)
            if nxt.start - phrase[-1].end > 0.35 or not cn or phrase[-1].text.endswith((".", ",", "?", "!")):
                break
            phrase.append(nxt)
            if cn not in STOP:
                break
        while len(phrase) > 1 and _clean(phrase[-1].text) in STOP:
            phrase.pop()
        cands.append((score, phrase))
    chosen: list[tuple[float, float, str]] = []
    for score, ph in sorted(cands, key=lambda x: -x[0]):
        s = ph[0].start
        if s < 1.0 or s > total - 1.0 or any(abs(s - c[0]) < KEY_GAP for c in chosen):
            continue
        if any(_clean(ph[0].text) in c[2].lower() for c in chosen):
            continue  # the same word twice is no news
        text = " ".join(re.sub(r"[^\w'%.\- ]", "", x.text) for x in ph).strip(" .").upper()
        if text:
            chosen.append((s, min(total, max(s + 1.0, ph[-1].end + 0.6)), text))
        if len(chosen) >= n:
            break
    return sorted(chosen)


CTA_SKIP = STOP | {"comment", "comments", "below", "niche", "neeche", "type", "write", "likho", "link", "send", "karo",
                   "kar", "kardo", "karna", "karein", "karde", "mein", "aur", "main", "bhai", "please", "zaroor", "word", "words", "naam"}


def cta_word(words: list[W]) -> tuple[float, str] | None:
    """The word the viewer should comment, said near the end → (when it is said, WORD):
    "type MOTION in the comments", "comment MOTION", "MOTION likho comments me". The word right before "in the
    comment(s)" wins; then the word after "type / comment / write"."""
    tail = words[int(len(words) * 0.5):]
    cs = [_clean(w.text) for w in tail]

    def ok(c: str) -> bool:
        return len(c) >= 3 and c.isalpha() and c not in CTA_SKIP

    for i, c in enumerate(cs):  # "<WORD> in the comment(s)" / "<WORD> comments me"
        if c.startswith("comment") and i >= 1:
            j = i - 1
            while j >= 0 and cs[j] in ("in", "the", "a", "my", "your"):
                j -= 1
            after = cs[i + 1] if i + 1 < len(cs) else ""
            # only "<WORD> in the comments" / "<WORD> comments me": the word before must be joined to it
            if j >= 0 and (j < i - 1 or after in ("me", "mein", "pe", "par")) and ok(cs[j]):
                return tail[j].start, cs[j].upper()
    for i, c in enumerate(cs):  # "type / comment / write <WORD>"
        if c in ("comment", "type", "write", "likho", "bolo"):
            nxt = next((k for k in range(i + 1, min(i + 5, len(cs))) if ok(cs[k])), None)
            if nxt is not None:
                return tail[nxt].start, cs[nxt].upper()
    return None


@tool("talking_head_reel")
def talking_head_reel(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    from .b_text import _captions

    words = spoken_words(plan, ctx)
    total = plan.total_duration()
    sents = sentences(words)

    # 2. layouts: split on the sentences, a different layout for each next sentence
    layout_at: list[tuple[float, float, str]] = []
    if p["layouts"] and len(sents) > 1:
        starts = [round(s[0].start, 3) for s in sents[1:]]
        for t in reversed(starts):
            if 0.6 < t < total - 0.6:
                try:
                    plan = split_at(plan, t)
                except ToolError:
                    continue
        tl = plan.timeline()
        k = 0
        for e in tl:
            lay = LAYOUTS[k % len(LAYOUTS)]
            layout_at.append((e.start, e.end, lay))
            k += 1
    data = plan.to_json()
    data["effects"] = [e for e in data["effects"] if not (e.get("params") or {}).get(MARK)]
    for i, (_a, _b, lay) in enumerate(layout_at):
        if lay != "full":
            data["effects"].append(Effect(type=lay, target=i, params={MARK: 1.0}).model_dump())

    def layout(t: float) -> str:
        return next((lay for a, b, lay in layout_at if a - 1e-3 <= t < b), "full")

    # 1. captions that follow the voice (spoken bright, upcoming grey); dark on the paper layouts
    caps = _captions(plan, ctx, {"position": "bottom", "size": 46, "words_per_line": 5})
    data["text"] = [t for t in data["text"] if t["kind"] != "caption" and MARK not in (t["style"].get("preset") or "")]
    for c in caps:
        lay = layout(c.start)
        paper = lay != "full"
        st = TextStyle(position="bottom", size=56 if paper else 64, box_color=None, animation="karaoke", font="poppins",
                       color="#9A958C" if paper else "#BDBDBD", highlight="#141414" if paper else "#FFFFFF",
                       outline=0 if paper else 2, shadow=0 if paper else 1.5,
                       margin=0.36 if lay == "split_top" else (0.12 if lay == "inset_card" else 0.13),
                       preset=f"{MARK}_caption")
        data["text"].append(c.model_copy(update={"style": st}).model_dump())

    # 3. keyword cards on the moment they are said
    keys = keywords(words, total) if p["keywords"] else []
    for s, e, text in keys:
        lay = layout(s)
        paper = lay != "full"
        # big condensed headline that fills the width (Anton, OFL): size from the length, in the lower part of the
        # frame so the face stays free; dark on paper, white with an outline on the picture
        size = max(70, min(190, int(1900 / max(4, len(text)))))
        if lay == "inset_card":  # the strip of paper under the card is low: smaller words
            size = min(size, 120)
        st = TextStyle(position="bottom", size=size, box_color=None, animation="pop", font="anton",
                       color="#141414" if paper else "#FFFFFF", outline=0 if paper else 3, shadow=0 if paper else 2,
                       uppercase=True, margin=0.2 if lay == "split_top" else (0.025 if lay == "inset_card" else 0.24),
                       preset=f"{MARK}_key")
        data["text"].append(TextItem(kind="title", text=text[:60], start=round(s, 3), end=round(e, 3),
                                     style=st).model_dump())

    # 4. handle + call to action
    if p.get("handle"):
        h = "@" + str(p["handle"]).lstrip("@").upper()[:30]
        data["text"].append(TextItem(kind="text", text=h, start=0.0, end=round(total, 3),
                                     style=TextStyle(position="top_right", size=34, box_color=None, color="#FFFFFF",
                                                     outline=1.5, preset=f"{MARK}_handle")).model_dump())
    cta = cta_word(words) if p["cta"] else None
    if cta and cta[0] < total - 0.5:
        data["text"].append(TextItem(kind="title", text=f"COMMENT  {cta[1]}  ↗", start=round(cta[0], 3),
                                     end=round(total, 3),
                                     style=TextStyle(position="bottom", size=78, box_color="#F4F1EA", color="#141414",
                                                     font="anton", animation="pop", margin=0.2,
                                                     preset=f"{MARK}_cta")).model_dump())
    n_lay = sum(1 for *_x, lay in layout_at if lay != "full")
    ctx.notes.append(f"{len(caps)} caption lines that follow the voice, {len(keys)} keyword card(s)"
                     + (f" ({', '.join(t for *_x, t in keys[:4])})" if keys else "")
                     + f", {n_lay} layout change(s)" + (f", CTA 'COMMENT {cta[1]}'" if cta else ""))
    return EditPlan.model_validate(data)
