"""Hindi speech: Devanagari → Hinglish romanisation (captions, sticker words) and the 'already in your edit' answer."""

import pytest

from cutmind import stickers
from cutmind.hindi import is_hindi, romanize
from cutmind.versions import _already


@pytest.mark.parametrize("dev,roman", [
    ("मेरे पास स्टूडियो में भी है", "mere paas studiyo mein bhi hai"),
    ("कितना बड़ा पेड़ है", "kitna bada ped hai"),
    ("चलिए आज चमत्कार देख लेते हैं", "chalie aj chamatkar dekh lete hain"),
    ("दो रहता है", "do rahta hai"),
    ("समुद्र राम कमरा समझना", "samudra ram kamra samajhna"),
])
def test_romanize(dev, roman):
    assert romanize(dev) == roman


def test_romanized_words_find_stickers():
    assert is_hindi("गुलाब") and not is_hindi("gulab")
    for dev in ("गुलाब", "पेड़", "चाय", "फूल", "पहाड़", "कुत्ता"):
        assert stickers.emoji_for(romanize(dev)), dev


def test_already_in_edit_answer():
    assert _already("captions laga do").startswith("Already in your edit: captions")
