"""Script Check (feature 28): script, mixed scripts, numerals, joiners, marks and Brand Glossary spellings, all in code."""

from app.reference.india import SCRIPT_OF
from app.studio import scriptcheck as sc


def entry(term: str, language: str = "*", **kw: object) -> dict:
    base = {"term": term, "language": language, "script": None, "approved_spelling": None, "preferred_translation": None, "pronunciation": None,
            "protected": True, "never_translate": True, "prohibited_alternatives": [], "notes": None}
    return base | kw


GLOSSARY = [
    entry("Aamod", pronunciation="AA-mode"), entry("Aamod", "mr", script="Deva", approved_spelling="आमोद", pronunciation="AA-mode"),
    entry("Aamod Festive Tin"), entry("Aamod Festive Tin", "mr", script="Deva", approved_spelling="आमोद फेस्टिव्ह टिन"),
]
CONTEXT = sc.ScriptContext("mr", SCRIPT_OF, GLOSSARY, ["Aamod", "Aamod Festive Tin"], ["No. 1"], 50)


def check(text: str, language: str = "mr", script: str | None = "Deva", context: sc.ScriptContext = CONTEXT) -> sc.ElementResult:
    return sc.check_element(sc.ScriptElement("e", "body", text, language, script), context)


def codes(result: sc.ElementResult) -> list[str]:
    return [i.code for i in result.issues]


def test_correct_copy_passes_and_names_the_glossary_term_with_its_pronunciation() -> None:
    result = check("तीच घरची चव, आता आमोद फेस्टिव्ह टिनमध्ये.")
    assert result.status == "ok" and result.issues == [] and result.expected_script == "Deva" and result.dominant_script == "Deva"
    assert {f["term"] for f in result.terms_found} == {"Aamod", "Aamod Festive Tin"}
    assert next(f for f in result.terms_found if f["term"] == "Aamod")["pronunciation"] == "AA-mode"


def test_a_foreign_script_is_located_and_is_a_problem() -> None:
    text = "तीच घरची சுவை चव"
    result = check(text)
    (issue,) = [i for i in result.issues if i.code == "foreign_script"]
    assert result.status == "problem" and "Tamil" in issue.message and text[issue.start : issue.end] == "சுவை" and issue.severity == "problem"


def test_latin_in_indic_copy_is_information_unless_the_copy_leans_on_it() -> None:
    cta = check("आजच ऑर्डर करा · Order now")
    (latin,) = cta.issues
    assert (latin.code, latin.severity, latin.excerpt) == ("unexpected_latin", "info", "Order now") and cta.status == "ok"
    heavy = check("आजच Order your festive sweets box today and enjoy")
    assert any(i.code == "unexpected_latin" and i.severity == "review" for i in heavy.issues) or "wrong_script" in codes(heavy)


def test_brand_terms_in_latin_letters_are_not_unexpected_latin() -> None:
    result = sc.check_element(sc.ScriptElement("e", "body", "आमोद Aamod Festive Tin", "mr", "Deva"), CONTEXT)
    assert "unexpected_latin" not in codes(result)


def test_a_protected_term_in_latin_letters_must_use_the_approved_spelling() -> None:
    result = check("आता Aamod Festive Tin मध्ये")
    issues = [i for i in result.issues if i.code == "glossary_spelling"]
    assert len(issues) == 1 and "आमोद फेस्टिव्ह टिन" in issues[0].message and issues[0].excerpt == "Aamod Festive Tin" and result.status == "problem"


def test_a_near_miss_of_an_approved_spelling_is_flagged_for_review() -> None:
    result = check("आता आमोद फेस्टिवल टिनमध्ये")
    (variant,) = [i for i in result.issues if i.code == "glossary_variant"]
    assert variant.severity == "review" and "आमोद फेस्टिव्ह टिन" in variant.message and result.status == "review"


def test_prohibited_terms_are_problems() -> None:
    result = check("आमोद No. 1 टिन")
    assert "prohibited_term" in codes(result) and result.status == "problem"


def test_numerals_mixed_or_of_another_script_are_flagged() -> None:
    assert [i.severity for i in check("दर १२ आणि 45").issues if i.code == "numerals"] == ["review"]
    foreign = check("दर ১২ आणि")
    assert any(i.code == "numerals" and i.severity == "problem" and "Bengali" in i.message for i in foreign.issues)
    assert not any(i.code == "numerals" for i in check("दर ₹899 फक्त").issues)  # Latin digits in Indic copy are ordinary


def test_joiners_are_fine_after_a_virama_and_stray_elsewhere() -> None:
    assert "joiner" not in codes(check("क्‍ष चव"))
    stray = check("‍चव घ‍ र")
    assert codes(stray).count("joiner") == 2 and stray.status == "review"
    doubled = check("चव‌‌घर")
    assert any("another joiner" in i.message for i in doubled.issues)


def test_invisible_marks_orphans_repeats_and_damage_are_found() -> None:
    assert "invisible" in codes(check("चव​घर"))
    assert any(i.code == "unicode" and "no letter" in i.message for i in check("ाचव").issues)
    assert any(i.code == "unicode" and "repeated" in i.message for i in check("चवाा").issues)
    assert any(i.code == "unicode" and "virama" in i.message for i in check("क्ा").issues)
    assert any(i.code == "encoding" for i in check("चव�घर").issues)


def test_a_declared_script_that_does_not_fit_the_language_is_a_problem() -> None:
    assert "declared_mismatch" in codes(check("தமிழ்", language="mr", script="Taml"))


def test_an_element_with_no_language_skips_the_script_test_and_says_so() -> None:
    no_language = sc.ScriptContext(None, SCRIPT_OF, [], [], [], 50)
    result = sc.check_element(sc.ScriptElement("e", "body", "तीच चव"), no_language)
    assert codes(result) == ["no_language"] and result.status == "ok" and result.expected_script is None


def test_a_script_without_a_bundled_font_cannot_be_rendered() -> None:
    context = sc.ScriptContext("mr", SCRIPT_OF, [], [], [], 50, shaping_scripts=frozenset({"Latn"}))
    assert "rendering" in codes(check("तीच चव", context=context))


def test_back_translation_checks_run_the_transcreate_term_checks() -> None:
    issues, clean = sc.back_translation_issues("Aamod Festive Tin", "आमोद फेस्टिव्ह टिन", "the festive tin", CONTEXT, "mr")
    assert not clean and issues and issues[0].code == "back_translation"
    issues, clean = sc.back_translation_issues("Aamod tin", "आमोद टिन", "the Aamod tin", CONTEXT, "mr")
    assert clean and issues == []


def test_english_copy_with_devanagari_letters_is_a_problem() -> None:
    result = sc.check_element(sc.ScriptElement("e", "body", "Order आमोद now", "en", "Latn"), sc.ScriptContext("en", SCRIPT_OF, [], [], [], 50))
    assert result.status == "problem" and "foreign_script" in codes(result)
