"""Synthetic panel sampling (migration decision M-13): participants are sampled by state, language, city tier and age band.

Those four dimensions are the only ones allowed. Protected traits (religion, caste, health, gender and similar) are
refused wherever a sampling plan or a subgroup filter could carry them; `find_protected` is the single check. Sampling
is deterministic: the same plan, size and seed give the same participants. Each dimension's marginal counts follow its
shares (equal unless the plan says otherwise, largest-remainder rounding), but the joint mix is a seeded shuffle, not a
population statistic, and shares are a configuration choice rather than prevalence in the real market.
"""

import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from app.analytics.population import TRAITS, allocate

SAMPLING_VERSION = "panel-v1"
CITY_TIERS: tuple[str, ...] = ("tier1", "tier2", "tier3", "rural")
AGE_BANDS: tuple[str, ...] = ("18-24", "25-34", "35-44", "45-54", "55+")
DIMENSIONS: tuple[str, ...] = ("states", "languages", "city_tiers", "age_bands")
CITY_TIER_LABELS = {"tier1": "tier 1 city", "tier2": "tier 2 city", "tier3": "tier 3 town", "rural": "rural area"}
SAMPLING_NOTE = (
    "Participants are synthetic. Each dimension is balanced to its shares with a seeded shuffle; the combination of "
    "dimensions is not a population statistic, and the panel is not statistically representative of real people."
)

# Canonical protected trait -> words that refer to it. Matching is on whole words, case-insensitive.
PROTECTED_TRAITS: dict[str, tuple[str, ...]] = {
    "religion": ("religion", "religious", "faith", "creed", "denomination", "hindu", "muslim", "christian", "sikh",
                 "buddhist", "jain", "jewish", "atheist"),
    "caste": ("caste", "castes", "subcaste", "jati", "varna", "dalit", "brahmin", "obc", "scheduled caste", "scheduled tribe"),
    "health": ("health", "medical", "illness", "disease", "diagnosis", "condition", "pregnant", "pregnancy"),
    "disability": ("disability", "disabled", "handicap", "handicapped"),
    "sexuality": ("sexuality", "sexual orientation", "gay", "lesbian", "bisexual", "lgbt", "lgbtq", "queer"),
    "gender": ("gender", "gender identity", "transgender", "male", "female", "men", "women", "sex"),
    "ethnicity": ("ethnicity", "ethnic", "race", "racial", "tribe", "tribal", "community"),
    "politics": ("politics", "political", "party affiliation", "voter"),
    "income": ("income", "wealth", "wealthy", "salary", "poverty"),
}
_PATTERNS = {
    trait: re.compile(r"(?<![a-z])(" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")(?![a-z])", re.IGNORECASE)
    for trait, words in PROTECTED_TRAITS.items()
}
PROTECTED_MESSAGE = (
    "'{word}' refers to {trait}, a protected trait. Panels may be sampled only by state, language, city tier and age band."
)


def find_protected(text: str) -> tuple[str, str] | None:
    """(trait, matched word) when `text` names a protected trait, else None."""
    for trait, pattern in _PATTERNS.items():
        if match := pattern.search(text):
            return trait, match.group(0)
    return None


def reject_protected(value: Any, path: str = "") -> None:
    """Raise ValueError if any key or string anywhere in `value` names a protected trait."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            found = find_protected(str(key).replace("_", " "))
            if found:
                raise ValueError(f"{path + str(key)}: " + PROTECTED_MESSAGE.format(trait=found[0], word=found[1]))
            reject_protected(item, f"{path}{key}.")
    elif isinstance(value, str):
        found = find_protected(value.replace("_", " "))
        if found:
            raise ValueError(f"{path.rstrip('.')}: " + PROTECTED_MESSAGE.format(trait=found[0], word=found[1]))
    elif isinstance(value, Sequence):
        for index, item in enumerate(value):
            reject_protected(item, f"{path}{index}.")


@dataclass(frozen=True)
class SampledParticipant:
    ordinal: int
    state_code: str
    language: str
    city_tier: str
    age_band: str
    traits: dict[str, str]  # style knobs only (population.TRAITS); never demographics

    def id(self, run_id: UUID) -> UUID:
        return uuid5(NAMESPACE_URL, f"omnicult-panel-participant:{run_id}:{self.ordinal}")


def balanced_column(values: Sequence[str], size: int, shares: Sequence[float] | None, seed: str) -> list[str]:
    """`size` entries drawn from `values` in proportion to `shares` (equal by default), shuffled with the seed."""
    counts = allocate(list(shares) if shares else [1.0] * len(values), size)
    column = [v for v, c in zip(values, counts) for _ in range(c)]
    random.Random(seed).shuffle(column)
    return column


def sample_panel(
    *, size: int, states: Sequence[str], languages: Sequence[str], city_tiers: Sequence[str], age_bands: Sequence[str],
    seed: int, weights: Mapping[str, Mapping[str, float]] | None = None,
) -> list[SampledParticipant]:
    """Deterministic panel of `size` participants. `weights[dimension][value]` sets that value's share (default equal)."""
    weights = weights or {}
    dims = {"states": states, "languages": languages, "city_tiers": city_tiers, "age_bands": age_bands}
    columns = {}
    for name, values in dims.items():
        if not values:
            raise ValueError(f"{name} must list at least one value.")
        shares = [weights[name][v] for v in values] if name in weights else None
        columns[name] = balanced_column(values, size, shares, f"{SAMPLING_VERSION}:{seed}:{name}")
    people = []
    for k in range(size):
        rng = random.Random(f"{SAMPLING_VERSION}:{seed}:traits:{k}")
        people.append(SampledParticipant(
            ordinal=k, state_code=columns["states"][k], language=columns["languages"][k],
            city_tier=columns["city_tiers"][k], age_band=columns["age_bands"][k],
            traits={key: rng.choice(options) for key, options in TRAITS.items()},
        ))
    return people


def marginal_counts(people: Sequence[Any]) -> dict[str, dict[str, int]]:
    """Counts per value for each dimension; accepts SampledParticipant or any object with the same attributes."""
    out: dict[str, dict[str, int]] = {"states": {}, "languages": {}, "city_tiers": {}, "age_bands": {}}
    for p in people:
        for name, value in (("states", p.state_code), ("languages", p.language), ("city_tiers", p.city_tier),
                            ("age_bands", p.age_band)):
            out[name][value] = out[name].get(value, 0) + 1
    return out


def describe(state_name: str, language_name: str, city_tier: str, age_band: str) -> str:
    return f"{state_name}; reads and speaks {language_name}; {CITY_TIER_LABELS[city_tier]}; age band {age_band}"
