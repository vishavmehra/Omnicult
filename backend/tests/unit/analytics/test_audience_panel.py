"""Panel sampling (M-13): allowed dimensions, deterministic balanced sampling, and protected-trait rejection in code."""

from collections import Counter

import pytest
from pydantic import ValidationError

from app.analytics.panel import (
    AGE_BANDS,
    CITY_TIERS,
    PROTECTED_TRAITS,
    find_protected,
    marginal_counts,
    reject_protected,
    sample_panel,
)
from app.schemas.audience import AskPanelCreate, AudienceStudyCreate, QuickReadCreate, SamplingPlan, SubgroupFilter

PLAN = dict(states=["IN-MH"], languages=["mr", "hi", "en"], city_tiers=list(CITY_TIERS), age_bands=list(AGE_BANDS))


def panel(size: int = 12, seed: int = 7, **overrides):
    return sample_panel(size=size, seed=seed, **(PLAN | overrides))


def test_sampling_is_deterministic_and_changes_with_the_seed():
    assert panel() == panel()
    assert panel(seed=8) != panel()
    assert [p.ordinal for p in panel()] == list(range(12))


def test_every_dimension_is_balanced_to_within_one_participant():
    people = panel(size=14)
    counts = marginal_counts(people)
    for dimension, values in counts.items():
        assert max(values.values()) - min(values.values()) <= 1, dimension
    assert set(counts["languages"]) == {"mr", "hi", "en"} and set(counts["city_tiers"]) == set(CITY_TIERS)
    assert sum(counts["age_bands"].values()) == 14


def test_weights_set_the_composition_by_configuration():
    people = panel(size=12, weights={"city_tiers": {"tier1": 3, "tier2": 1, "tier3": 1, "rural": 1}})
    counts = Counter(p.city_tier for p in people)
    assert counts == {"tier1": 6, "tier2": 2, "tier3": 2, "rural": 2}


def test_participants_carry_style_knobs_only_never_demographics():
    for p in panel():
        assert set(p.traits) == {"adoption_style", "price_sensitivity", "media_habit", "tone_preference"}


def test_an_empty_dimension_is_refused():
    with pytest.raises(ValueError, match="languages"):
        panel(languages=[])


@pytest.mark.parametrize("text, trait", [
    ("religion", "religion"), ("Hindu", "religion"), ("caste", "caste"), ("scheduled caste", "caste"),
    ("health condition", "health"), ("disabled", "disability"), ("gender", "gender"), ("women", "gender"),
    ("sexual orientation", "sexuality"), ("ethnicity", "ethnicity"), ("political party affiliation", "politics"),
    ("income", "income"),
])
def test_protected_traits_are_found(text: str, trait: str):
    found = find_protected(text)
    assert found is not None and found[0] == trait


@pytest.mark.parametrize("text", ["IN-MH", "mr", "tier2", "rural", "25-34", "55+", "states", "age_bands", "city tiers", "weights"])
def test_allowed_dimension_names_and_values_are_not_flagged(text: str):
    assert find_protected(text.replace("_", " ")) is None


def test_every_protected_trait_has_at_least_one_word():
    assert all(words for words in PROTECTED_TRAITS.values())


def test_reject_protected_checks_keys_values_and_nesting():
    with pytest.raises(ValueError, match="religion"):
        reject_protected({"religion": ["x"]})
    with pytest.raises(ValueError, match="caste"):
        reject_protected({"languages": [{"note": "caste"}]})
    reject_protected({"states": ["IN-MH"], "languages": ["mr"], "weights": {"city_tiers": {"tier1": 2}}})


@pytest.mark.parametrize("field", ["religion", "caste", "health", "sexual_orientation", "gender", "ethnicity", "income", "political_party"])
def test_a_sampling_plan_refuses_a_protected_trait_as_a_dimension(field: str):
    with pytest.raises(ValidationError) as exc:
        SamplingPlan.model_validate({"states": ["IN-MH"], field: ["anything"]})
    assert "protected trait" in str(exc.value)


def test_a_sampling_plan_refuses_a_protected_trait_hidden_in_a_value():
    with pytest.raises(ValidationError, match="protected trait"):
        SamplingPlan.model_validate({"languages": ["mr"], "weights": {"religion": {"hindu": 1}}})


def test_a_sampling_plan_refuses_unknown_states_languages_and_bad_weights():
    for bad in ({"states": ["IN-ZZ"]}, {"languages": ["xx"]}, {"city_tiers": ["tier9"]}, {"age_bands": ["12-17"]},
                {"states": ["IN-MH", "IN-MH"]}, {"weights": {"city_tiers": {"tier1": -1}}},
                {"city_tiers": ["tier1", "tier2"], "weights": {"city_tiers": {"tier1": 1}}}, {"weights": {"shoe_size": {"a": 1}}}):
        with pytest.raises(ValidationError):
            SamplingPlan.model_validate(bad)
    SamplingPlan.model_validate({"states": ["IN-MH"], "languages": ["mr", "en"], "weights": {"languages": {"mr": 2, "en": 1}}})


def test_a_subgroup_filter_uses_only_the_four_dimensions():
    assert SubgroupFilter(states=["IN-MH"], city_tiers=["tier2"]).city_tiers == ["tier2"]
    for bad in ({}, {"caste": ["x"]}, {"religion": "x"}, {"health": ["y"]}, {"favourite_colour": ["red"]}):
        with pytest.raises(ValidationError):
            SubgroupFilter.model_validate(bad)


def test_ask_the_panel_targets_validate_the_filter():
    ok = AskPanelCreate.model_validate({"question": "Why?", "target": {"kind": "subgroup", "filter": {"age_bands": ["25-34"]}}})
    assert ok.target.kind == "subgroup"
    with pytest.raises(ValidationError, match="protected trait"):
        AskPanelCreate.model_validate({"question": "Why?", "target": {"kind": "subgroup", "filter": {"religion": ["x"]}}})
    assert AskPanelCreate.model_validate({"question": "Why?", "target": {"kind": "panel"}}).target.kind == "panel"


def test_quick_read_and_study_requests_have_bounds():
    assert QuickReadCreate(region_code="IN-MH").size == 12
    for size in (1, 5):
        with pytest.raises(ValidationError):
            QuickReadCreate(region_code="IN-MH", size=size)
    with pytest.raises(ValidationError):
        QuickReadCreate(region_code="MH")
    with pytest.raises(ValidationError, match="states"):
        AudienceStudyCreate(sampling=SamplingPlan(), size=30)
    with pytest.raises(ValidationError):
        AudienceStudyCreate(sampling=SamplingPlan(states=["IN-MH"]), size=19)
