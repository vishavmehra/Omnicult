"""Data Health (feature 53): is the regional evidence behind a workspace healthy, fresh, and broad enough?

Reads stored claims and their sources only; it never calls a source, so it cannot report a source as "up". Per source
type it shows the last stored retrieval, freshness against each claim's expiry, and what is known about attempts and
errors. Attempts are known only where a call log exists: `CALL_LOG_READERS` maps a source type to a reader, and the
built-in ones cover `gemini_grounding` and the AI provider `vertex_ai` (per capability) through `ai_usage_events`. Every
other source reports `attempts_logged: false` instead of a made-up zero. Per region it reuses the Evidence Meter, so coverage here equals coverage everywhere else.
"""

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.confidence import FRESHNESS_YEARS
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session
from app.schemas.common import DataMode
from app.schemas.proof import (
    CapabilityCallHealth,
    DataHealth,
    FreshnessRules,
    RegionCoverage,
    SourceCallError,
    SourceHealth,
)
from app.services.claims import (
    CATEGORIES,
    LIVE_STATUSES,
    _claim_stale,
    _claim_view,
    _open_conflicts_by_claim,
    _sources,
    compute_meter,
)
from app.services.identity import require_workspace_role

EXPIRED_SHARE = 0.5  # a source type is "expired" when at least this share of its claims is past expiry
NOT_LOGGED = "Retrieval attempts and errors for this source are not logged for this source; only stored retrievals are visible."
LIMITATIONS = [
    "Data Health reads stored copies; it never calls a source, so it cannot confirm that a source is reachable now.",
    "Freshness is judged per claim: past its stated expiry is expired; an observed-source date of two years or more is aging.",
    "A region with few or no claims is thin for lack of recorded evidence, which is not the same as nothing existing.",
]


@dataclass(frozen=True)
class CapabilityCalls:
    capability: str
    attempts: int
    errors: int
    last_success_at: datetime | None


@dataclass(frozen=True)
class CallStats:
    attempts: int
    errors: int
    last_attempt_at: datetime | None
    last_error: tuple[datetime, str | None] | None
    last_success_at: datetime | None = None
    by_capability: tuple[CapabilityCalls, ...] = ()


CallLogReader = Callable[[AsyncSession, UUID], Awaitable[CallStats]]
CALL_LOG_READERS: dict[str, CallLogReader] = {}


def register_call_log(source_type: str, reader: CallLogReader) -> None:
    """Plug in a call log for a source type (the culture stream registers its retrieval log here when it merges)."""
    CALL_LOG_READERS[source_type] = reader


async def _grounding_calls(s: AsyncSession, workspace_id: UUID) -> CallStats:
    where = (m.AiUsageEvent.capability == "grounded_research", m.AiUsageEvent.workspace_id == workspace_id)
    attempts = await s.scalar(select(func.count(m.AiUsageEvent.id)).where(*where)) or 0
    failed = await s.scalar(select(func.count(m.AiUsageEvent.id)).where(*where, m.AiUsageEvent.status != "ok")) or 0
    last = await s.scalar(select(func.max(m.AiUsageEvent.created_at)).where(*where))
    last_error = (await s.execute(
        select(m.AiUsageEvent.created_at, m.AiUsageEvent.error_code).where(*where, m.AiUsageEvent.status != "ok")
        .order_by(m.AiUsageEvent.created_at.desc()).limit(1)
    )).first()
    return CallStats(int(attempts), int(failed), last, (last_error[0], last_error[1]) if last_error else None)


register_call_log("gemini_grounding", _grounding_calls)

VERTEX_AI = "vertex_ai"


async def _vertex_calls(s: AsyncSession, workspace_id: UUID) -> CallStats:
    """Every recorded Google model call of the workspace (the gateway stores each request, failed attempts included, in
    `ai_usage_events` with provider `google`), per capability: attempts, errors and the last success. A call made outside a
    workspace scope carries no workspace and is not counted. When the backend is the Gemini Developer API instead of Vertex
    AI the rows are the same, so the source name is the deployment's intended provider."""
    e, failed = m.AiUsageEvent, m.AiUsageEvent.status != "ok"
    where = (e.provider == "google", e.workspace_id == workspace_id)
    rows = (await s.execute(
        select(
            e.capability, func.count(e.id), func.sum(case((failed, 1), else_=0)), func.max(case((e.status == "ok", e.created_at)))
        ).where(*where).group_by(e.capability).order_by(e.capability)
    )).all()
    by_capability = tuple(CapabilityCalls(cap, int(n), int(bad or 0), ok) for cap, n, bad, ok in rows)
    last = await s.scalar(select(func.max(e.created_at)).where(*where))
    last_error = (await s.execute(
        select(e.created_at, e.error_code).where(*where, failed).order_by(e.created_at.desc()).limit(1)
    )).first()
    successes = [c.last_success_at for c in by_capability if c.last_success_at]
    return CallStats(
        sum(c.attempts for c in by_capability), sum(c.errors for c in by_capability), last,
        (last_error[0], last_error[1]) if last_error else None, max(successes) if successes else None, by_capability,
    )


register_call_log(VERTEX_AI, _vertex_calls)


def freshness_label(claims: int, expired: int, aging: int) -> str:
    """unknown without claims; expired when at least half are past expiry; aging when any is expired or old; else fresh."""
    if claims == 0:
        return "unknown"
    if expired / claims >= EXPIRED_SHARE:
        return "expired"
    return "aging" if expired or aging else "fresh"


def claim_state(claim: m.Claim, sources: list[m.ClaimSource], now: datetime) -> str:
    if claim.expires_at is not None and claim.expires_at <= now:
        return "expired"
    return "aging" if _claim_stale(claim, sources, now) else "fresh"


def cache_state(live: int, fixture: int) -> str:
    if live and fixture:
        return "mixed"
    return "stored_live" if live else "fixture" if fixture else "none"


def _visible(workspace_id: UUID, mode: str) -> tuple:
    return (
        or_(m.Claim.workspace_id == workspace_id, m.Claim.workspace_id.is_(None)),
        m.Claim.mode == mode, m.Claim.status.in_(LIVE_STATUSES),
    )


def source_health(
    source_type: str, claims: list[m.Claim], sources: list[m.ClaimSource], states: dict[UUID, str],
    region_codes: list[str], stats: CallStats | None,
) -> SourceHealth:
    expired = sum(1 for c in claims if states[c.id] == "expired")
    aging = sum(1 for c in claims if states[c.id] == "aging")
    live = sum(1 for c in claims if c.mode == "live")
    dates = [s.retrieved_at for s in sources]
    notes = [] if stats is not None else [NOT_LOGGED]
    return SourceHealth(
        source_type=source_type, sources=len({(s.source_type, s.source_identifier) for s in sources}), claims=len(claims),
        live_claims=live, fixture_claims=len(claims) - live, cache_state=cache_state(live, len(claims) - live),  # type: ignore[arg-type]
        last_retrieved_at=max(dates) if dates else None, oldest_retrieved_at=min(dates) if dates else None,
        freshness=freshness_label(len(claims), expired, aging),  # type: ignore[arg-type]
        fresh_claims=len(claims) - expired - aging, aging_claims=aging, expired_claims=expired,
        attempts=stats.attempts if stats else None, errors=stats.errors if stats else None,
        last_attempt_at=stats.last_attempt_at if stats else None,
        last_error=SourceCallError(at=stats.last_error[0], code=stats.last_error[1]) if stats and stats.last_error else None,
        last_success_at=stats.last_success_at if stats else None,
        capabilities=[CapabilityCallHealth(capability=c.capability, attempts=c.attempts, errors=c.errors, last_success_at=c.last_success_at)
                      for c in stats.by_capability] if stats else [],
        attempts_logged=stats is not None, region_codes=sorted(region_codes), limitations=notes,
    )


async def workspace_data_health(user_id: UUID, workspace_id: UUID, mode: DataMode = "live") -> DataHealth:
    now = utcnow()
    async with read_session() as s:
        await require_workspace_role(s, user_id, workspace_id)
        claims = list((await s.execute(
            select(m.Claim).where(*_visible(workspace_id, mode)).order_by(m.Claim.category, m.Claim.attribute, m.Claim.id)
        )).scalars())
        by_claim: dict[UUID, list[m.ClaimSource]] = defaultdict(list)
        for src in await _sources(s, [c.id for c in claims]) if claims else []:
            by_claim[src.claim_id].append(src)
        regions = list((await s.execute(
            select(m.Region).where(m.Region.is_active).order_by(m.Region.name)
        )).scalars())
        code_of = {r.id: r.code for r in regions}
        stats = {}
        for source_type, reader in CALL_LOG_READERS.items():
            stats[source_type] = await reader(s, workspace_id)
        open_by_claim = await _open_conflicts_by_claim(s, workspace_id)
        review = (await s.execute(
            select(m.Conflict.claim_a_id, m.Conflict.claim_b_id)
            .where(m.Conflict.workspace_id == workspace_id, m.Conflict.status == "review_requested")
        )).all()

    states = {c.id: claim_state(c, by_claim[c.id], now) for c in claims}
    claims_of: dict[str, dict[UUID, m.Claim]] = defaultdict(dict)
    sources_of: dict[str, list[m.ClaimSource]] = defaultdict(list)
    for claim in claims:
        for src in by_claim[claim.id]:
            claims_of[src.source_type][claim.id] = claim
            sources_of[src.source_type].append(src)
    health = []
    for source_type in sorted(set(claims_of) | set(CALL_LOG_READERS)):
        covered = list(claims_of[source_type].values())
        codes = {code_of[c.region_id] for c in covered if c.region_id in code_of}
        health.append(source_health(source_type, covered, sources_of[source_type], states, sorted(codes), stats.get(source_type)))

    flagged = {claim_id for pair in review for claim_id in pair}
    coverage = []
    for region in regions:
        in_region = [c for c in claims if c.region_id == region.id]
        views = [_claim_view(c, by_claim, open_by_claim, now) for c in in_region]
        meter = compute_meter(region, workspace_id, mode, in_region, by_claim, views, flagged, now)
        types = sorted({src.source_type for c in in_region for src in by_claim[c.id]})
        coverage.append(RegionCoverage(
            region_code=region.code, region_name=region.name, strength=meter.strength, strength_reasons=meter.strength_reasons,
            claims=meter.claims, supported_claims=meter.supported_claims, categories_covered=meter.categories_covered,
            categories_total=meter.categories_total,
            missing_categories=[c.category for c in meter.coverage if c.supported_claims == 0],
            sources=meter.sources, source_types=types, newest_source_date=meter.freshness.newest_source_date,
            open_conflicts=meter.open_conflicts, stale_claims=meter.stale_claims,
        ))
    return DataHealth(
        workspace_id=workspace_id, mode=mode, generated_at=now, sources=health, regions=coverage,
        rules=FreshnessRules(
            expired_share_for_expired=EXPIRED_SHARE, stale_window_years=FRESHNESS_YEARS,
            notes=["Categories counted: " + ", ".join(CATEGORIES) + "."],
        ),
        limitations=LIMITATIONS,
    )

