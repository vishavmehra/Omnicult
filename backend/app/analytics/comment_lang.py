"""Script and language of a public comment, decided by code from its letters (no model, no network, no dependency).

Script is exact: each letter is placed by its Unicode name. Language is a best effort that is honest about its limit:
a script that belongs to one language here gives that language (Tamil, Malayalam, Bengali, Telugu, Kannada, Gujarati,
Gurmukhi, Odia); Devanagari is Marathi or Hindi when common function words of exactly one of them appear, otherwise it
is not told apart; Latin letters are Hindi written in Latin when Hindi function words outnumber English ones, otherwise
English. Latin-script Tamil, Marathi and the like are therefore read as English, and Bengali script also covers
Assamese. `UNDETERMINED` ("und") means the code did not decide; `NO_LETTERS` ("zxx", ISO 639-2 "no linguistic content") is a
comment of emoji, digits or punctuation only. A comment that mixes a regional script with Latin words,
or Hindi with English words, is `code_mixed`.
"""

import re
import string
import unicodedata

UNDETERMINED = "und"
NO_LETTERS = "zxx"
LANGUAGE_NAMES = {
    "mr": "Marathi", "ta": "Tamil", "ml": "Malayalam", "bn": "Bengali", "en": "English", "hi": "Hindi", "te": "Telugu",
    "kn": "Kannada", "gu": "Gujarati", "pa": "Punjabi", "or": "Odia", UNDETERMINED: "Not told apart", NO_LETTERS: "Emoji or symbols only",
}

_SCRIPT_BY_NAME = {
    "LATIN": "Latn", "DEVANAGARI": "Deva", "TAMIL": "Taml", "MALAYALAM": "Mlym", "BENGALI": "Beng", "TELUGU": "Telu",
    "KANNADA": "Knda", "GUJARATI": "Gujr", "GURMUKHI": "Guru", "ORIYA": "Orya", "ARABIC": "Arab",
}
_LANGUAGE_BY_SCRIPT = {"Taml": "ta", "Mlym": "ml", "Beng": "bn", "Telu": "te", "Knda": "kn", "Gujr": "gu", "Guru": "pa", "Orya": "or"}
COMMON_SCRIPT = "Zyyy"  # ISO 15924 "common": digits, emoji and punctuation only
OTHER_SCRIPT = "Zzzz"  # a script this module does not name

_NOISE = re.compile(r"https?://\S+|www\.\S+|@\S+")
_EDGE = string.punctuation + "।॥…“”‘’—–¡¿"
_HINDI = frozenset("है हैं और नहीं के को में से यह बहुत था थी मैं आप हम क्या भी".split())
_MARATHI = frozenset("आहे आणि नाही मला तुम्ही खूप काय होता होती आम्ही पण आपल्या तुला माझ्या आहेत".split())
_ENGLISH = frozenset(
    "the and of this it you for was my that love best very are not with have what so i just your great nice beautiful "
    "amazing good ad video song music".split())
_HINGLISH = frozenset(
    "hai hain nahi nahin bahut bohot bahot aur kya mera meri tum acha accha achha bhai kyun kyu mujhe hum tha thi ka ki "
    "ke ko se mein yeh ye wala wali sabse dil pyaar lagta lagi".split())


def _script_of_letter(ch: str) -> str:
    return _SCRIPT_BY_NAME.get(unicodedata.name(ch, "").split(" ", 1)[0], OTHER_SCRIPT)


def _words(text: str) -> list[str]:
    return [w for w in (token.strip(_EDGE) for token in text.casefold().split()) if w]


def analyse(text: str) -> tuple[str, str, bool]:
    """(language, script, code_mixed) of one comment. Links and @mentions are ignored."""
    body = _NOISE.sub(" ", unicodedata.normalize("NFC", text))
    letters: dict[str, int] = {}
    for ch in body:
        if ch.isalpha():
            script = _script_of_letter(ch)
            letters[script] = letters.get(script, 0) + 1
    if not letters:
        return NO_LETTERS, COMMON_SCRIPT, False
    latin = letters.get("Latn", 0)
    others = {s: n for s, n in letters.items() if s != "Latn"}
    main = max(others, key=others.get) if others and sum(others.values()) >= latin else "Latn"  # type: ignore[arg-type]
    words = _words(body)
    if main == "Latn":
        hindi, english = sum(w in _HINGLISH for w in words), sum(w in _ENGLISH for w in words)
        if hindi > english:
            return "hi", "Latn", True
        return "en", "Latn", sum(others.values()) >= 2 and latin >= 2
    mixed = latin >= 2 and others[main] >= 2
    if main == "Deva":
        marathi, hindi = sum(w in _MARATHI for w in words), sum(w in _HINDI for w in words)
        return ("mr" if marathi > hindi else "hi" if hindi > marathi else UNDETERMINED), "Deva", mixed
    return _LANGUAGE_BY_SCRIPT.get(main, UNDETERMINED), main, mixed
