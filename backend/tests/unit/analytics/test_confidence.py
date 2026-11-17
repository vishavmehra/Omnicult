"""Confidence rules (handoff 6.2) and conflict detection (6.3). No database, no network."""

from datetime import UTC, date, datetime

import pytest

from app.analytics.confidence import (
    Candidate,
    compute_confidence,
    detect_conflicts,
    freshness_cutoff,
    is_stale,
    normalized_value,
    recommend_selection,
    scope_key,
)
from app.schemas.claims import ClaimDraft, ClaimScope, SourceRef

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def src(group: str, published: date | None = date(2025, 6, 1), *, source_type: str = "wikidata", excerpt: str | None = None,
        identifier: str | None = None) -> SourceRef:
    return SourceRef(
        source_type=source_type, source_identifier=identifier or f"{source_type}-{group}",  # type: ignore[arg-type]
        published_at=published, retrieved_at=NOW, excerpt=excerpt, independence_group=group,
    )


def draft(value: object, *, subject: str = "region:IN-TN", attribute: str = "major_festival", scope: ClaimScope | None = None) -> ClaimDraft:
    return ClaimDraft(
        subject=subject, attribute=attribute, category="festival", value=value, value_text=str(value),
        scope=scope or ClaimScope(region_code="IN-TN"), kind="observed", sources=[], retrieved_at=NOW,
    )


# --- confidence ---------------------------------------------------------------------------


def test_one_source_is_low() -> None:
    level, reason = compute_confidence("observed", [src("wikimedia")], now=NOW)
    assert level == "low"
    assert "One source" in reason


def test_no_sources_is_low() -> None:
    assert compute_confidence("observed", [], now=NOW)[0] == "low"


@pytest.mark.parametrize("kind", ["interpretation", "unverified"])
def test_interpretation_and_unverified_stay_low_even_with_sources(kind: str) -> None:
    sources = [src("wikimedia"), src("government", source_type="curated_reference")]
    level, _ = compute_confidence(kind, sources, now=NOW, reviewer_confirmed=True)  # type: ignore[arg-type]
    assert level == "low"


def test_two_sources_in_one_group_count_as_one() -> None:
    sources = [src("wikimedia", source_type="wikidata"), src("wikimedia", source_type="wikipedia")]
    level, reason = compute_confidence("observed", sources, now=NOW)
    assert level == "low"
    assert "one independence group" in reason


def test_two_independent_fresh_sources_are_moderate() -> None:
    sources = [src("wikimedia"), src("government", source_type="curated_reference")]
    level, reason = compute_confidence("observed", sources, now=NOW)
    assert level == "moderate"
    assert "government" in reason and "wikimedia" in reason


def test_two_independent_but_stale_sources_are_low() -> None:
    sources = [src("census", date(2011, 3, 1), source_type="census_2011"), src("wikimedia", date(2019, 1, 1))]
    level, reason = compute_confidence("observed", sources, now=NOW)
    assert level == "low"
    assert "2019-01-01" in reason


def test_one_stale_and_one_fresh_independent_source_is_moderate() -> None:
    """The rule looks at the newest supporting source: old census data stays Low only unless corroborated."""
    sources = [src("census", date(2011, 3, 1), source_type="census_2011"), src("wikimedia", date(2026, 1, 1))]
    assert compute_confidence("observed", sources, now=NOW)[0] == "moderate"


def test_freshness_boundary_is_exactly_two_years() -> None:
    assert freshness_cutoff(NOW) == date(2024, 11, 17)
    on_cutoff = [src("a", date(2024, 11, 17)), src("b", date(2024, 11, 17))]
    one_day_younger = [src("a", date(2024, 11, 18)), src("b", date(2024, 11, 18))]
    assert compute_confidence("observed", on_cutoff, now=NOW)[0] == "low"
    assert compute_confidence("observed", one_day_younger, now=NOW)[0] == "moderate"
    assert freshness_cutoff(datetime(2028, 2, 29, tzinfo=UTC)) == date(2026, 2, 28)


def test_undated_source_uses_its_retrieval_date() -> None:
    sources = [src("a", None), src("b", None)]  # retrieved NOW
    assert compute_confidence("observed", sources, now=NOW)[0] == "moderate"


def test_reviewer_confirmation_raises_moderate_to_high() -> None:
    sources = [src("wikimedia"), src("government", source_type="curated_reference")]
    assert compute_confidence("observed", sources, now=NOW, reviewer_confirmed=True)[0] == "high"
    assert compute_confidence("observed", sources, now=NOW, campaign_agreement=True)[0] == "high"


def test_reviewer_cannot_raise_a_low_claim() -> None:
    assert compute_confidence("observed", [src("wikimedia")], now=NOW, reviewer_confirmed=True)[0] == "low"


def test_reviewer_and_campaign_sources_are_not_independent_observations() -> None:
    sources = [src("wikimedia"), src("reviewers", source_type="reviewer"), src("ads", source_type="campaign_result")]
    assert compute_confidence("observed", sources, now=NOW)[0] == "low"


def test_synthetic_never_exceeds_moderate() -> None:
    sources = [src("a"), src("b", source_type="curated_reference")]
    level, reason = compute_confidence("synthetic", sources, now=NOW, reviewer_confirmed=True, campaign_agreement=True)
    assert level == "moderate"
    assert "Capped at Moderate" in reason
    assert compute_confidence("synthetic", sources, now=NOW)[0] == "moderate"
    assert compute_confidence("synthetic", [src("a")], now=NOW)[0] == "low"


def test_calculated_claims_follow_the_observed_rule() -> None:
    sources = [src("census", date(2025, 1, 1), source_type="census_2011"), src("wikimedia")]
    assert compute_confidence("calculated", sources, now=NOW)[0] == "moderate"


def test_ungrounded_model_citation_is_not_an_observed_source() -> None:
    bare = src("google", source_type="gemini_grounding")
    quoted = src("google", source_type="gemini_grounding", excerpt="Pongal is a harvest festival.")
    assert compute_confidence("observed", [src("wikimedia"), bare], now=NOW)[0] == "low"
    assert compute_confidence("observed", [src("wikimedia"), quoted], now=NOW)[0] == "moderate"


def test_is_stale() -> None:
    assert is_stale([], now=NOW)
    assert is_stale([src("census", date(2011, 3, 1))], now=NOW)
    assert not is_stale([src("wikimedia")], now=NOW)


# --- conflicts ----------------------------------------------------------------------------


def test_same_subject_attribute_scope_with_different_values_conflict() -> None:
    a, b = draft("Pongal"), draft("Onam")
    found = detect_conflicts([a, b])
    assert len(found) == 1
    assert (found[0].claim_a, found[0].claim_b) == (a, b)
    assert "major_festival" in found[0].reason and "region:IN-TN" in found[0].reason


def test_equal_values_do_not_conflict_after_normalisation() -> None:
    assert detect_conflicts([draft("Pongal"), draft("  pongal ")]) == []
    assert detect_conflicts([draft(5), draft(5.0)]) == []
    assert detect_conflicts([draft(["Pongal", "Onam"]), draft(["Onam", "Pongal"])]) == []
    assert detect_conflicts([draft({"ta": 0.89, "en": 0.1}), draft({"en": 0.1, "ta": 0.89})]) == []


def test_different_scope_subject_or_attribute_do_not_conflict() -> None:
    base = draft("Pongal")
    assert detect_conflicts([base, draft("Onam", scope=ClaimScope(region_code="IN-TN", city_tier="tier1"))]) == []
    assert detect_conflicts([base, draft("Onam", scope=ClaimScope(region_code="IN-KL"))]) == []
    assert detect_conflicts([base, draft("Onam", subject="region:IN-KL")]) == []
    assert detect_conflicts([base, draft("Onam", attribute="major_food")]) == []


def test_three_distinct_values_give_three_pairs_in_input_order() -> None:
    found = detect_conflicts([draft("a"), draft("b"), draft("c")])
    assert [(c.claim_a.value, c.claim_b.value) for c in found] == [("a", "b"), ("a", "c"), ("b", "c")]


def test_numeric_disagreement_is_a_conflict() -> None:
    assert len(detect_conflicts([draft(0.89, attribute="language_share"), draft(0.81, attribute="language_share")])) == 1


def test_scope_key_is_stable() -> None:
    assert scope_key(ClaimScope(region_code="IN-TN")) == scope_key({"region_code": "IN-TN", "country": "IN"})
    assert scope_key(ClaimScope(region_code="IN-TN")) != scope_key(ClaimScope(region_code="IN-KL"))


def test_normalized_value_is_json_comparable() -> None:
    assert normalized_value({"b": [2, 1], "a": "X "}) == {"a": "x", "b": [1.0, 2.0]}


# --- which value to use -------------------------------------------------------------------


def cand(kind: str = "observed", confidence: str = "low", newest: date | None = date(2025, 1, 1), spec: int = 1) -> Candidate:
    return Candidate(kind, confidence, newest, spec)


def test_recommendation_order_is_kind_then_confidence_then_recency_then_specificity() -> None:
    assert recommend_selection(cand("interpretation", "high"), cand("observed", "low"))[0] == "b"
    assert recommend_selection(cand(confidence="low"), cand(confidence="moderate"))[0] == "b"
    assert recommend_selection(cand(newest=date(2020, 1, 1)), cand(newest=date(2025, 1, 1)))[0] == "b"
    assert recommend_selection(cand(spec=1), cand(spec=3))[0] == "b"
    choice, reason = recommend_selection(cand(), cand())
    assert choice == "a" and "reviewer" in reason
