"""Neutral result models, typed errors and the CultureSource protocol (docs/CONTRACTS_PHASE1.md section 4).

A source that does not support an operation returns an empty result, never invented data. Methods raise
CultureSourceError for provider problems; CultureService turns those into call-log entries and partial results.
"""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from app.schemas.claims import ClaimDraft, SourceRef

Operation = Literal["resolve_entity", "related_signals", "audience_facts", "trend_series", "moments"]
ALL_OPERATIONS: frozenset[Operation] = frozenset(
    {"resolve_entity", "related_signals", "audience_facts", "trend_series", "moments"}
)


def now_utc() -> datetime:
    return datetime.now(UTC)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def request_hash(source: str, operation: str, request: dict[str, Any]) -> str:
    """SHA-256 of the canonical request. Requests never hold secrets (keys go in headers/params the adapter adds)."""
    return hashlib.sha256(canonical_json({"source": source, "operation": operation, "request": request}).encode()).hexdigest()


# --- typed errors ------------------------------------------------------------------------------------------------


class CultureSourceError(Exception):
    """Base class. `kind` is stable text for logs and the UI; `retryable` says whether a later retry may succeed."""

    kind = "error"
    retryable = False
    payload: Any = None  # the provider's JSON error body when it sent one (HttpFetcher sets it on a non-retried 4xx), else None

    def __init__(self, source: str, operation: str, message: str, *, status_code: int | None = None) -> None:
        super().__init__(f"{source}.{operation}: {message}")
        self.source, self.operation, self.status_code = source, operation, status_code


class SourceTimeout(CultureSourceError):
    kind, retryable = "timeout", True


class SourceNetworkError(CultureSourceError):
    kind, retryable = "network", True


class SourceRateLimited(CultureSourceError):
    kind, retryable = "rate_limited", True


class SourceHttpError(CultureSourceError):
    kind = "http"


class SourceAuthError(CultureSourceError):
    kind = "auth"


class SourceValidationError(CultureSourceError):
    """The response was not the shape the adapter expects (schema drift or a malformed body)."""

    kind = "validation"


class SourceNotConfigured(CultureSourceError):
    kind = "not_configured"


# --- descriptor and results --------------------------------------------------------------------------------------


class SourceDescriptor(BaseModel):
    """What MASTER_PROMPT 5.4 requires every adapter to declare."""

    name: str
    source_type: Literal[
        "knowledge_graph", "trend_series", "event_feed", "public_dataset", "calendar", "curated_reference",
        "grounded_llm", "fixture",
    ]
    supported_operations: frozenset[Operation]
    scope: str
    coverage_limitations: list[str]
    cache_policy: dict[str, timedelta] = {}  # operation -> TTL; operations absent here are not cached
    requires_credentials: bool = False


class EntityCandidate(BaseModel):
    entity_id: str  # e.g. a Wikidata Q-id
    label: str
    description: str | None = None
    language: str | None = None  # language of the label that matched
    match_type: Literal["label", "alias", "other"] = "other"
    matched_text: str | None = None
    url: str | None = None
    source: str


class EntityResolution(BaseModel):
    """`resolved`: exactly one candidate matches the query exactly. `ambiguous`: several plausible candidates, or
    none matches exactly; the caller must ask or show the alternatives, never pick silently. `unresolved`: nothing."""

    status: Literal["resolved", "ambiguous", "unresolved"]
    query: str
    language: str | None = None
    region_code: str | None = None
    entity: EntityCandidate | None = None
    candidates: list[EntityCandidate] = []
    sources: list[str] = []
    retrieved_at: datetime
    note: str | None = None


def _norm(text: str | None) -> str:
    return " ".join((text or "").casefold().split())


def decide_resolution(
    query: str, candidates: list[EntityCandidate], *, language: str | None, region_code: str | None,
    sources: list[str], retrieved_at: datetime,
) -> EntityResolution:
    """The shared ambiguity rule: resolve only when exactly one candidate matches the query by label or alias.

    Two exact matches (for example a festival and a dish with the same name, or a label that is also another
    item's alias) are both kept as candidates. A near match alone (no exact one) is never promoted either."""
    base = dict(query=query, language=language, region_code=region_code, sources=sources, retrieved_at=retrieved_at)
    if not candidates:
        return EntityResolution(status="unresolved", candidates=[], note="No candidate found.", **base)
    wanted = _norm(query)
    exact = [c for c in candidates if _norm(c.label) == wanted or _norm(c.matched_text) == wanted]
    if len(exact) == 1:
        return EntityResolution(status="resolved", entity=exact[0], candidates=candidates, **base)
    note = (f"{len(exact)} candidates match the query exactly; confirm which is meant." if exact
            else "No candidate matches the query exactly; confirm which is meant.")
    return EntityResolution(status="ambiguous", candidates=candidates, note=note, **base)


class TrendPoint(BaseModel):
    date: date
    views: int


class TrendEdition(BaseModel):
    language: str
    project: str  # e.g. "ta.wikipedia"
    article: str
    points: list[TrendPoint]
    total: int
    baseline: list[TrendPoint] | None = None  # the whole edition's views per month, when read (Trend Radar); None otherwise


class TrendSeries(BaseModel):
    """Attention over time, not demand: pageviews measure reading, not purchase intent or market size."""

    term: str
    region_code: str | None = None
    unit: str = "pageviews"
    granularity: Literal["daily", "monthly"] = "daily"
    start: date
    end: date
    editions: list[TrendEdition]
    caveat: str
    source: SourceRef


class CallLogRecord(BaseModel):
    source: str
    operation: str
    request_hash: str
    retrieved_at: datetime
    status: Literal["ok", "empty", "error"]
    cached: bool = False
    result_count: int = 0
    duration_ms: int = 0
    error_type: str | None = None
    error: str | None = None


class CultureSource(Protocol):
    name: str
    mode: Literal["live", "fixture"]
    descriptor: SourceDescriptor

    def is_configured(self) -> bool: ...

    async def resolve_entity(self, query: str, *, language: str | None = None,
                             region_code: str | None = None) -> EntityResolution: ...

    async def related_signals(self, entity_id: str, *, region_code: str, limit: int = 10) -> list[ClaimDraft]: ...

    async def audience_facts(self, region_code: str) -> list[ClaimDraft]: ...

    async def trend_series(self, term: str, *, region_code: str, start: date, end: date) -> TrendSeries | None: ...

    async def moments(self, region_code: str, *, year: int) -> list[ClaimDraft]: ...


class SourceBase:
    """Default no-op operations, so an adapter implements only what it supports (the rest return empty results)."""

    name: str
    mode: Literal["live", "fixture"] = "live"
    descriptor: SourceDescriptor

    def is_configured(self) -> bool:
        return True

    async def resolve_entity(self, query: str, *, language: str | None = None,
                             region_code: str | None = None) -> EntityResolution:
        return EntityResolution(status="unresolved", query=query, language=language, region_code=region_code,
                                retrieved_at=now_utc(), note=f"{self.name} does not resolve entities.")

    async def related_signals(self, entity_id: str, *, region_code: str, limit: int = 10) -> list[ClaimDraft]:
        return []

    async def audience_facts(self, region_code: str) -> list[ClaimDraft]:
        return []

    async def trend_series(self, term: str, *, region_code: str, start: date, end: date) -> TrendSeries | None:
        return None

    async def moments(self, region_code: str, *, year: int) -> list[ClaimDraft]:
        return []
