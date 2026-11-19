"""Claim Guard rules (feature 27): wording found in six languages, graded by fixed rules, with policy, evidence and basis."""

import pytest

from app.studio import claimguard as cg

AAMOD_POLICY = cg.PolicyInput(
    forbidden=["Health, nutrition or wellness claims.", "Financial claims.", "Superiority, leadership or No. 1 claims without independent substantiation."],
    allowed=["True product facts of the fictional product: contents, net weight (750 g), delivery window."],
)
PLANTED = "*ग्राहकांच्या पसंतीनुसार महाराष्ट्रातील सर्वोत्तम फराळ टिन."


def find(text: str, policy: cg.PolicyInput = cg.PolicyInput(), **kw: object) -> list[cg.Draft]:
    return cg.extract([cg.TextElement("e1", "body", text)], policy=policy, **kw)  # type: ignore[arg-type]


def test_the_planted_marathi_superiority_claim_is_found_with_its_clause_and_position() -> None:
    (draft,) = find(PLANTED, AAMOD_POLICY)
    assert (draft.kind, draft.quote, draft.rule_id, draft.source) == ("superiority", "सर्वोत्तम", "superiority.deva", "rule")
    assert PLANTED[draft.start : draft.end] == "सर्वोत्तम"
    assert draft.phrase == "ग्राहकांच्या पसंतीनुसार महाराष्ट्रातील सर्वोत्तम फराळ टिन"
    assert (draft.severity, draft.blocks_go, draft.confidence) == ("high", True, "high")
    assert draft.policy["status"] == "forbidden" and "Superiority" in draft.policy["rule"]
    assert draft.basis == {"stated": True, "wording": "पसंतीनुसार", "sourced": False}
    assert [r.rule for r in draft.rules] == ["G1_base", "G2_hard_wording", "G3_policy", "G4_basis", "G7_blocks_go"]
    assert {"asci-1-1", "asci-1-2", "asci-1-6"} <= set(draft.ad_code_ids)


@pytest.mark.parametrize("text,kind,quote", [
    ("*வாடிக்கையாளர் விருப்பத்தின்படி தமிழ்நாட்டின் சிறந்த பலகார டின்.", "superiority", "சிறந்த"),
    ("*ഉപഭോക്താക്കളുടെ ഇഷ്ടപ്രകാരം കേരളത്തിലെ ഏറ്റവും മികച്ച പലഹാര ടിൻ.", "superiority", "ഏറ്റവും മികച്ച"),
    ("*গ্রাহকদের পছন্দ অনুযায়ী পশ্চিমবঙ্গের সেরা মিষ্টির টিন।", "superiority", "সেরা"),
    ("हमारी मिठाई नंबर 1 है", "superiority", "नंबर 1"),
    ("Best in India, trusted by all", "superiority", "Best in India"),
    ("This is better than any other tin", "comparative", "better than any"),
    ("आता फक्त ₹८९९ मध्ये", "price", "₹८९९"),
    ("Only Rs. 899 today", "price", "Rs. 899"),
    ("आरोग्यदायी फराळ", "health", "आरोग्य"),
    ("A healthy treat with no added sugar", "health", "healthy"),
    ("100% satisfaction guaranteed", "guarantee", "100%"),
    ("डिलिव्हरीची हमी", "guarantee", "हमी"),
    ("Guaranteed returns on every box", "financial", "Guaranteed returns"),
])
def test_wording_is_found_in_english_and_the_five_market_languages(text: str, kind: str, quote: str) -> None:
    found = [d for d in find(text) if d.kind == kind]
    assert found and quote in {d.quote for d in found}, [(d.kind, d.quote) for d in find(text)]
    for d in found:
        assert text[d.start : d.end] == d.quote


@pytest.mark.parametrize("text", [
    "दिवाळी म्हणजे फराळ!", "आजीच्या हातची चव", "घरच्या चवीचा फराळ, आता एकाच टिनमध्ये", "भाऊबीजेला द्या गोड भेट", "आजच ऑर्डर करा · Order now",
    "Every bond, a little sweeter.", "Aamod Festive Tin*", "Best wishes this Diwali",
    "இந்தப் பண்டிகைக்கு இனிய பரிசைக் கொடுங்கள்", "ഈ ഉത്സവത്തിന് മധുരമുള്ള സമ്മാനം നൽകൂ", "এই উৎসবে মিষ্টি উপহার দিন", "*நிகர எடை 750 கிராம்.", "*নিট ওজন 750 গ্রাম।",
])
def test_the_ordinary_copy_of_the_journey_raises_nothing(text: str) -> None:
    assert find(text, AAMOD_POLICY) == []


def test_a_word_inside_another_word_is_not_a_match_and_an_indic_stem_takes_its_suffix() -> None:
    assert find("bestseller candles") == []  # not the word "best"
    assert [d.quote for d in find("सर्वोत्तमाचा मान")] == ["सर्वोत्तम"]  # the Marathi genitive suffix still matches the stem
    assert find("असर्वोत्तम") == []  # but not from the middle of a word


def test_severity_follows_the_rules_and_policy_only_escalates() -> None:
    (plain,) = find("Our leading brand")  # soft wording, no policy: base only
    assert (plain.severity, [r.rule for r in plain.rules]) == ("medium", ["G1_base"])
    (policed,) = find("Our leading brand", cg.PolicyInput(forbidden=["No leadership claims."]))
    assert policed.severity == "high" and policed.blocks_go and "G3_policy" in {r.rule for r in policed.rules}
    (price,) = find("Only Rs. 899")
    assert (price.severity, price.blocks_go) == ("low", False)
    (capped,) = find(PLANTED, AAMOD_POLICY)
    assert capped.severity == "high" and len(capped.rules) > 3  # more steps than levels: never above high


def test_a_basis_with_a_source_or_date_is_not_flagged_as_unsourced() -> None:
    (sourced,) = find("Best sweets in Maharashtra, according to the 2027 Nielsen survey")
    assert sourced.basis["stated"] and sourced.basis["sourced"] and "G4_basis" not in {r.rule for r in sourced.rules}


def test_a_price_is_checked_against_the_campaign_brief_and_a_mismatch_escalates() -> None:
    (ok,) = find("Only Rs. 899", brief_price=899.0, brief_currency="INR", brief_sample=True)
    assert ok.evidence["status"] == "found" and ok.evidence["items"][0]["source"] == "campaign_brief" and "sample" in ok.evidence["items"][0]["statement"]
    (off,) = find("Only Rs. 799", brief_price=899.0, brief_currency="INR")
    assert off.evidence["status"] == "mismatch" and off.severity == "medium" and "G5_price" in {r.rule for r in off.rules}
    (none,) = find("Only Rs. 799")
    assert none.evidence["status"] == "none"


def test_evidence_needs_two_shared_words_and_is_related_not_proof() -> None:
    claims = [{"id": "c1", "statement": "Maharashtra households buy sweets gifting boxes before Diwali", "kind": "observed", "confidence": "moderate"}]
    (hit,) = find("Maharashtra gifting boxes are the best", region_claims=claims)
    assert hit.evidence["status"] == "found" and hit.evidence["items"][0]["claim_id"] == "c1" and "not proof" in hit.evidence["items"][0]["note"]
    (miss,) = find("Maharashtra is the best", region_claims=claims)
    assert miss.evidence["status"] == "none"


def test_policy_reads_the_brand_kit_lists_and_the_prohibited_terms() -> None:
    assert cg.policy_match("health", "healthy", AAMOD_POLICY)["status"] == "forbidden"
    assert cg.policy_match("price", "only 899", AAMOD_POLICY)["status"] == "not_listed"
    assert cg.policy_match("price", "only 899", cg.PolicyInput())["status"] == "no_policy"
    term = cg.policy_match("guarantee", "we are No. 1 here", cg.PolicyInput(prohibited_terms=["No. 1"]))
    assert term["status"] == "forbidden" and term["source"] == "Brand prohibited terms"


def test_a_finding_key_is_stable_and_differs_by_position() -> None:
    (a,) = find(PLANTED)
    (b,) = find(PLANTED)
    assert a.key == b.key and len(a.key) == 16
    (shifted,) = find("x " + PLANTED)
    assert shifted.key != a.key


def test_ad_codes_fit_the_kind_and_the_index_gap_for_financial_is_stated() -> None:
    assert {"asci-fb-2"} <= {e.id for e in cg.ad_codes_for("health")}
    (financial,) = [d for d in find("Guaranteed returns") if d.kind == "financial"]
    assert cg.INDEX_NOTE in financial.limitations


def test_ordering_is_severity_first_then_the_creatives_own_order() -> None:
    drafts = cg.extract([cg.TextElement("a", "body", "Only Rs. 899"), cg.TextElement("b", "body", "Best sweets")], policy=cg.PolicyInput())
    ordered = cg.order(drafts, {"a": 0, "b": 1})
    assert [d.element_id for d in ordered] == ["b", "a"]
