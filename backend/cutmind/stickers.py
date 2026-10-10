"""Word stickers: when someone in a vlog SAYS a thing ("ye gulab dekho", "kitna bada ped hai", "chai pi rahe hain"),
a small animated sticker of it pops up at that moment.

Stickers are colour emoji drawn with the Windows "Segoe UI Emoji" font (or Noto Color Emoji on Linux) through Pillow,
turned into PNGs with a white sticker outline. No download, no image generator: the words come from the transcript
(faster-whisper), the moments from its word timings.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

EMOJI_FONTS = ("C:/Windows/Fonts/seguiemj.ttf", "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
               "/System/Library/Fonts/Apple Color Emoji.ttc")

# spoken word (English / Hindi / Hinglish, singular or plural) → emoji. Kept to things people show in vlogs.
WORDS: dict[str, str] = {
    r"roses?|gulab|flowers?|phool|phul": "\U0001F339", r"sunflowers?|surajmukhi": "\U0001F33B",
    r"trees?|ped|perh|jungle|forest": "\U0001F333", r"palm|nariyal": "\U0001F334", r"leaf|leaves|patta|patte": "\U0001F343",
    r"mountains?|pahad|pahar|hills?": "\u26F0\uFE0F", r"beach|samundar|samudra|sea|ocean|beech": "\U0001F3D6\uFE0F",
    r"waves?|lehar|lehren": "\U0001F30A", r"rain|baarish|barish": "\U0001F327\uFE0F", r"snow|baraf|barf": "\u2744\uFE0F",
    r"sun|suraj|sunny|dhoop": "\u2600\uFE0F", r"sunset|sunrise": "\U0001F305", r"moon|chand|chaand": "\U0001F319",
    r"stars?|taare|tare": "\u2B50", r"rainbow|indradhanush": "\U0001F308", r"fire|aag|bonfire": "\U0001F525",
    r"tea|chai": "\u2615", r"coffee|kaafi": "\u2615", r"pizza": "\U0001F355", r"burger": "\U0001F354",
    r"cake|birthday": "\U0001F382", r"ice ?cream|icecream|kulfi": "\U0001F366", r"biryani|rice|chawal": "\U0001F35B",
    r"momos?|dumplings?": "\U0001F95F", r"samosa|pakode?|pakora": "\U0001F95F", r"mango|aam": "\U0001F96D",
    r"apples?|seb": "\U0001F34E", r"water|paani|pani": "\U0001F4A7", r"food|khana|khaana": "\U0001F37D\uFE0F",
    r"dogs?|kutta|kutte|puppy|doggo": "\U0001F436", r"cats?|billi|kitten": "\U0001F431", r"birds?|chidiya|panchhi": "\U0001F426",
    r"cows?|gaay|gaai": "\U0001F404", r"monkeys?|bandar": "\U0001F412", r"fish|machhli|machli": "\U0001F41F",
    r"butterfly|titli": "\U0001F98B", r"horses?|ghoda|ghode": "\U0001F40E", r"elephants?|haathi|hathi": "\U0001F418",
    r"cars?|gaadi|gadi": "\U0001F697", r"bikes?|scooty|motorcycle": "\U0001F3CD\uFE0F", r"cycle|bicycle": "\U0001F6B2",
    r"bus": "\U0001F68C", r"trains?|rail": "\U0001F686", r"planes?|flight|airport|hawai ?jahaz": "\u2708\uFE0F",
    r"boats?|naav|nav|ship": "\u26F5", r"road ?trip|trip|travel|safar": "\U0001F9F3", r"hotel|room": "\U0001F3E8",
    r"temple|mandir": "\U0001F6D5", r"church": "\u26EA", r"house|ghar|home": "\U0001F3E0", r"city|shehar|sheher": "\U0001F3D9\uFE0F",
    r"phone|mobile": "\U0001F4F1", r"camera": "\U0001F4F7", r"laptop|computer": "\U0001F4BB", r"money|paisa|paise|rupees?": "\U0001F4B0",
    r"gift|tohfa": "\U0001F381", r"books?|kitab|kitaab": "\U0001F4DA", r"music|gaana|song": "\U0001F3B5",
    r"football|soccer": "\u26BD", r"cricket": "\U0001F3CF", r"gym|workout": "\U0001F4AA", r"party": "\U0001F389",
    r"love|pyaar|pyar|dil": "\u2764\uFE0F", r"friends?|dost|dosto|yaar": "\U0001F91D", r"family|parivaar|mummy|papa": "\U0001F46A",
    r"happy|khush|mazaa|maza": "\U0001F604", r"sad|dukhi": "\U0001F622", r"wow|amazing|awesome|zabardast": "\U0001F929",
    r"sleep|neend|sona": "\U0001F634", r"time|samay|waqt": "\u23F0", r"shopping|market|bazaar": "\U0001F6CD\uFE0F",
}
_RX = [(re.compile(rf"^(?:{k})$"), v) for k, v in WORDS.items()]

MAX_STICKERS = 6
MIN_GAP = 1.2      # s between two stickers (they alternate corners; closer than this is a sticker storm)
SHOW_FOR = 1.8     # s a sticker stays


def emoji_for(word: str) -> str | None:
    w = re.sub(r"[^\w ]", "", word.lower()).strip()
    return next((e for rx, e in _RX if rx.match(w)), None)


def pick(words: list[tuple[str, float, float]], total: float, max_n: int = MAX_STICKERS) -> list[dict[str, Any]]:
    """(word, start, end) in OUTPUT seconds → stickers [{emoji, word, start, end}], spread out, each thing once."""
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for text, a, _b in sorted(words, key=lambda w: w[1]):
        e = emoji_for(text)
        if not e or e in used or a > total - 0.6:
            continue
        if out and a - out[-1]["start"] < MIN_GAP:
            continue
        used.add(e)
        out.append({"emoji": e, "word": text, "start": round(a, 3), "end": round(min(total, a + SHOW_FOR), 3)})
        if len(out) >= max_n:
            break
    return out


@lru_cache(maxsize=1)
def _font_path() -> str | None:
    return next((f for f in EMOJI_FONTS if Path(f).exists()), None)


def available() -> bool:
    return _font_path() is not None


def render_png(emoji: str, out: Path, size: int = 256) -> Path:
    """The emoji as a sticker PNG: transparent, a white outline and a soft shadow (readable on any picture)."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

    if out.exists():
        return out
    path = _font_path()
    if path is None:
        raise RuntimeError("no colour emoji font on this machine")
    font = ImageFont.truetype(path, 200)
    canvas = Image.new("RGBA", (420, 420), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((100, 100), emoji, font=font, embedded_color=True)
    box = canvas.getbbox()
    glyph = canvas.crop(box) if box else canvas
    pad = 16
    g = Image.new("RGBA", (glyph.width + 2 * pad, glyph.height + 2 * pad), (0, 0, 0, 0))
    g.alpha_composite(glyph, (pad, pad))
    alpha = g.getchannel("A")
    ring = alpha.filter(ImageFilter.MaxFilter(17))  # white sticker border
    shadow = ring.filter(ImageFilter.GaussianBlur(6)).point(lambda v: int(v * 0.45))
    sticker = Image.new("RGBA", g.size, (0, 0, 0, 0))
    sh = Image.new("RGBA", g.size, (0, 0, 0, 255))
    sh.putalpha(ImageChops.offset(shadow, 0, 5))
    sticker.alpha_composite(sh)
    white = Image.new("RGBA", g.size, (255, 255, 255, 255))
    white.putalpha(ring)
    sticker.alpha_composite(white)
    sticker.alpha_composite(g)
    sticker.thumbnail((size, size), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    sticker.save(out)
    return out
