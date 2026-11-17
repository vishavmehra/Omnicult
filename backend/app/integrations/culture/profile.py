"""RegionProfileBuilder: gather claims for one region from every configured source, grouped by category.

The builder only collects and merges; it never sets confidence (data-auth's compute_confidence does) and never
resolves a disagreement. Claims about the same subject, attribute and scope whose values are equal are merged into one
claim with all sources (the corroboration the Moderate rule needs); claims whose values differ stay separate, so a
conflict card can show both. Categories with no claim, sources that failed and sources that are not configured are
listed in `gaps`, so a weak region looks weak.
"""

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, get_args
from urllib.parse import unquote, urlparse

from pydantic import BaseModel

from app.integrations.culture.adapters.wikipedia_pageviews import series_to_claim
from app.integrations.culture.base import CallLogRecord
from app.integrations.culture.regions import region_for
from app.integrations.culture.service import CultureService
from app.schemas.claims import ClaimCategory, ClaimDraft

# The categories a region profile reports (docs/CONTRACTS_PHASE1.md ClaimCategory minus demographic and media).
PROFILE_CATEGORIES: tuple[str, ...] = (
    "language", "script", "festival", "moment", "food", "colour", "symbol", "humour", "family", "custom", "sensitivity",
    "trend",
)
assert set(PROFILE_CATEGORIES) <= set(get_args(ClaimCategory))


class RegionProfile(BaseModel):
    region_code: str
    region_name: str
    mode: Literal["live", "fixture"]
    generated_at: datetime
    claims_by_category: dict[str, list[ClaimDraft]]
    call_log: list[CallLogRecord]
    sources_skipped: list[str]  # adapters that are not configured
    gaps: list[str]

    def all_claims(self) -> list[ClaimDraft]:
        return [c for category in self.claims_by_category.values() for c in category]


def _fingerprint(value: Any) -> str:
    """Equal values compare equal regardless of case, spacing, int/float and key order."""
    def norm(v: Any) -> Any:
        if isinstance(v, bool) or v is None:
            return v
        if isinstance(v, int | float):
            return float(v)
        if isinstance(v, str):
            return " ".join(v.casefold().split())
        if isinstance(v, dict):
            return {str(k): norm(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}
        if isinstance(v, list | tuple):
            return sorted((norm(x) for x in v), key=lambda x: json.dumps(x, sort_keys=True, default=str))
        return str(v)
    return json.dumps(norm(value), sort_keys=True, separators=(",", ":"), default=str)


def merge_corroborating(claims: list[ClaimDraft]) -> list[ClaimDraft]:
    """Merge claims with the same subject, attribute, scope and value into one claim carrying all distinct sources."""
    merged: dict[tuple, ClaimDraft] = {}
    for claim in claims:
        key = (claim.subject, claim.attribute, claim.scope.model_dump_json(), _fingerprint(claim.value))
        if key not in merged:
            merged[key] = claim
            continue
        kept = merged[key]
        have = {(s.source_type, s.source_identifier) for s in kept.sources}
        extra = [s for s in claim.sources if (s.source_type, s.source_identifier) not in have]
        merged[key] = kept.model_copy(update={"sources": [*kept.sources, *extra]})
    return list(merged.values())


def wikipedia_titles(claims: list[ClaimDraft]) -> list[str]:
    """English Wikipedia article titles cited by festival claims, in claim order, without duplicates."""
    titles: list[str] = []
    for claim in claims:
        for source in claim.sources:
            if source.source_type == "wikipedia" and source.url and "en.wikipedia.org/wiki/" in source.url:
                title = unquote(urlparse(source.url).path.rsplit("/", 1)[-1]).replace("_", " ")
                if title not in titles:
                    titles.append(title)
    return titles


class RegionProfileBuilder:
    def __init__(self, service: CultureService) -> None:
        self.service = service

    async def build(self, region_code: str, *, years: tuple[int, ...] | None = None, trend_terms: list[str] | None = None,
                    max_trend_terms: int = 3, today: date | None = None) -> RegionProfile:
        today = today or datetime.now(UTC).date()
        years = years or (today.year, today.year + 1)
        region = region_for(region_code)
        log: list[CallLogRecord] = []
        svc = self.service
        facts, signals, *moment_lists = await asyncio.gather(
            svc.audience_facts(region_code, log=log),
            svc.related_signals(f"region:{region_code}", region_code=region_code, limit=1000, log=log),
            *(svc.moments(region_code, year=y, log=log) for y in years))
        claims = [*facts, *signals, *(c for lst in moment_lists for c in lst)]

        terms = trend_terms if trend_terms is not None else wikipedia_titles(
            [c for c in claims if c.category == "festival"])[:max_trend_terms]
        end = today.replace(day=1) - timedelta(days=1)  # last day of the previous month
        start = (end.replace(day=1) - timedelta(days=330)).replace(day=1)  # twelve whole months, monthly granularity
        for series_list in await asyncio.gather(*(
                svc.trend_series(t, region_code=region_code, start=start, end=end, log=log) for t in terms)):
            claims.extend(series_to_claim(s) for s in series_list)

        claims = merge_corroborating(claims)
        by_category: dict[str, list[ClaimDraft]] = {c: [] for c in PROFILE_CATEGORIES}
        for claim in claims:
            by_category.setdefault(claim.category, []).append(claim)
        return RegionProfile(
            region_code=region_code, region_name=region.name if region else region_code, mode=svc.mode,
            generated_at=datetime.now(UTC), claims_by_category=by_category, call_log=log,
            sources_skipped=svc.skipped_sources(), gaps=self._gaps(by_category, log, svc.skipped_sources()))

    @staticmethod
    def _gaps(by_category: dict[str, list[ClaimDraft]], log: list[CallLogRecord], skipped: list[str]) -> list[str]:
        gaps = [f"No claims for category '{c}'." for c in PROFILE_CATEGORIES if not by_category.get(c)]
        gaps += [f"{r.source}.{r.operation} failed ({r.error_type}); its claims are missing." for r in log if r.status == "error"]
        gaps += [f"Source '{name}' is not configured; its claims are missing." for name in skipped]
        return gaps
