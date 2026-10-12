"""tools/b_speech.py: sentences, keyword cards and the comment call-to-action from spoken words (any speech)."""

from __future__ import annotations

from cutmind.tools.b_speech import KEY_GAP, W, cta_word, keywords, sentences
from cutmind.tools.parse import parse, strip_handles


def words(text: str, step: float = 0.4, pause_after: dict[int, float] | None = None) -> list[W]:
    out, t = [], 0.0
    for i, x in enumerate(text.split()):
        out.append(W(x, round(t, 3), round(t + step * 0.8, 3)))
        t += step + (pause_after or {}).get(i, 0.0)
    return out


def test_sentences_split_on_full_stops_and_pauses():
    ws = words("hello friends welcome back. today we go to the mountains and then the lake", pause_after={9: 0.9})
    ss = sentences(ws)
    assert [" ".join(w.text for w in s) for s in ss][:2] == ["hello friends welcome back.", "today we go to the mountains"]
    assert len(ss) == 3


def test_keywords_are_content_words_spaced_out_and_never_stop_words():
    text = ("so this is the future of video editing and the quality is amazing every layer every keyframe is editable "
            "and the timeline is yours you can change the animations whenever you want to")
    ws = words(text, step=0.45)
    keys = keywords(ws, ws[-1].end + 1)
    assert keys and all(k[2].split()[0].lower() not in ("the", "and", "is", "so", "you") for k in keys)
    starts = [k[0] for k in keys]
    assert all(b - a >= KEY_GAP - 1e-6 for a, b in zip(starts, starts[1:]))
    said = set(text.upper().split())
    assert all(set(k[2].split()) <= said for k in keys)  # only words that were said
    assert all(k[2] == k[2].upper() for k in keys)


def test_cta_finds_the_comment_word_in_english_and_hinglish():
    pad = "filler " * 20
    for said, want in [("type motion in the comments and I'll send you the link", "MOTION"),
                       ("comment karo REEL aur main link bhejunga", "REEL"),
                       ("comment below the word GUIDE and I'll DM you", "GUIDE"),
                       ("GUIDE comments me likho", "GUIDE")]:
        got = cta_word(words(pad + said))
        assert got is not None and got[1] == want, (said, got)
    assert cta_word(words(pad + "thanks for watching see you next time")) is None


def test_handle_is_a_name_not_an_instruction():
    p, hs = strip_handles("jo bol raha hu wo screen pe aaye, handle @cut.mind_23")
    assert hs == ["cut.mind_23"] and "@" not in p
    calls = parse("jo bol raha hu wo screen pe aaye @cutmind")["calls"]
    assert calls and calls[0]["id"] == "talking_head_reel" and calls[0]["params"].get("handle") == "cutmind"
