"""Script Check (feature 28), version script-check-v1. Pure, deterministic code: no model, no network, no database.

It reads one text element and says whether it is written correctly for its language: the script, mixed scripts, numerals,
joiners, stray or damaged characters, the Brand Glossary spellings, protected and prohibited terms. Everything here is a
check in code. It does not judge meaning or tone, and it cannot tell that a word is mistranslated; it says where a native
reader should look. It reuses the transcreate checks (`app.studio.checks`): the Unicode script blocks, the script test with
its code-mixing threshold, and the glossary term checks, so a line is judged by the same rules before and after it is edited.

Each issue carries a character span and the quoted text, so the interface can point at the exact place. Severity is fixed
per code: `problem` (almost certainly wrong), `review` (a native reader should look) or `info` (worth knowing, not a fault).
"""

import difflib
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.studio.checks import SCRIPT_RANGES, min_share_for, script_check, script_of, term_checks

CHECK_VERSION = "script-check-v1"
Severity = Literal["problem", "review", "info"]
VIRAMAS = frozenset({0x094D, 0x09CD, 0x0A4D, 0x0ACD, 0x0B4D, 0x0BCD, 0x0C4D, 0x0CCD, 0x0D4D})
JOINERS = {0x200C: "zero-width non-joiner", 0x200D: "zero-width joiner"}
INVISIBLE = frozenset({0x200B, 0xFEFF, 0x2060, 0x00AD, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)})
INVISIBLE_NAMES = {0x200B: "zero-width space", 0xFEFF: "byte-order mark", 0x2060: "word joiner", 0x00AD: "soft hyphen"}
LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z'’\-]*(?:\s+[A-Za-z][A-Za-z'’\-]*)*")
LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
VARIANT_RATIO = 0.82
SCRIPT_NAMES = {"Latn": "Latin", "Deva": "Devanagari", "Beng": "Bengali", "Guru": "Gurmukhi", "Gujr": "Gujarati", "Orya": "Odia",
                "Taml": "Tamil", "Telu": "Telugu", "Knda": "Kannada", "Mlym": "Malayalam", "Arab": "Arabic", "Zzzz": "another script"}


def script_name(code: str | None) -> str:
    return SCRIPT_NAMES.get(code or "", code or "unknown")


@dataclass(frozen=True)
class ScriptElement:
    id: str
    kind: str
    text: str
    language: str | None = None
    script: str | None = None


@dataclass(frozen=True)
class ScriptContext:
    version_language: str | None
    script_of_language: Mapping[str, str]
    entries: Sequence[Mapping[str, Any]] = ()  # glossary entries for the languages in play, as plain dicts
    protected: Sequence[str] = ()  # the brand record's protected terms (Latin, as written)
    prohibited: Sequence[str] = ()
    code_mixing: int = 50  # the version's Tone Dial: how much English the copy is meant to carry
    shaping_scripts: frozenset[str] = frozenset(SCRIPT_RANGES)  # scripts with a bundled font


@dataclass
class Issue:
    code: str
    severity: Severity
    message: str
    start: int | None = None
    end: int | None = None
    excerpt: str | None = None


@dataclass
class ElementResult:
    element_id: str
    expected_script: str | None
    expected_language: str | None
    dominant_script: str | None
    shares: dict[str, float]
    issues: list[Issue] = field(default_factory=list)
    terms_found: list[dict[str, Any]] = field(default_factory=list)

    @property
    def status(self) -> Literal["ok", "review", "problem"]:
        severities = {i.severity for i in self.issues}
        return "problem" if "problem" in severities else "review" if "review" in severities else "ok"


# --- characters ---------------------------------------------------------------------------------------------------------


def digit_script(ch: str) -> str:
    """The numbering system of a decimal digit: Latn for 0-9, else the block it sits in."""
    point = ord(ch)
    if 0x30 <= point <= 0x39:
        return "Latn"
    for script, ranges in SCRIPT_RANGES.items():
        if any(low <= point <= high for low, high in ranges):
            return script
    return "Zzzz"


def _excerpt(text: str, start: int, end: int) -> str:
    """The exact characters of the span (the interface highlights them inside the element's own text)."""
    return text[start:end]


def _find(text: str, needle: str) -> tuple[int, int] | None:
    at = text.casefold().find(needle.casefold())
    return (at, at + len(needle)) if at >= 0 else None


def _is_virama(ch: str | None) -> bool:
    return ch is not None and ord(ch) in VIRAMAS


def character_issues(text: str, expected: str | None) -> list[Issue]:
    """Damaged, stray and misplaced characters: replacement characters, controls, invisible characters, joiners, marks
    with no base letter, repeated marks, marks that follow a virama, and text that is not in Unicode normal form."""
    issues: list[Issue] = []
    for i, ch in enumerate(text):
        prev = text[i - 1] if i else None
        nxt = text[i + 1] if i + 1 < len(text) else None
        point, category = ord(ch), unicodedata.category(ch)
        if ch == "�":
            issues.append(Issue("encoding", "problem", "A replacement character (U+FFFD) stands where a letter was lost: the text was damaged when it was saved or pasted.", i, i + 1, _excerpt(text, i, i + 1)))
        elif category == "Cc" and ch not in "\n\t\r":
            issues.append(Issue("encoding", "problem", f"A control character (U+{point:04X}) is in the text.", i, i + 1, _excerpt(text, i, i + 1)))
        elif point in JOINERS:
            where = None
            if prev is None or prev.isspace() or nxt is None or nxt.isspace():
                where = "at the edge of a word"
            elif ord(prev) in JOINERS:
                where = "right after another joiner"
            elif not _is_virama(prev) and script_of(prev) in (None, "Latn"):
                where = "next to a digit, punctuation or Latin letter"
            if where:
                issues.append(Issue("joiner", "review", f"A {JOINERS[point]} sits {where}; joiners only do something after a virama or between Indic letters.", i, i + 1, _excerpt(text, i, i + 1)))
        elif point in INVISIBLE:
            name = INVISIBLE_NAMES.get(point, f"invisible character U+{point:04X}")
            issues.append(Issue("invisible", "review", f"A {name} is in the text. It cannot be seen and can break search and matching.", i, i + 1, _excerpt(text, i, i + 1)))
        elif category in ("Mn", "Mc") and script_of(ch) not in (None, "Latn"):
            if prev is None or prev.isspace() or unicodedata.category(prev)[0] in "PNSZ":
                issues.append(Issue("unicode", "problem", "A vowel sign or mark has no letter to attach to.", i, i + 1, _excerpt(text, i, i + 1)))
            elif prev == ch:
                issues.append(Issue("unicode", "problem", "The same vowel sign or mark is repeated.", i - 1, i + 1, _excerpt(text, i - 1, i + 1)))
            elif _is_virama(prev) and not _is_virama(ch):
                issues.append(Issue("unicode", "problem", "A mark directly after a virama (halant) cannot be shaped.", i - 1, i + 1, _excerpt(text, i - 1, i + 1)))
    if unicodedata.normalize("NFC", text) != text:
        issues.append(Issue("unicode", "review", "The text is not in normalised (NFC) form. Look-alike sequences can break matching and shaping."))
    return issues


def numeral_issues(text: str, expected: str | None) -> list[Issue]:
    """Digits of more than one numbering system in one element, or the digits of another script."""
    systems: dict[str, int] = {}
    for ch in text:
        if unicodedata.category(ch) == "Nd":
            system = digit_script(ch)
            systems[system] = systems.get(system, 0) + 1
    issues: list[Issue] = []
    if len(systems) > 1:
        issues.append(Issue("numerals", "review", "Digits from more than one numbering system are mixed: " + ", ".join(script_name(s) for s in sorted(systems)) + "."))
    for system in sorted(systems):
        if system not in ("Latn", expected):
            first = next(i for i, ch in enumerate(text) if unicodedata.category(ch) == "Nd" and digit_script(ch) == system)
            issues.append(Issue("numerals", "problem", f"{script_name(system)} digits appear in {script_name(expected) if expected else 'this'} copy.", first, first + 1, _excerpt(text, first, first + 1)))
    return issues


def script_issues(text: str, expected: str | None, context: ScriptContext, preserved: Sequence[str]) -> tuple[list[Issue], dict[str, Any] | None]:
    """The script test (reused from the transcreate checks), then where the letters of another script are, and words that
    mix scripts. Latin words that are not brand terms are listed as information, or for review when the copy leans on them."""
    issues: list[Issue] = []
    if expected is None:
        return issues, None
    check = script_check(text, expected, preserved=preserved, min_share=min_share_for(context.code_mixing))
    foreign_runs = _foreign_runs(text, expected)
    for start, end, script in foreign_runs:
        issues.append(Issue("foreign_script", "problem", f"{script_name(script)} letters appear in {script_name(expected)} copy.", start, end, _excerpt(text, start, end)))
    if not check["ok"] and not foreign_runs:
        issues.append(Issue("wrong_script", "problem", check["message"]))
    for match in re.finditer(r"\S+", text):
        scripts = {s for s in (script_of(c) for c in match.group()) if s and s != "Zzzz"}
        non_latin = scripts - {"Latn"}
        if len(non_latin) > 1:
            issues.append(Issue("mixed_script_word", "problem", "One word mixes letters of " + " and ".join(script_name(s) for s in sorted(non_latin)) + ".", match.start(), match.end(), match.group()))
        elif non_latin and "Latn" in scripts and not any(p.casefold() in match.group().casefold() for p in preserved if p):
            issues.append(Issue("mixed_script_word", "review", f"One word mixes Latin and {script_name(next(iter(non_latin)))} letters.", match.start(), match.end(), match.group()))
    if expected != "Latn":
        latin_share = check["shares"].get("Latn", 0.0)
        severity: Severity = "info" if latin_share <= 0.5 or context.code_mixing >= 70 else "review"
        allowed = {w.casefold() for term in preserved for w in LATIN_WORD.findall(term)}
        for run in LATIN_RUN.finditer(text):
            words = [w for w in LATIN_WORD.findall(run.group()) if len(w) > 1 and w.casefold() not in allowed]
            if words:
                issues.append(Issue("unexpected_latin", severity, f"Latin words in {script_name(expected)} copy: {' '.join(words)}. Fine as deliberate code-mixing; confirm it is meant.", run.start(), run.end(), run.group()))
    return issues, check


def _foreign_runs(text: str, expected: str) -> list[tuple[int, int, str]]:
    """Runs of letters in a script that is neither the expected one nor Latin (counting marks as part of their run)."""
    runs: list[tuple[int, int, str]] = []
    for i, ch in enumerate(text):
        script = script_of(ch)
        if script is None or script in (expected, "Latn"):
            continue
        if runs and runs[-1][2] == script and i - runs[-1][1] <= 1:
            runs[-1] = (runs[-1][0], i + 1, script)
        else:
            runs.append((i, i + 1, script))
    return runs


# --- the Brand Glossary --------------------------------------------------------------------------------------------------


def _scoped(entries: Sequence[Mapping[str, Any]], language: str | None) -> list[Mapping[str, Any]]:
    return [e for e in entries if e["language"] in ("*", language)]


def glossary_issues(text: str, language: str | None, expected: str | None, context: ScriptContext) -> tuple[list[Issue], list[dict[str, Any]], list[str]]:
    """Protected terms, approved spellings, prohibited terms and pronunciation guidance for the terms present in `text`.
    Returns (issues, terms found, the forms that count as brand terms in this text)."""
    issues: list[Issue] = []
    found: list[dict[str, Any]] = []
    forms: list[str] = [*context.protected]
    checks = term_checks(text, text, None, context.entries, language=language, protected=context.protected, prohibited=context.prohibited)
    reported: list[tuple[int, int]] = []
    for term in sorted(checks["missing_in_copy"], key=len, reverse=True):  # a term inside a longer one is reported once, with the longer
        span = _find(text, term)
        if span and any(a <= span[0] and span[1] <= b for a, b in reported):
            continue
        if span:
            reported.append(span)
        entry = next((e for e in _scoped(context.entries, language) if e["term"].casefold() == term.casefold() and e.get("approved_spelling")), None)
        approved = entry["approved_spelling"] if entry else None
        message = (f"'{term}' is written in Latin letters; the approved spelling for this language is '{approved}'." if approved
                   else f"The protected term '{term}' is not kept as written.")
        issues.append(Issue("glossary_spelling", "problem", message, *(span or (None, None)), _excerpt(text, *span) if span else None))
    for banned in checks["prohibited_in_copy"]:
        span = _find(text, banned)
        issues.append(Issue("prohibited_term", "problem", f"'{banned}' is a prohibited term in the Brand Glossary or Brand Kit.", *(span or (None, None)), _excerpt(text, *span) if span else None))
    seen: set[str] = set()
    for entry in sorted(_scoped(context.entries, language), key=lambda e: e["language"] == "*"):  # the language's own entry first
        approved, term = entry.get("approved_spelling"), entry["term"]
        if term.casefold() in seen:
            continue
        seen.add(term.casefold())
        for form in dict.fromkeys(f for f in (approved, term) if f):
            span = _find(text, form)
            if span:
                found.append({"term": term, "form": text[span[0] : span[1]], "pronunciation": entry.get("pronunciation"), "protected": bool(entry["protected"] or entry["never_translate"]),
                              "start": span[0], "end": span[1]})
                forms.append(form)
                break
        else:
            if approved and entry.get("language") == language and (entry.get("script") in (None, expected)):
                variant = _near_miss(text, approved)
                if variant:
                    issues.append(Issue("glossary_variant", "review", f"'{variant[0]}' is close to the approved spelling '{approved}' of '{term}' but not the same. A grammatical ending is fine; a native reader can confirm.", variant[1], variant[2], variant[0]))
    return issues, found, list(dict.fromkeys(forms))


def _near_miss(text: str, approved: str) -> tuple[str, int, int] | None:
    """A span of `text` that is close to `approved` (same number of words) without containing it."""
    words = list(re.finditer(r"\S+", text))
    size = len(approved.split())
    for i in range(len(words) - size + 1):
        start, end = words[i].start(), words[i + size - 1].end()
        candidate = text[start:end].strip(".,;:!?*·|।")
        stem = candidate[: len(approved) + 2]
        if candidate != approved and difflib.SequenceMatcher(None, approved, stem).ratio() >= VARIANT_RATIO:
            return candidate, start, start + len(candidate)
    return None


# --- the whole element -----------------------------------------------------------------------------------------------------


def check_element(element: ScriptElement, context: ScriptContext) -> ElementResult:
    language = element.language or context.version_language
    declared = context.script_of_language.get(language or "")
    expected = element.script or declared
    text = element.text
    issues: list[Issue] = []
    if element.script and element.language and context.script_of_language.get(element.language) not in (None, element.script):
        issues.append(Issue("declared_mismatch", "problem", f"The element says {script_name(element.script)}, but {element.language} is written in {script_name(context.script_of_language[element.language])}."))
    glossary, found, forms = glossary_issues(text, language, expected, context)
    script_found, check = script_issues(text, expected, context, forms)
    issues += character_issues(text, expected) + numeral_issues(text, expected) + script_found + glossary
    if expected is None and any(script_of(c) for c in text):
        issues.append(Issue("no_language", "info", "No language or script is set for this element, so the script test was skipped."))
    if expected is not None and expected not in context.shaping_scripts:
        issues.append(Issue("rendering", "review", f"No bundled font covers {script_name(expected)}, so this text cannot be rendered in code on this server."))
    issues.sort(key=lambda i: (i.start if i.start is not None else -1, i.code))
    return ElementResult(element.id, expected, language, check["dominant_script"] if check else None, check["shares"] if check else {}, issues, found)


def back_translation_issues(
    source: str, copy: str, back: str, context: ScriptContext, language: str | None
) -> tuple[list[Issue], bool]:
    """The transcreate term checks on the stored English back-translation: protected terms must survive and prohibited ones
    must not appear. Returns (issues, whether the back-translation is clean)."""
    checks = term_checks(source, copy, back, context.entries, language=language, protected=context.protected, prohibited=context.prohibited)
    issues = [Issue("back_translation", "problem", f"The protected term '{t}' is altered in the English back-translation.") for t in checks["missing_in_back_translation"]]
    issues += [Issue("back_translation", "problem", f"The prohibited term '{t}' appears in the English back-translation.") for t in checks["prohibited_in_back_translation"]]
    return issues, not issues
