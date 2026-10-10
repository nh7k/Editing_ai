"""E. Text and captions — captions from speech, karaoke, caption style, title card, lower third, text, typewriter
/ pop / neon / slide animations, logo watermark, progress bar.

Text is drawn by libass (HarfBuzz shaping, so Devanagari conjuncts and matras join correctly) with the project's
OFL fonts (Hind / Kalam for Hindi). Captions are timed from the transcript's words on the current cut.
"""

from __future__ import annotations

import re
from typing import Any

from ..plan import EditPlan, TextItem, TextStyle
from ..text_styles import TEXT_PRESETS, apply_look
from .engine import ToolCtx, tool
from .timeline import ToolError
from .timewin import When

DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _font_for(text: str, font: str | None) -> str | None:
    """Hindi text needs a font with Devanagari glyphs (Hind) — Poppins / Anton would show boxes."""
    if DEVANAGARI.search(text) and font not in ("hind", "kalam"):
        return "hind"
    return font


def _window(plan: EditPlan, when: When, default: tuple[float, float] | None = None) -> tuple[float, float]:
    total = plan.total_duration()
    if when.whole:
        return default or (0.0, round(total, 3))
    a, b = when.windows[0]
    return round(a, 3), round(min(b, total), 3)


def _add_text(plan: EditPlan, item: TextItem) -> EditPlan:
    data = plan.to_json()
    data["text"].append(item.model_dump())
    return EditPlan.model_validate(data)


def _captions(plan: EditPlan, ctx: ToolCtx, p: dict[str, Any]) -> list[TextItem]:
    from ..agents.effects import caption_items

    if ctx.analysis is None:
        raise ToolError("captions need speech-to-text, which is not available here")
    an = ctx.analysis()
    words = {cid: ca.words for cid, ca in an.clips.items()}
    if not any(words.values()):
        raise ToolError("no speech found in this video, so there is nothing to caption")
    items = caption_items(plan.timeline(), words, p.get("position", "bottom"), int(p.get("size", 50)),
                          max_words=int(p.get("words_per_line", 0) or 0))
    if not items:
        raise ToolError("none of the spoken words are in the current cut")
    return items


@tool("auto_captions")
def auto_captions(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    items = _captions(plan, ctx, p)
    data = plan.to_json()
    data["text"] = [t for t in data["text"] if t["kind"] != "caption"]
    for it in items:
        st = apply_look(it.style, p["style"]) if p.get("style") else it.style
        st = st.model_copy(update={"font": _font_for(it.text, st.font)})
        data["text"].append(it.model_copy(update={"style": st}).model_dump())
    ctx.notes.append(f"{len(items)} captions from the speech ({p.get('style') or 'classic'} style, "
                     f"{p['position']}, ≤ {p['words_per_line'] or 'auto'} words a line)")
    return EditPlan.model_validate(data)


@tool("karaoke_captions")
def karaoke_captions(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    if not any(t.kind == "caption" for t in plan.text):
        plan = auto_captions(plan, {"style": "bold_pop", "position": "center", "words_per_line": 4, "size": 60}, when, ctx)
    data = plan.to_json()
    n = 0
    for t in data["text"]:
        if t["kind"] == "caption":
            st = TextStyle.model_validate(t["style"]).model_copy(update={"animation": "karaoke", "highlight": p["color"],
                                                                        "color": "#FFFFFF"})
            t["style"] = st.model_dump()
            n += 1
    ctx.notes.append(f"{n} captions: each word lights up {p['color']} as it is said")
    return EditPlan.model_validate(data)


@tool("caption_style")
def caption_style(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    kinds = ("caption",)
    if not any(t.kind == "caption" for t in plan.text):
        if any(t.kind in ("text", "title") for t in plan.text):
            kinds = ("text", "title")  # "text ka color pink karo": the edit's own texts
        else:  # "hormozi style captions" on a fresh edit: make them
            plan = auto_captions(plan, {"style": None, "position": p.get("position") or "bottom", "words_per_line": 4,
                                        "size": 50}, when, ctx)
    data = plan.to_json()
    n = 0
    for t in data["text"]:
        if t["kind"] not in kinds:
            continue
        st = TextStyle.model_validate(t["style"])
        if p.get("preset"):
            st = apply_look(st, p["preset"])
        upd: dict[str, Any] = {}
        if p.get("color"):
            upd["color"] = p["color"]
        if p.get("size"):
            upd["size"] = int(p["size"])
        if p.get("position"):
            upd["position"] = p["position"]
        if p.get("font"):
            upd["font"] = p["font"]
        st = st.model_copy(update=upd)
        st = st.model_copy(update={"font": _font_for(t["text"], st.font)})
        t["style"] = st.model_dump()
        n += 1
    what = ", ".join(f"{k} {v}" for k, v in p.items() if v)
    ctx.notes.append(f"{n} captions restyled: {what}")
    return EditPlan.model_validate(data)


@tool("title_card")
def title_card(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    """A full-screen title on its own background, at the start (or `at` seconds): the video waits for it."""
    from .b_cutting import intro_outro

    at = float(p["at"])
    if at <= 0.05:
        return intro_outro(plan, {"text": p["text"], "outro_text": p["text"], "which": "intro",
                                  "duration": p["duration"], "background": p["background"]}, when, ctx)
    from . import generated
    from .timeline import split_at

    total = plan.total_duration()
    if at >= total - 0.05:
        return intro_outro(plan, {"text": p["text"], "outro_text": p["text"], "which": "outro",
                                  "duration": p["duration"], "background": p["background"]}, when, ctx)
    plan = split_at(plan, at)
    tl = plan.timeline()
    k = next(e.index for e in tl if abs(e.start - at) <= 0.06)
    w, h = plan.canvas.size
    d = float(p["duration"])
    cid, path = generated.card(ctx.gen_dir, w, h, d, p["background"], plan.canvas.fps)
    ctx.sources[cid] = path
    data = plan.to_json()
    for c in data["clips"]:
        if c["order"] >= k:
            c["order"] += 1
    for x in data["effects"]:
        if x["target"] >= k:
            x["target"] += 1
    for t in data["transitions"]:
        if t["after"] >= k:
            t["after"] += 1
    for x in data.get("audio_edits", []):
        if x["after"] >= k:
            x["after"] += 1
    for key in ("text", "stickers", "graphics", "overlays"):
        for it in data.get(key, []):
            if it["start"] >= at - 1e-3:
                it["start"], it["end"] = round(it["start"] + d, 3), round(it["end"] + d, 3)
            elif it["end"] > at:
                it["end"] = round(it["end"] + d, 3)
    data["clips"].append({"source": cid, "in": 0.0, "out": d, "order": k})
    data["text"].append({"kind": "title", "text": p["text"], "start": round(at + 0.1, 3), "end": round(at + d - 0.1, 3),
                         "style": {"position": "center", "size": 88, "box_color": None, "animation": "fade",
                                   "font": _font_for(p["text"], None)}})
    ctx.notes.append(f"title card '{p['text']}' at {at:g}s ({d:g}s)")
    return EditPlan.model_validate(data)


@tool("lower_third")
def lower_third(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    a, b = _window(plan, when, (0.5, min(plan.total_duration(), 4.5)))
    text = p["text"] + (f"\n{p['subtitle']}" if p.get("subtitle") else "")
    st = apply_look(TextStyle(position="bottom_left", size=44, animation="fly_left", margin=0.08), "name_tag")
    st = st.model_copy(update={"font": _font_for(text, st.font)})
    ctx.notes.append(f"name strap '{p['text']}' bottom left, {a:.1f}-{b:.1f}s")
    return _add_text(plan, TextItem(kind="text", text=text[:200], start=a, end=b, style=st))


ANIM = {"typewriter": "typewriter", "pop": "pop", "neon": "glow_pulse",
        "left": "fly_left", "right": "fly_right", "up": "slide_up", "down": "drop_in"}


def _text_with(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx, anim: str, preset: str | None,
               what: str, color: str | None = None) -> EditPlan:
    """Add `text` with an animation; with no text, give the animation to the edit's own texts (not captions)."""
    if p.get("text"):
        a, b = _window(plan, when)
        st = TextStyle(position=p.get("position") or "center", size=int(p.get("size") or 72), box_color=None,
                       animation=anim)  # type: ignore[arg-type]
        if preset:
            st = apply_look(st, preset)
        if color:
            st = st.model_copy(update={"color": color})
        st = st.model_copy(update={"font": _font_for(p["text"], st.font)})
        ctx.notes.append(f"'{p['text']}' {what} ({a:.1f}-{b:.1f}s)")
        return _add_text(plan, TextItem(kind="text", text=p["text"], start=a, end=b, style=st))
    data = plan.to_json()
    n = 0
    for t in data["text"]:
        if t["kind"] in ("text", "title"):
            st = TextStyle.model_validate(t["style"]).model_copy(update={"animation": anim})
            if preset:
                st = apply_look(st, preset)
            if color:
                st = st.model_copy(update={"color": color})
            t["style"] = st.model_dump()
            n += 1
    if not n:
        raise ToolError(f"there is no text to animate — say the text in quotes, e.g. '{what} \"Goa trip\"'")
    ctx.notes.append(f"{n} text(s) now {what}")
    return EditPlan.model_validate(data)


@tool("text_overlay")
def text_overlay(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    if not p.get("text"):
        raise ToolError("what should it say? Put the words in quotes, e.g. 'likho \"Goa Trip\"'")
    a, b = _window(plan, when)
    st = TextStyle(position=p["position"], size=int(p["size"]), box_color="#000000" if p["box"] else None)
    if p.get("color"):
        st = st.model_copy(update={"color": p["color"]})
    st = st.model_copy(update={"font": _font_for(p["text"], st.font)})
    ctx.notes.append(f"text '{p['text']}' {p['position']} ({a:.1f}-{b:.1f}s)")
    return _add_text(plan, TextItem(kind="text", text=p["text"], start=a, end=b, style=st))


@tool("text_typewriter")
def text_typewriter(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _text_with(plan, p, when, ctx, "typewriter", "typewriter_font" if not p.get("text") or not DEVANAGARI.search(p["text"]) else None,
                      "typed out letter by letter")


@tool("text_pop_in")
def text_pop_in(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _text_with(plan, p, when, ctx, "pop", "bold_pop", "popping in")


def neon_style(st: TextStyle, color: str) -> TextStyle:
    """A neon tube: a near-white core (25 % of the colour), the colour as a thick outline and a wide glow — a
    coloured fill alone vanished on a colourful background (measured in the render test)."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    core = "#{:02X}{:02X}{:02X}".format(*(int(255 * 0.75 + c * 0.25) for c in (r, g, b)))
    return apply_look(st, "neon").model_copy(update={"color": core, "outline_color": color, "outline": 4.0,
                                                     "glow": 10.0, "box_color": None, "font": "poppins_black"})


@tool("text_glow_neon")
def text_glow_neon(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    if p.get("text"):
        a, b = _window(plan, when)
        st = neon_style(TextStyle(position=p.get("position") or "center", size=int(p.get("size") or 72),
                                  animation="glow_pulse"), p["color"])
        st = st.model_copy(update={"font": _font_for(p["text"], st.font)})
        ctx.notes.append(f"'{p['text']}' glowing neon {p['color']} ({a:.1f}-{b:.1f}s)")
        return _add_text(plan, TextItem(kind="text", text=p["text"], start=a, end=b, style=st))
    data = plan.to_json()
    n = 0
    for t in data["text"]:
        if t["kind"] in ("text", "title"):
            t["style"] = neon_style(TextStyle.model_validate(t["style"]), p["color"]).model_copy(
                update={"animation": "glow_pulse"}).model_dump()
            n += 1
    if not n:
        raise ToolError("there is no text to make neon — put the words in quotes")
    ctx.notes.append(f"{n} text(s) now glowing neon {p['color']}")
    return EditPlan.model_validate(data)


@tool("text_slide")
def text_slide(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    return _text_with(plan, p, when, ctx, ANIM[p["direction"]], None, f"sliding in from the {p['direction']}")


@tool("watermark_logo")
def watermark_logo(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    """A logo image (uploaded to the project) in a corner at an opacity — or, with no logo, the text in quotes."""
    corner = {"top_left": (0.03, 0.03), "top_right": (0.82, 0.03), "bottom_left": (0.03, 0.85),
              "bottom_right": (0.82, 0.85)}[p["position"]]
    data = plan.to_json()
    total = round(plan.total_duration(), 3)
    if ctx.logo is not None and ctx.logo.exists():
        size = float(p["size"])
        W, H = plan.canvas.size
        x = corner[0] if corner[0] < 0.5 else 1 - size - 0.03
        hh = size * W / H
        y = corner[1] if corner[1] < 0.5 else 1 - hh - 0.03
        data["graphics"].append({"kind": "image", "source": str(ctx.logo), "start": 0.0, "end": total, "x": x, "y": y,
                                 "w": size, "h": hh, "opacity": float(p["opacity"])})
        ctx.notes.append(f"logo {p['position'].replace('_', ' ')}, {p['opacity']:.0%} opacity")
    elif p.get("text"):
        pos = "top_right" if p["position"].startswith("top") else "bottom_right"
        data["text"] = [t for t in data["text"] if t["kind"] != "watermark"]
        data["text"].append({"kind": "watermark", "text": p["text"], "start": 0.0, "end": total,
                             "style": {"position": pos, "size": 30, "box_color": None, "color": "#FFFFFF"}})
        ctx.notes.append(f"text watermark '{p['text']}' {pos.replace('_', ' ')}")
    else:
        raise ToolError("upload your logo (PNG) to the project, or give the watermark text in quotes")
    return EditPlan.model_validate(data)


@tool("progress_bar")
def progress_bar(plan: EditPlan, p: dict[str, Any], when: When, ctx: ToolCtx) -> EditPlan:
    a, b = _window(plan, when)
    data = plan.to_json()
    data["graphics"] = [g for g in data["graphics"] if g["kind"] != "progress"]
    data["graphics"].append({"kind": "progress", "start": a, "end": b, "x": 0.0, "y": 0.0 if p["position"] == "top" else 1.0,
                             "w": 1.0, "h": 0.02, "color": p["color"], "strength": float(p["thickness"])})
    ctx.notes.append(f"progress bar at the {p['position']} ({p['color']})")
    return EditPlan.model_validate(data)


def preset_names() -> list[str]:
    return list(TEXT_PRESETS)
