"""Code checks: Unicode script check, glossary term checks (copy and back-translation), tone directives, chip filtering."""

from uuid import uuid4

from app.agents.tweak import ChipOut, validate_chips
from app.studio import checks

TAMIL = "இனிய தீபாவளி வாழ்த்துகள்"
MARATHI = "शुभ दिवाळी"


def entry(term: str, **kw: object) -> dict:
    base = {"term": term, "language": "*", "script": None, "approved_spelling": None, "preferred_translation": None,
            "pronunciation": None, "protected": True, "never_translate": False, "prohibited_alternatives": [], "notes": None}
    return base | kw


# --- script check -------------------------------------------------------------------------------


def test_script_check_accepts_the_expected_script_and_rejects_another() -> None:
    assert checks.script_check(TAMIL, "Taml")["ok"] is True
    wrong = checks.script_check(MARATHI, "Taml")
    assert wrong["ok"] is False and wrong["foreign_scripts"] == ["Deva"] and wrong["dominant_script"] == "Deva"
    assert checks.script_check("Happy Diwali", "Taml")["ok"] is False  # Latin only: no Tamil letters at all
    assert checks.script_check("Happy Diwali", "Latn")["ok"] is True
    assert checks.script_check(TAMIL, "Latn")["ok"] is False


def test_script_check_ignores_digits_punctuation_and_joiners_and_handles_combining_marks() -> None:
    assert checks.script_check("தீபாவளி 2026! ।", "Taml")["ok"] is True
    assert checks.script_check("क्षत्रिय", "Deva")["shares"] == {"Deva": 1.0}  # conjuncts and vowel signs stay Devanagari
    assert checks.script_check("1234 !!!", "Taml")["ok"] is False  # no letters to check


def test_preserved_terms_do_not_count_against_the_share() -> None:
    text = f"Acme {TAMIL}"
    assert checks.script_check(text, "Taml", preserved=["Acme"])["shares"] == {"Taml": 1.0}
    assert checks.script_check("ACME", "Taml", preserved=["acme"])["ok"] is True  # only a preserved term: nothing else to check
    assert checks.script_check("Acme", "Taml")["ok"] is False


def test_code_mixing_lowers_the_required_share() -> None:
    mixed = "இனிய Diwali offer today"  # mostly Latin letters
    pure = checks.script_check(mixed, "Taml", min_share=checks.min_share_for(0))
    code_mixed = checks.script_check(mixed, "Taml", min_share=checks.min_share_for(100))
    assert checks.min_share_for(0) > checks.min_share_for(100) >= 0.2
    assert pure["ok"] is False and code_mixed["ok"] is True


# --- glossary term checks --------------------------------------------------------------------------


def test_protected_terms_must_survive_in_the_copy_and_the_back_translation() -> None:
    glossary = [entry("Acme", language="ta", script="Taml", approved_spelling="ஏக்மி")]
    good = checks.term_checks("Light up with Acme", "ஏக்மி உடன் ஒளிருங்கள்", "Glow with Acme", glossary, language="ta")
    assert good["protected_preserved"] is True and good["preserved_terms"] == ["ஏக்மி"]
    altered = checks.term_checks("Light up with Acme", "ஏக்மி உடன் ஒளிருங்கள்", "Glow with Akme", glossary, language="ta")
    assert altered["protected_preserved"] is False and altered["missing_in_back_translation"] == ["Acme"]
    wrong_spelling = checks.term_checks("Light up with Acme", "அக்மி உடன் ஒளிருங்கள்", "Glow with Acme", glossary, language="ta")
    assert wrong_spelling["missing_in_copy"] == ["Acme"]  # the brand-approved spelling is required, not any spelling
    assert checks.term_problems(wrong_spelling)


def test_a_term_not_in_the_source_is_not_required() -> None:
    result = checks.term_checks("Light up Diwali", "दिवाळी", "Diwali", [entry("Acme")], language="mr")
    assert result["protected_preserved"] is True and result["preserved_terms"] == []


def test_prohibited_alternatives_are_checked_in_both_texts_and_brand_lists_apply() -> None:
    glossary = [entry("Acme", prohibited_alternatives=["Akme"], protected=False)]
    result = checks.term_checks("Acme sale", "Akme விற்பனை", "AKME sale", glossary, language="ta", prohibited=["cheap"])
    assert result["prohibited_in_copy"] == ["Akme"] and result["prohibited_in_back_translation"] == ["Akme"]
    result = checks.term_checks("Acme sale", "x", "a cheap sale", [], language="ta", prohibited=["cheap"])
    assert result["prohibited_in_back_translation"] == ["cheap"]
    assert checks.term_checks("Acme sale", "x", None, glossary, language="ta")["prohibited_in_back_translation"] == []  # back None = skipped


def test_the_entry_for_the_target_language_overrides_the_all_languages_entry() -> None:
    glossary = [entry("Acme"), entry("Acme", language="ta", approved_spelling="ஏக்மி", script="Taml")]
    assert checks.term_checks("Acme", "ஏக்மி", "Acme", glossary, language="ta")["protected_preserved"] is True
    assert checks.term_checks("Acme", "Acme", "Acme", glossary, language="ta")["missing_in_copy"] == ["Acme"]
    assert checks.term_checks("Acme", "Acme", "Acme", glossary, language="mr")["protected_preserved"] is True  # `*` entry only
    assert checks.applicable_entries(glossary, "mr") == [glossary[0]]


def test_preferred_translation_is_a_warning_not_a_block_and_never_translate_is_protected() -> None:
    glossary = [entry("sale", protected=False, preferred_translation="தள்ளுபடி"), entry("Acme", protected=False, never_translate=True)]
    result = checks.term_checks("Acme sale", "Acme விற்பனை", "Acme sale", glossary, language="ta")
    assert result["preferred_translation_missing"] == ["sale"] and result["protected_preserved"] is True
    assert checks.term_checks("Acme sale", "விற்பனை", "sale", glossary, language="ta")["missing_in_copy"] == ["Acme"]


def test_flat_brand_protected_terms_are_checked_like_glossary_terms() -> None:
    result = checks.term_checks("Northstar trails", "पायवाटा", "trails", [], language="mr", protected=["Northstar"])
    assert result["missing_in_copy"] == ["Northstar"] and result["missing_in_back_translation"] == ["Northstar"]


# --- tone dials ---------------------------------------------------------------------------------------


def test_tone_dials_change_the_directives() -> None:
    neutral = {d: 50 for d in checks.DIAL_TEXT}
    base = checks.tone_directives(neutral)
    assert len(base) == 5 and all(checks.NEUTRAL in line for line in base)
    for dial in checks.DIAL_TEXT:
        low, high = checks.tone_directives({**neutral, dial: 10}), checks.tone_directives({**neutral, dial: 90})
        assert low != base and high != base and low != high
        assert [line for line in low if line.startswith(dial)] != [line for line in high if line.startswith(dial)]
        assert sum(1 for a, b in zip(low, base) if a != b) == 1  # one dial moves one directive


# --- chip filtering --------------------------------------------------------------------------------------


def chip(**kw: object) -> ChipOut:
    base = {"title": "Warmer", "operation_type": "replace_text", "new_value": "Happy Diwali with Acme!", "reason": "r",
            "claims": ["C1"], "expected_effect": "e"}
    return ChipOut.model_validate(base | kw)


def run(outs: list[ChipOut], **kw: object) -> tuple[list, list[str]]:
    element = {"id": "headline", "kind": "headline", "value": "Happy Diwali from Acme", "language": "en", "script": "Latn"}
    args = {"element": element, "handles": {"C1": uuid4(), "C2": uuid4()}, "glossary": [entry("Acme")], "protected": [], "prohibited": [], "limit": 5}
    return validate_chips(outs, **(args | kw))  # type: ignore[arg-type]


def test_chips_that_cite_unknown_claims_or_none_are_dropped_in_code() -> None:
    drafts, notes = run([chip(claims=["C9"]), chip(claims=[]), chip(claims=["C1", "C99"]), chip(claims=["c1"], new_value="Diwali greetings from Acme")])
    assert len(drafts) == 1 and drafts[0].claim_ids and drafts[0].change == {"value": "Diwali greetings from Acme"}
    assert notes == ["3 proposed chip(s) cited a claim that was not supplied, or none and were removed."]


def test_chips_that_cannot_be_applied_or_break_the_glossary_are_dropped() -> None:
    swap = chip(operation_type="swap_reference", new_value=None, from_text="Diwali", to_text="Pongal")
    bad_swap = chip(operation_type="swap_reference", new_value=None, from_text="Holi", to_text="Pongal")
    same = chip(new_value="Happy Diwali from Acme")
    no_brand = chip(new_value="Happy Diwali everyone")  # drops the protected term Acme
    cheap = chip(new_value="Happy Diwali from Acme, cheap")
    drafts, notes = run([swap, bad_swap, same, no_brand, cheap], prohibited=["cheap"])
    assert [d.operation_type for d in drafts] == ["swap_reference"] and drafts[0].change == {"from_text": "Diwali", "to_text": "Pongal"}
    assert len(notes) == 2 and any("protected term" in n for n in notes) and any("could not be applied" in n for n in notes)


def test_chips_that_leave_the_script_or_repeat_another_chip_are_dropped_and_the_limit_applies() -> None:
    element = {"id": "h", "kind": "headline", "value": "शुभ दिवाळी Acme", "language": "mr", "script": "Deva"}
    in_tamil = chip(new_value="இனிய தீபாவளி Acme")
    ok_a, ok_b = chip(new_value="दिवाळीच्या शुभेच्छा Acme"), chip(new_value="दिवाळी आनंदाची Acme")
    drafts, notes = run([in_tamil, ok_a, ok_a, ok_b], element=element, limit=1)
    assert len(drafts) == 1 and drafts[0].change["value"] == "दिवाळीच्या शुभेच्छा Acme"
    assert any("script" in n for n in notes) and any("repeated" in n for n in notes)
