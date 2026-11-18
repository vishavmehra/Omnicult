"""Small text measures shared by the Audience Lab sessions (lab-t3). Pure functions, stdlib only.

`wording_overlap` counts shared content words. It is a wording measure and never a measure of understanding: a
restatement can reuse the words and miss the point, or use other words and keep it.
"""

import re
from collections.abc import Iterable

STOPWORDS = frozenset(
    "a an the and or but of to in on at for with from by as is are was were be been it its this that these those you your we our "
    "i my me they their them he she his her not no so if then than too very can will just about into over".split()
)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def content_words(text: str | None) -> set[str]:
    """Lower-cased words of two letters or more, without stopwords, with a trailing plural 's' folded (sweets, sweet)."""
    words = set()
    for raw in _WORD.findall((text or "").casefold()):
        if len(raw) < 2 or raw in STOPWORDS:
            continue
        words.add(raw[:-1] if len(raw) > 3 and raw.endswith("s") and not raw.endswith("ss") else raw)
    return words


def wording_overlap(a: str | None, b: str | None) -> float | None:
    """Shared content words over the smaller word set, 0 to 1 (None when either side has no content words)."""
    left, right = content_words(a), content_words(b)
    if not left or not right:
        return None
    return round(len(left & right) / min(len(left), len(right)), 4)


def first_seen(labels: Iterable[str]) -> dict[str, str]:
    """Normalised label -> the first spelling seen, so a theme keeps the words a participant used."""
    out: dict[str, str] = {}
    for label in labels:
        key = " ".join(_WORD.findall(label.casefold()))
        if key:
            out.setdefault(key, label.strip())
    return out


def label_key(label: str) -> str:
    return " ".join(_WORD.findall(label.casefold()))
