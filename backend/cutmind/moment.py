"""Comments on the timeline: the user stops the video at a moment, long-presses / clicks there and writes what they
want ("yaha zoom", "WOW likh do", "rose", "ye part hata do"). The edit happens AT that moment only — the rest of the
current edit stays as it is, and every earlier comment stays too.

What a comment can do at its moment (output seconds of the CURRENT edit):
  - an effect for a few seconds ("zoom", "glitch", "black and white", "slow motion")
  - text on screen ("WOW likh do", "'Goa' likho"; a short comment that is no edit at all is written as it is)
  - a sticker ("rose", "yaha ped ka sticker")
  - cut that part out ("ye part hata do", "ye nahi chahiye")
"""

from __future__ import annotations

import re
from typing import Any

from . import stickers
from .intent import Intent, TimedEffect, TimedText, parse_intent
from .plan import EditPlan

PUNCH = {"zoom", "zoom_out", "shake"}
SECONDS = 2.5      # how long a comment's effect / text lasts
MAX_TEXT_WORDS = 6  # a comment that is no edit is written on screen only when it is this short

CUT = re.compile(r"\b(hata|hatao|hata do|nikal|nikalo|kaat|kaato|kat do|cut|delete|remove|nahi chahiye|nhi chahiye|"
                 r"mat dikhao|skip)\w*", re.I)
TEXT_GONE = re.compile(r"\b(text|likha|likhawat|word|words|shabd|naam|title|caption)\w*\b.{0,20}"
                       r"\b(hata|hatao|nikal|remove|delete|mita|mitao|band)\w*", re.I)
QUESTION = re.compile(r"\?|\b(kya|kyu|kyun|kaise|why|how|what)\b", re.I)
# "add rose", "yaha gulab lagao": the thing itself is wanted there (a sticker), not the sentence as text
ADD = re.compile(r"\b(add|daal|dal|daalo|dalo|laga|lagao|lagado|dikha|dikhao|put|show|insert|chahiye)\w*", re.I)
# an instruction nobody understood is never written on screen as it is
ASK = re.compile(r"\b(karo|kar do|kardo|kr do|add|lagao|daalo|dalo|hatao|banao|make|put|please|plz)\b", re.I)


def read_comment(text: str) -> dict[str, Any]:
    """What a timeline comment asks for: {effects, text, emoji, cut, understood: [...]} — understood empty = nothing."""
    t = text.strip()
    it = parse_intent(t)
    out: dict[str, Any] = {"effects": [], "text": None, "emoji": None, "cut": False, "restyle": None, "understood": []}
    # the text that is ON SCREEN at that moment: its colour / size, or take it away ("text white karo", "ye text hata do")
    remove_text = bool(TEXT_GONE.search(t))
    if it.text_color or it.text_scale or remove_text:
        out["restyle"] = {"color": it.text_color, "scale": it.text_scale, "remove": remove_text}
        return _said(out)
    fx = list(it.effects)
    if it.color_preset in ("bw", "noir"):
        fx.append("mono")
    if it.slow_motion or it.slow_end:
        fx.append("speed_ramp")
    out["effects"] = list(dict.fromkeys(fx))
    out["text"] = it.title or it.end_text or it.tracked_text
    quoted = re.search(r"[\"'“‘](.{1,40}?)[\"'”’]", t)
    if quoted and not out["text"]:
        out["text"] = quoted.group(1).strip()
    words = re.findall(r"[\w']+", t.lower())
    emoji = next((e for w in words if (e := stickers.emoji_for(w))), None)
    wants_sticker = bool(re.search(r"\b(sticker|emoji|icon|animation)\w*", t, re.I) or ADD.search(t))
    # a sticker when asked for one ("rose ka sticker") or when the comment is just the thing ("rose")
    if emoji and (wants_sticker or len(words) == 1 and not (out["effects"] or out["text"])) and stickers.available():
        out["emoji"] = emoji
    out["cut"] = bool(CUT.search(t)) and not (out["effects"] or out["text"] or out["emoji"])
    if not (out["effects"] or out["text"] or out["emoji"] or out["cut"]) and t and not QUESTION.search(t) \
            and len(words) <= MAX_TEXT_WORDS and not ASK.search(t):
        out["text"] = t[:60]  # "jo bhi likhu vo add ho jaye": a short note is written there as it is
        out["as_written"] = True
    return _said(out)


def _said(out: dict[str, Any]) -> dict[str, Any]:
    u = out["understood"]
    r = out.get("restyle")
    if r:
        u.append("remove the text here" if r["remove"] else "the text here " + ", ".join(
            x for x in (f"colour {r['color']}" if r["color"] else "", f"size x{r['scale']:g}" if r["scale"] else "") if x))
    u += [f"{e} effect" for e in out["effects"]]
    if out["text"]:
        u.append(f"text '{out['text']}'")
    if out["emoji"]:
        u.append(f"sticker {out['emoji']}")
    if out["cut"]:
        u.append("cut this part out")
    return out


def segment_at(plan: EditPlan, t: float) -> dict[str, Any] | None:
    """The shot playing at output second t of this plan: its clip, source in/out and output start/end."""
    for e in plan.timeline():
        if e.start - 1e-3 <= t < e.end + 1e-3:
            s = e.segment
            return {"source": s.source, "in": s.in_, "out": s.out, "start": e.start, "end": e.end}
    return None


def moment_options(text: str, at: float, plan: EditPlan) -> dict[str, Any]:
    """The job option for a comment at `at` on `plan` (raises ValueError with a Hinglish reason when it can't)."""
    total = plan.total_duration()
    if not 0 <= at < total:
        raise ValueError(f"{at:.1f}s is outside the video ({total:.1f}s).")
    c = read_comment(text)
    if not c["understood"]:
        raise ValueError(f'Is moment ({at:.1f}s) ke liye "{text[:60]}" samajh nahi aaya. Aise likho: "zoom", '
                         '"WOW likh do", "rose ka sticker", "black and white", "ye part hata do".')
    if c.get("restyle"):  # a change to the text on screen right then: there must be one
        on = [x for x in plan.text if x.start - 0.05 <= at < x.end + 0.05]
        if not on:
            raise ValueError(f"Is moment ({at:.1f}s) pe koi text nahi dikh raha — jis second pe text hai wahan "
                             "comment karo, ya poori video ke liye chat mein likho (jaise \"text white karo\").")
    seg = segment_at(plan, at)
    m: dict[str, Any] = {"at": round(at, 3), "end": round(min(total, at + SECONDS), 3), **c}
    if c["cut"]:
        if seg is None or len(plan.clips) < 2 and seg["end"] - seg["start"] >= total - 0.05:
            raise ValueError("Ye poori video ka akela shot hai — isko hata diya to kuch nahi bachega.")
        m["cut_range"] = [seg["source"], seg["in"], seg["out"]] if seg else None
    return m


def moment_intent(m: dict[str, Any]) -> Intent:
    """An Intent that changes only that moment (merged on top of the current edit by memory)."""
    a, b = float(m["at"]), float(m["end"])
    it = Intent(from_comment=True)
    # stronger than the whole-video default (1.0): a comment's effect must be seen at its moment, also on top of an
    # edit that already has a gentle zoom everywhere
    it.timed_effects = [TimedEffect(effect=e, start=a, end=b, strength=1.6 if e in PUNCH else 1.0)
                        for e in m.get("effects") or []]
    if m.get("text"):
        it.timed_texts = [TimedText(text=m["text"], start=a, end=b)]
    if m.get("emoji"):
        it.moment_stickers = [{"emoji": m["emoji"], "word": "", "start": a, "end": round(min(b, a + 1.8), 3)}]
    if m.get("cut_range"):
        it.exclude_ranges = [m["cut_range"]]
    if m.get("restyle"):
        it.text_restyles = [{"at": a, **m["restyle"]}]
    it.recognized = [f"at {a:.1f}s: {u}" for u in m.get("understood") or []]
    return it
