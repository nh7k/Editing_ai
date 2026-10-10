"""Fonts and text-style presets (CapCut-style "text templates").

Fonts are open-source (SIL OFL / Apache-2.0, from github.com/google/fonts) and ship in backend/assets/fonts, so
renders look the same on every server; libass is pointed at that folder. Free for commercial use.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# id → (family name libass looks up, bold, file, look)
FONTS: dict[str, tuple[str, bool, str, str]] = {
    "arial": ("Arial", True, "", "system default"),
    "anton": ("Anton", False, "Anton-Regular.ttf", "tall condensed headline"),
    "bebas": ("Bebas Neue", False, "BebasNeue-Regular.ttf", "clean all-caps"),
    "bangers": ("Bangers", False, "Bangers-Regular.ttf", "comic book"),
    "marker": ("Permanent Marker", False, "PermanentMarker-Regular.ttf", "hand-drawn marker"),
    "pacifico": ("Pacifico", False, "Pacifico-Regular.ttf", "retro script"),
    "lobster": ("Lobster", False, "Lobster-Regular.ttf", "bold script"),
    "poppins": ("Poppins", True, "Poppins-Bold.ttf", "modern bold sans"),
    "poppins_black": ("Poppins ExtraBold", False, "Poppins-ExtraBold.ttf", "heavy sans (Hormozi-style captions)"),
    "righteous": ("Righteous", False, "Righteous-Regular.ttf", "rounded retro"),
    "monoton": ("Monoton", False, "Monoton-Regular.ttf", "neon tube lines"),
    "pixel": ("Press Start 2P", False, "PressStart2P-Regular.ttf", "8-bit gaming"),
    "army": ("Black Ops One", False, "BlackOpsOne-Regular.ttf", "stencil / action"),
    "kalam": ("Kalam", True, "Kalam-Bold.ttf", "handwriting (Hindi + English)"),
    "hind": ("Hind", True, "Hind-Bold.ttf", "clean Hindi + English"),
    "luckiest": ("Luckiest Guy", False, "LuckiestGuy-Regular.ttf", "playful cartoon"),
    "abril": ("Abril Fatface", False, "AbrilFatface-Regular.ttf", "elegant fashion serif"),
    "typewriter": ("Special Elite", False, "SpecialElite-Regular.ttf", "old typewriter"),
    "vibes": ("Great Vibes", False, "GreatVibes-Regular.ttf", "wedding calligraphy"),
}


@dataclass(frozen=True)
class TextPreset:
    name: str
    font: str
    color: str
    outline_color: str | None   # None = no outline
    outline: float              # px at 1080
    shadow: float
    glow: float                 # blur radius
    box_color: str | None
    uppercase: bool
    keywords: tuple[str, ...]


TEXT_PRESETS: dict[str, TextPreset] = {
    "classic": TextPreset("Classic box", "poppins", "#FFFFFF", None, 0, 0, 0, "#7C5CFF", False, (r"classic (text|captions?)",)),
    "hormozi": TextPreset("Hormozi", "poppins_black", "#FFFFFF", "#000000", 7, 0, 0, None, True,
                          (r"hormozi", r"podcast (style )?captions?", r"alex hormozi")),
    "bold_pop": TextPreset("Bold Pop", "poppins_black", "#FFE600", "#000000", 6, 3, 0, None, True,
                           (r"bold (yellow )?(text|captions?)", r"bold pop")),
    "neon": TextPreset("Neon Glow", "monoton", "#22D3EE", "#7C5CFF", 3, 0, 6, None, False, (r"neon (text|captions?|title)", r"glowing text")),
    "minimal": TextPreset("Minimal", "bebas", "#FFFFFF", None, 0, 2, 0, None, True, (r"minimal (text|captions?)", r"clean (text|captions?)")),
    "comic": TextPreset("Comic", "bangers", "#FFFFFF", "#E11D48", 5, 4, 0, None, True, (r"comic (text|captions?|style)", r"cartoon text")),
    "handwritten": TextPreset("Handwritten", "marker", "#FFFFFF", "#000000", 2, 2, 0, None, False,
                              (r"hand.?written", r"marker (text|font)", r"handwriting")),
    "retro": TextPreset("Retro", "righteous", "#FB923C", "#7C2D12", 4, 4, 0, None, False, (r"retro (text|captions?|font)",)),
    "cinema": TextPreset("Cinema", "abril", "#F5F5F4", None, 0, 3, 0, None, False, (r"cinema(tic)? (text|title|font)", r"elegant (text|title)")),
    "gaming": TextPreset("Gaming", "pixel", "#4ADE80", "#000000", 4, 0, 0, None, True,
                         (r"gaming (text|font|captions?)", r"pixel (text|font)", r"8.?bit")),
    "action": TextPreset("Action", "army", "#FACC15", "#111827", 4, 3, 0, None, True, (r"action (text|title)", r"army (text|font)", r"stencil")),
    "love": TextPreset("Love", "pacifico", "#F9A8D4", "#831843", 3, 2, 2, None, False, (r"love (text|font)", r"romantic (text|font)", r"pyaar")),
    "wedding": TextPreset("Wedding", "vibes", "#FDE68A", "#78350F", 2, 2, 2, None, False, (r"wedding (text|font|title)", r"shaadi", r"calligraphy")),
    "news": TextPreset("News", "poppins", "#FFFFFF", None, 0, 0, 0, "#DC2626", True, (r"news (text|style|ticker)", r"breaking news")),
    "typewriter_font": TextPreset("Typewriter", "typewriter", "#F5F5F4", "#000000", 2, 0, 0, None, False,
                                  (r"typewriter font", r"old (letter|typewriter) (text|font)")),
    "desi": TextPreset("Desi Bold", "hind", "#FFFFFF", "#B91C1C", 5, 3, 0, None, False, (r"hindi (text|font|captions?)", r"desi (text|font)")),
    "cartoon": TextPreset("Cartoon", "luckiest", "#FFFFFF", "#2563EB", 6, 4, 0, None, True, (r"playful (text|font)", r"kids? (text|font)")),
    "glass": TextPreset("Liquid Glass", "poppins_black", "#D6F1FF", "#1E3A8A", 6, 7, 1, None, True,
                        (r"liquid glass", r"glass (text|style)", r"glassy")),
    # lyric-poster reels: huge condensed capitals, each word a new colour (red / black / yellow), no box
    "poster": TextPreset("Lyric Poster", "anton", "#E10600", "#FFFFFF", 2, 2, 0, None, True,
                         (r"poster (text|style|words?|font)", r"lyric poster", r"(bade|bada|big)\s+bold\s+(words?|shabd|text)")),
    "name_tag": TextPreset("Name tag", "poppins", "#111827", None, 0, 0, 0, "#FACC15", False, (r"name ?tag", r"label")),
}

COLOR_WORDS: dict[str, str] = {
    "white": "#FFFFFF", "safed": "#FFFFFF", "black": "#000000", "kala": "#000000", "kaala": "#000000",
    "kaale": "#000000", "kale": "#000000", "yellow": "#FFE600", "peela": "#FFE600",
    "red": "#EF4444", "laal": "#EF4444", "lal": "#EF4444", "blue": "#3B82F6", "neela": "#3B82F6", "green": "#22C55E",
    "hara": "#22C55E", "pink": "#F472B6", "gulabi": "#F472B6", "orange": "#FB923C", "purple": "#A855F7", "cyan": "#22D3EE",
    "gold": "#FACC15", "sunehra": "#FACC15",
}


# "poster": the colour of the n-th word (the reference reels alternate red, black and yellow)
POSTER_COLORS = (("#E10600", "#FFFFFF"), ("#111111", "#FFFFFF"), ("#FFE600", "#111111"))


def apply_look(style, preset_id: str | None = None, color: str | None = None, animation: str | None = None):  # noqa: ANN001, ANN201
    """A copy of a plan TextStyle with a preset (font, colours, outline, shadow, glow, case) and/or colour applied."""
    upd: dict[str, object] = {}
    pr = TEXT_PRESETS.get(preset_id or "")
    if pr is not None:
        upd.update(font=pr.font, color=pr.color, outline_color=pr.outline_color, outline=pr.outline or None,
                   shadow=pr.shadow, glow=pr.glow, box_color=pr.box_color, uppercase=pr.uppercase, preset=preset_id)
    if color:
        upd["color"] = color
        if pr is None and style.box_color:  # a coloured word reads better with an outline than inside a box
            upd.update(box_color=None, outline_color="#000000", outline=4.0)
    if animation and animation != "none":
        upd["animation"] = animation
    return style.model_copy(update=upd)


def font_family(font_id: str | None) -> tuple[str, bool]:
    fam, bold, _f, _d = FONTS.get(font_id or "arial", FONTS["arial"])
    return fam, bold


def catalog() -> dict[str, list[dict[str, object]]]:
    return {
        "fonts": [{"id": k, "family": v[0], "look": v[3]} for k, v in FONTS.items()],
        "presets": [{"id": k, "name": p.name, "font": p.font, "color": p.color, "outline_color": p.outline_color,
                     "box_color": p.box_color, "uppercase": p.uppercase} for k, p in TEXT_PRESETS.items()],
        "colors": [{"word": k, "hex": v} for k, v in COLOR_WORDS.items()],
    }
