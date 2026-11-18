"""Script and language of a public comment, decided by code: exact script, honest language."""

import pytest

from app.analytics.comment_lang import UNDETERMINED, analyse


@pytest.mark.parametrize(("text", "expected"), [
    ("This is the best ad ever!!", ("en", "Latn", False)),
    ("Wow", ("en", "Latn", False)),
    ("வாழ்த்துக்கள்", ("ta", "Taml", False)),
    ("வாழ்த்துக்கள் super ad", ("ta", "Taml", True)),
    ("ഓണം ആശംസകൾ", ("ml", "Mlym", False)),
    ("നല്ല ad ആണ്", ("ml", "Mlym", True)),
    ("আমার খুব ভালো লাগলো", ("bn", "Beng", False)),
    ("చాలా బాగుంది", ("te", "Telu", False)),
    ("ತುಂಬಾ ಚೆನ್ನಾಗಿದೆ", ("kn", "Knda", False)),
    ("ખૂબ સરસ", ("gu", "Gujr", False)),
    ("ਬਹੁਤ ਵਧੀਆ", ("pa", "Guru", False)),
    ("ବହୁତ ଭଲ", ("or", "Orya", False)),
    ("मला हा खूप आवडला", ("mr", "Deva", False)),
    ("यह बहुत अच्छा है", ("hi", "Deva", False)),
    ("Super ad bhai, bahut acha hai", ("hi", "Latn", True)),
    ("बहुत सुंदर", ("hi", "Deva", False)),
    ("सुंदर", (UNDETERMINED, "Deva", False)),
    ("😍😍 ❤️", ("zxx", "Zyyy", False)),
    ("12345 !!!", ("zxx", "Zyyy", False)),
    ("https://example.com/watch @someone", ("zxx", "Zyyy", False)),
    ("Привет", (UNDETERMINED, "Zzzz", False)),
    ("مرحبا", (UNDETERMINED, "Arab", False)),
])
def test_language_script_and_mixing_of_a_comment(text: str, expected: tuple[str, str, bool]) -> None:
    assert analyse(text) == expected


def test_a_link_or_a_mention_does_not_make_a_regional_comment_code_mixed() -> None:
    assert analyse("வாழ்த்துக்கள் https://example.com/xyz @someone") == ("ta", "Taml", False)


def test_the_mix_of_a_tamil_and_a_malayalam_comment_is_counted_per_comment() -> None:
    languages = [analyse(t)[0] for t in ["வாழ்த்துக்கள்", "ഓണം ആശംസകൾ", "great film", "great ad"]]
    assert sorted(languages) == ["en", "en", "ml", "ta"]
