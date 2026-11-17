"""Deterministic analytics for scoring version mvp-1 (contracts/README §8).

Scoring mvp-2 and the Readiness Board rules live in `scoring_v2` and `readiness` (Launch Room); mvp-1 is unchanged and
still scores stored adaptation evaluations.
"""

from app.analytics.scoring import (
    DEFINITIONS,
    SCORING_DEFINITION,
    SCORING_VERSION,
    aggregate,
    best_candidate,
    brief_confidence,
    comparability,
    constraint_checks,
    finding_confidence,
    is_source_observed,
    merge_terms,
    overall,
    rating_score,
    recommend,
    tradeoff,
)

__all__ = [
    "DEFINITIONS",
    "SCORING_DEFINITION",
    "SCORING_VERSION",
    "aggregate",
    "best_candidate",
    "brief_confidence",
    "comparability",
    "constraint_checks",
    "finding_confidence",
    "is_source_observed",
    "merge_terms",
    "overall",
    "rating_score",
    "recommend",
    "tradeoff",
]
