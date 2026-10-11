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


def _plan(**extra):
    from cutmind.plan import EditPlan

    return EditPlan.model_validate({"clips": [{"source": "c1", "in": 0.0, "out": 5.0, "order": 0}], **extra})


def test_already_in_edit_answer_is_checked_on_the_plan():
    caps = _plan(text=[{"kind": "caption", "text": "hello", "start": 0.0, "end": 1.0}])
    assert _already("captions laga do", caps).startswith("Already in your edit: captions")
    # the opposite: no captions in the edit -> never "already" (it used to re-read the prompt and claim it)
    msg = _already("captions laga do", _plan())
    assert "Already" not in msg and "NOT in the edit: captions" in msg


def test_already_never_claims_a_look_the_edit_does_not_have():
    # the real failure: "purple…" asked violet_authority, the edit had midnight_drift, the message said "already"
    msg = _already("violet authority look lagao", _plan(style="midnight_drift"))
    assert "Already" not in msg and "violet authority look" in msg
    assert _already("violet authority look lagao", _plan(style="violet_authority")).startswith("Already")
