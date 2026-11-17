"""Deterministic confidence and conflict rules (handoff 6.2 and 6.3, docs/CONTRACTS_PHASE1.md section 3).

Confidence is computed here and nowhere else: no source and no model chooses it.

    Low       one observed source (or none), or a model interpretation only. Also: several sources that share one
              independence group, and independent sources whose newest is two years old or more.
    Moderate  at least two observed sources from different independence groups that agree, and the newest of them is
              less than two years old.
    High      Moderate plus a native-reviewer confirmation or agreement with real campaign results.
    Synthetic claims never exceed Moderate, whatever else is attached to them.

Assumptions, stated because they decide edge cases:
  * Sources attached to one claim all support that claim's value ("agree"); a source that disagrees belongs to a
    different claim, and the pair is reported by `detect_conflicts`.
  * A source's date is `published_at`, or the retrieval date when the source has no publication date (a live API
    reflects the world at retrieval). Old census data therefore stays Low unless corroborated by a fresher source.
  * `reviewer` and `campaign_result` sources are confirmations, not independent observations; they are excluded from
    the observed count and raise a Moderate claim to High through the flags the caller derives from them.
  * `gemini_grounding` is a model-found citation; it counts as an observed source only when it carries the quoted
    page text (`excerpt`), as M-05 requires.
"""

import json
from collections import defaultdict
from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Generic, Literal, Protocol, TypeVar

from app.schemas.claims import ClaimKind, ConfidenceLevel, ClaimScope

FRESHNESS_YEARS = 2
CONFIRMATION_SOURCES = frozenset({"reviewer", "campaign_result"})
KIND_RANK: dict[str, int] = {"observed": 0, "calculated": 1, "synthetic": 2, "interpretation": 3, "unverified": 4}
CONFIDENCE_RANK: dict[str, int] = {"high": 0, "moderate": 1, "low": 2}


class SourceLike(Protocol):
    """Satisfied by `SourceRef` and by the `claim_sources` ORM rows."""

    source_type: str
    independence_group: str
    published_at: date | None
    retrieved_at: datetime
    excerpt: str | None


class ClaimLike(Protocol):
    """Satisfied by `ClaimDraft` and by the `claims` ORM rows."""

    subject: str
    attribute: str
    value: Any


C = TypeVar("C", bound=ClaimLike)


def source_date(source: SourceLike) -> date:
    return source.published_at or source.retrieved_at.date()


def is_observation(source: SourceLike) -> bool:
    """Whether a source counts toward the independent, observed total."""
    if source.source_type in CONFIRMATION_SOURCES:
        return False
    if source.source_type == "gemini_grounding":
        return bool((source.excerpt or "").strip())
    return True


def freshness_cutoff(now: datetime) -> date:
    """A source dated after this day is less than two years old."""
    today = now.date()
    try:
        return today.replace(year=today.year - FRESHNESS_YEARS)
    except ValueError:  # 29 February
        return today.replace(year=today.year - FRESHNESS_YEARS, day=28)


def newest_observed_date(sources: Iterable[SourceLike]) -> date | None:
    dates = [source_date(s) for s in sources if is_observation(s)]
    return max(dates) if dates else None


def is_stale(sources: Iterable[SourceLike], *, now: datetime) -> bool:
    """True when no observed source is less than two years old (or none exists)."""
    newest = newest_observed_date(sources)
    return newest is None or newest <= freshness_cutoff(now)


def compute_confidence(
    kind: ClaimKind,
    sources: Sequence[SourceLike],
    *,
    now: datetime,
    reviewer_confirmed: bool = False,
    campaign_agreement: bool = False,
) -> tuple[ConfidenceLevel, str]:
    """Return (level, human-readable reason). The reason always names the rule that decided the level."""
    if kind in ("interpretation", "unverified"):
        what = "A model interpretation" if kind == "interpretation" else "An unverified statement"
        return "low", f"{what} without independent observed sources; it stays Low until sources support it."
    observed = [s for s in sources if is_observation(s)]
    if not observed:
        return "low", "No observed source supports this claim."
    groups = sorted({s.independence_group for s in observed})
    if len(groups) < 2:
        if len(observed) == 1:
            return "low", f"One source ({observed[0].source_type}); Moderate needs two independent observed sources."
        return "low", (
            f"{len(observed)} sources, but all belong to one independence group ({groups[0]}); "
            "they count as one source."
        )
    newest = max(source_date(s) for s in observed)
    if newest <= freshness_cutoff(now):
        return "low", (
            f"{len(groups)} independent sources agree, but the newest is from {newest.isoformat()}, "
            f"{FRESHNESS_YEARS} years old or more; Moderate needs a source under {FRESHNESS_YEARS} years old."
        )
    level: ConfidenceLevel = "moderate"
    reason = (
        f"{len(groups)} independent observed sources agree ({', '.join(groups)}); "
        f"the newest is from {newest.isoformat()}."
    )
    if reviewer_confirmed or campaign_agreement:
        level = "high"
        confirmation = "a native reviewer confirmed it" if reviewer_confirmed else "it agrees with real campaign results"
        reason += f" Raised to High because {confirmation}."
    if kind == "synthetic" and level == "high":
        level = "moderate"
        reason += " Capped at Moderate: synthetic panel results can never exceed Moderate."
    elif kind == "synthetic":
        reason += " Synthetic claims never exceed Moderate."
    return level, reason


# --- values, scopes, conflicts ------------------------------------------------------------


def normalized_value(value: Any) -> Any:
    """A comparison form: strings trimmed and case-folded, numbers by value, lists unordered, dict keys sorted."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    if isinstance(value, dict):
        return {str(k): normalized_value(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, list | tuple | set | frozenset):
        # ponytail: lists are treated as unordered sets; an order-sensitive attribute needs its own comparison.
        return sorted((normalized_value(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True, default=str))
    return str(value)


def value_fingerprint(value: Any) -> str:
    return json.dumps(normalized_value(value), sort_keys=True, separators=(",", ":"), default=str)


def scope_key(scope: ClaimScope | dict[str, Any]) -> str:
    data = scope.model_dump() if isinstance(scope, ClaimScope) else dict(scope)
    return json.dumps({k: data.get(k) for k in sorted(ClaimScope.model_fields)}, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class ConflictDraft(Generic[C]):
    """Two claims about the same subject, attribute and scope whose values differ. Both are preserved."""

    claim_a: C
    claim_b: C
    reason: str


def detect_conflicts(claims: Sequence[C]) -> list[ConflictDraft[C]]:
    """Pairs of claims with the same subject, attribute and scope but different values.

    `claims` may be `ClaimDraft`s or stored claims (anything with subject, attribute, scope and value). Claims with equal
    values never conflict. The result order follows the input order, so it is deterministic.
    """
    groups: dict[Hashable, list[C]] = defaultdict(list)
    for claim in claims:
        groups[(claim.subject, claim.attribute, scope_key(claim.scope))].append(claim)  # type: ignore[attr-defined]
    found: list[ConflictDraft[C]] = []
    for (subject, attribute, _), members in groups.items():
        for i, first in enumerate(members):
            for second in members[i + 1 :]:
                if value_fingerprint(first.value) != value_fingerprint(second.value):
                    found.append(
                        ConflictDraft(
                            first, second,
                            f"Sources disagree on {attribute} for {subject}: "
                            f"{_short(first.value)} versus {_short(second.value)}.",
                        )
                    )
    return found


def _short(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)
    return repr(text if len(text) <= 80 else text[:77] + "...")


# --- which value is currently used --------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    kind: str
    confidence: str
    newest: date | None
    specificity: int  # number of scope fields set; a narrower claim is the more specific one


def recommend_selection(a: Candidate, b: Candidate) -> tuple[Literal["a", "b"], str]:
    """Which of two conflicting values to use while the conflict is open, and why (authority, then confidence,
    then recency, then specificity). A reviewer can always switch it; the other value is never deleted."""
    rules: tuple[tuple[str, Any], ...] = (
        ("it is better evidenced (observed evidence outranks interpretation)", lambda c: KIND_RANK.get(c.kind, 9)),
        ("it has the higher confidence", lambda c: CONFIDENCE_RANK.get(c.confidence, 9)),
        ("its newest source is more recent", lambda c: -(c.newest.toordinal() if c.newest else 0)),
        ("its scope is more specific", lambda c: -c.specificity),
    )
    for reason, key in rules:
        ka, kb = key(a), key(b)
        if ka != kb:
            return ("a" if ka < kb else "b"), f"Used because {reason}."
    return "a", "No rule separates the two values; the first recorded value is used until a reviewer decides."
