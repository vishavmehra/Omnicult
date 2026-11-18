"""Code checks for Creative Studio: Unicode script check, Brand Glossary term checks, and Tone Dial directives.

Everything a model says about its own output is checked here, never trusted: the regional copy must use the expected
script, protected terms must survive in the copy and in the English back-translation, prohibited alternatives must not
appear in either, and the tone dials become explicit prompt directives (so a dial really changes the generation call).
The flat brand-kit term lists follow a case-insensitive rule.
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# Unicode blocks of the scripts used in the supported markets (ISO 15924 code -> code point ranges). Letters outside
# every block count as "Zzzz" (other), which is never accepted next to an expected Indic script.
SCRIPT_RANGES: dict[str, tuple[tuple[int, int], ...]] = {
    "Latn": ((0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F), (0x1E00, 0x1EFF)),
    "Deva": ((0x0900, 0x097F), (0xA8E0, 0xA8FF)),
    "Beng": ((0x0980, 0x09FF),),
    "Guru": ((0x0A00, 0x0A7F),),
    "Gujr": ((0x0A80, 0x0AFF),),
    "Orya": ((0x0B00, 0x0B7F),),
    "Taml": ((0x0B80, 0x0BFF),),
    "Telu": ((0x0C00, 0x0C7F),),
    "Knda": ((0x0C80, 0x0CFF),),
    "Mlym": ((0x0D00, 0x0D7F),),
    "Arab": ((0x0600, 0x06FF), (0x0750, 0x077F)),
}
OTHER = "Zzzz"
DEFAULT_MIN_SHARE = 0.5


def script_of(char: str) -> str | None:
    """The script of a letter or combining mark, `Zzzz` for a letter of an unlisted script, None for anything else
    (digits, punctuation, spaces, joiners)."""
    if unicodedata.category(char)[0] not in "LM":
        return None
    point = ord(char)
    for script, ranges in SCRIPT_RANGES.items():
        if any(low <= point <= high for low, high in ranges):
            return script
    return None if 0x0300 <= point <= 0x036F else OTHER  # combining diacritics ride on Latin letters


def min_share_for(code_mixing: int) -> float:
    """Share of letters that must be in the expected script. Pure language needs more; heavy code-mixing allows more
    English (a Tanglish line is mostly Latin letters by design)."""
    return round(max(0.2, 0.6 - 0.4 * code_mixing / 100), 2)


def strip_terms(text: str, terms: Iterable[str]) -> tuple[str, bool]:
    """`text` without any occurrence of the terms (case-insensitive), and whether something was removed."""
    removed = False
    for term in sorted({t for t in terms if t}, key=len, reverse=True):
        text, count = re.subn(re.escape(term), " ", text, flags=re.IGNORECASE)
        removed = removed or count > 0
    return text, removed


def script_check(text: str, expected: str, *, preserved: Iterable[str] = (), min_share: float = DEFAULT_MIN_SHARE) -> dict[str, Any]:
    """Unicode-block check. ok needs: the expected script present, no letters of any other script except Latin, and the
    expected script at least `min_share` of all letters (Latin is allowed for brand terms and code-mixing)."""
    stripped, removed_terms = strip_terms(text, preserved)
    counts: dict[str, int] = {}
    for char in stripped:
        script = script_of(char)
        if script is not None:
            counts[script] = counts.get(script, 0) + 1
    total = sum(counts.values())
    shares = {s: round(n / total, 3) for s, n in sorted(counts.items())} if total else {}
    foreign = sorted(s for s in counts if s not in (expected, "Latn"))
    dominant = max(counts, key=lambda s: counts[s]) if counts else None
    if total == 0:
        ok, message = removed_terms, ("Only preserved terms; no other letters to check." if removed_terms else "No letters to check.")
    elif foreign:
        ok, message = False, f"Letters of another script appear: {', '.join(foreign)}; expected {expected}."
    elif counts.get(expected, 0) == 0:
        ok, message = False, f"No {expected} letters; the copy is written in {dominant}."
    elif shares.get(expected, 0.0) < min_share:
        ok, message = False, f"{expected} is {shares.get(expected, 0.0):.0%} of the letters; at least {min_share:.0%} is needed."
    else:
        ok, message = True, f"Written in {expected} ({shares.get(expected, 0.0):.0%} of the letters)."
    return {"expected_script": expected, "ok": ok, "dominant_script": dominant, "shares": shares, "foreign_scripts": foreign,
            "min_share": min_share, "message": message}


# --- Brand Glossary --------------------------------------------------------------------------


def _has(text: str, term: str) -> bool:
    return term.casefold() in text.casefold()


def applicable_entries(entries: Sequence[Mapping[str, Any]], language: str | None) -> list[Mapping[str, Any]]:
    """Glossary entries for a language: its own, plus the `*` (every language) entries."""
    return [e for e in entries if e["language"] in ("*", language)]


def term_checks(
    source: str, copy: str, back: str | None, entries: Sequence[Mapping[str, Any]], *, language: str | None,
    protected: Iterable[str] = (), prohibited: Iterable[str] = (),
) -> dict[str, Any]:
    """Protected and prohibited term checks on the regional copy and the English back-translation (`back` None = skip).

    A protected or never-translate term that appears in the source must appear in the copy as its brand-approved
    spelling (else as written) and in the back-translation as written. A prohibited alternative must appear in neither.
    `protected` and `prohibited` are the brand kit's flat lists (Latin terms kept as written). An entry for the target
    language overrides the `*` entry for the same term.
    """
    scoped = applicable_entries(entries, language)
    effective: dict[str, Mapping[str, Any]] = {}
    for entry in sorted(scoped, key=lambda e: e["language"] == "*"):  # specific entries first (False sorts before True)
        effective.setdefault(entry["term"].casefold(), entry)
    required: dict[str, str] = {}  # term as written -> the form the copy must contain
    for entry in effective.values():
        if (entry["protected"] or entry["never_translate"]) and _has(source, entry["term"]):
            required[entry["term"]] = entry.get("approved_spelling") or entry["term"]
    folded = {t.casefold() for t in required}
    for term in protected:
        if term.casefold() not in folded and _has(source, term):
            required[term] = term
    missing_copy = [t for t, form in required.items() if not _has(copy, form)]
    missing_back = [t for t in required if back is not None and not _has(back, t)]
    banned = list(dict.fromkeys([alt for e in scoped for alt in e["prohibited_alternatives"]] + list(prohibited)))
    preferred_missing = [
        e["term"] for e in effective.values()
        if e.get("preferred_translation") and not (e["protected"] or e["never_translate"])
        and _has(source, e["term"]) and not _has(copy, e["preferred_translation"])
    ]
    return {
        "protected_preserved": not missing_copy and not missing_back,
        "missing_in_copy": missing_copy,
        "missing_in_back_translation": missing_back,
        "prohibited_in_copy": [b for b in banned if _has(copy, b)],
        "prohibited_in_back_translation": [b for b in banned if back is not None and _has(back, b)],
        "preferred_translation_missing": preferred_missing,
        "preserved_terms": [form for t, form in required.items() if _has(copy, form)],
    }


def term_problems(checks: Mapping[str, Any]) -> list[str]:
    """Blocking problems, in words, from `term_checks`."""
    problems = []
    if checks["missing_in_copy"]:
        problems.append("Protected term missing from the regional copy: " + ", ".join(checks["missing_in_copy"]) + ".")
    if checks["missing_in_back_translation"]:
        problems.append("Protected term altered in the back-translation: " + ", ".join(checks["missing_in_back_translation"]) + ".")
    if checks["prohibited_in_copy"]:
        problems.append("Prohibited term in the regional copy: " + ", ".join(checks["prohibited_in_copy"]) + ".")
    if checks["prohibited_in_back_translation"]:
        problems.append("Prohibited term in the back-translation: " + ", ".join(checks["prohibited_in_back_translation"]) + ".")
    return problems


# --- Tone Dials ---------------------------------------------------------------------------------

# dial -> (what a low value asks for, what a high value asks for). 0-30 low, 31-69 neutral, 70-100 high.
DIAL_TEXT: dict[str, tuple[str, str]] = {
    "formality": ("casual, everyday register with informal pronouns and verb forms", "formal, respectful register with honorific forms"),
    "code_mixing": ("pure target language; avoid English words except protected terms", "natural code-mixing: keep common English words and phrases as speakers do"),
    "urban_rural": ("rural voice: village and farm references, plain local vocabulary", "urban voice: city life, modern and cosmopolitan vocabulary"),
    "playfulness": ("serious, sincere tone", "playful tone: wordplay and light humour where natural"),
    "energy": ("calm, low-energy delivery", "high-energy delivery: short punchy lines, exclamation"),
}
NEUTRAL = "neutral: follow the brand voice"


def tone_directives(tone: Mapping[str, int]) -> list[str]:
    """One explicit directive per Tone Dial, derived only from the dial values. These go into the generation prompt, so a
    changed dial changes the call (and the same dials are stored with the version)."""
    lines = []
    for dial, (low, high) in DIAL_TEXT.items():
        value = int(tone[dial])
        text = low if value <= 30 else high if value >= 70 else NEUTRAL
        lines.append(f"{dial} {value}/100: {text}")
    return lines
