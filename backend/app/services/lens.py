"""Market Lens builds: gather a region's claims from the culture sources, store them, and keep a versioned record.

Demo campaigns use the deterministic fixture source only (no network, no model); live campaigns use the live adapters
with their cool-downs. Claims are stored through `upsert_claims`, so provenance, computed confidence and conflicts are
the same as everywhere else. Nothing is cached in the database: the process-wide cache below only spares the free public
APIs repeated requests. The culture call log is stored per workspace so Data Health can report attempts and errors.
"""

import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import Conflict, NotFound, RateLimited, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.integrations.culture import CultureService, InMemoryCacheStore, RegionProfile, RegionProfileBuilder, build_culture_service
from app.schemas import lens as v
from app.schemas.common import ErrorDetail
from app.services import data_health
from app.services.audit import record_audit
from app.services.claims import upsert_claims
from app.services.common import get_owned, require_writable

logger = logging.getLogger(__name__)

LIVE_MAX_REGIONS = 6
GROUNDING_NAME = "gemini_grounding"
_PROCESS_CACHE = InMemoryCacheStore()  # live culture results, process-wide: repeated builds do not repeat free API calls
_RUNNING: set[tuple[UUID, str, str]] = set()  # (workspace, region, mode) builds in progress in this process


@dataclass(frozen=True)
class LensContext:
    """What every Lens request needs: who asks, which campaign, its workspace, and the data mode of its brand."""

    user_id: UUID
    campaign_id: UUID
    project_id: UUID
    workspace_id: UUID
    mode: str


async def lens_context(user_id: UUID, campaign_id: UUID, *, writable: bool = False) -> LensContext:
    """404 for a campaign in a workspace the caller cannot reach; 403 on writes for a read-only role."""
    async with read_session() as s:
        _, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        if writable:
            require_writable(project)
        if project.workspace_id is None:
            raise Conflict("This brand has no workspace yet, so no shared evidence can be stored for it.")
        return LensContext(user_id, campaign_id, project.id, project.workspace_id, project.mode)


def mode_label(mode: str) -> str:
    if mode == "demo":
        return ("Demo fixtures. Claims are labelled DEMO FIXTURE: the same offline datasets live mode reads, with recorded entity "
                "searches and a synthetic trend series. Not a live retrieval.")
    return "Live sources. Each claim was retrieved from the sources shown, on the dates shown."


async def region_names(s: AsyncSession) -> dict[str, str]:
    return {code: name for code, name in (await s.execute(select(m.Region.code, m.Region.name).where(m.Region.is_active))).all()}


# --- the service a build uses (tests replace this) -----------------------------------------------------------------


def make_culture_service(settings: Settings, mode: str, *, include_grounding: bool) -> CultureService:
    """demo: fixture source only. live: every adapter; grounded research only when asked for and configured."""
    if mode == "demo":
        return build_culture_service(settings, mode="demo")
    research = None
    if include_grounding:
        from app.llm import LLMGateway

        try:
            research = LLMGateway(settings).capability("grounded_research")
        except Exception:  # noqa: BLE001 - a missing capability is reported as a skipped source, not a crash
            logger.warning("grounded_research capability unavailable")
    return build_culture_service(settings, mode="live", research=research, cache=_PROCESS_CACHE)


# --- views -------------------------------------------------------------------------------------------------------


def build_view(row: m.LensBuild, region_name: str, calls: list[m.CultureCall] | None = None) -> v.LensBuildView:
    return v.LensBuildView(
        id=row.id, campaign_id=row.campaign_id, workspace_id=row.workspace_id, region_code=row.region_code, region_name=region_name,
        mode=row.mode,  # type: ignore[arg-type]
        version=row.version, status=row.status,  # type: ignore[arg-type]
        years=row.years, include_trends=bool(row.options.get("include_trends")),
        include_grounding=bool(row.options.get("include_grounding")), claim_count=row.claim_count,
        created_claims=row.created_claims, updated_claims=row.updated_claims, conflicts_opened=row.conflicts_opened,
        rejected_claims=row.rejected_claims, categories=row.categories, gaps=row.gaps, sources_skipped=row.sources_skipped,
        error=row.error, started_at=row.started_at, finished_at=row.finished_at,
        calls=[
            v.LensCallView(
                source=c.source, operation=c.operation, status=c.status,  # type: ignore[arg-type]
                cached=c.cached, result_count=c.result_count, duration_ms=c.duration_ms, error_type=c.error_type, error=c.error,
                retrieved_at=c.retrieved_at)
            for c in sorted(calls or [], key=lambda c: (c.retrieved_at, c.source, c.operation))
        ],
    )


async def latest_builds(s: AsyncSession, workspace_id: UUID, mode: str) -> dict[str, m.LensBuild]:
    """The newest build per region for a workspace and mode."""
    rows = (await s.execute(
        select(m.LensBuild).where(m.LensBuild.workspace_id == workspace_id, m.LensBuild.mode == mode)
        .order_by(m.LensBuild.region_code, m.LensBuild.version)
    )).scalars()
    return {row.region_code: row for row in rows}  # ascending version: the last one per region wins


async def list_builds(ctx: LensContext, region_code: str | None, limit: int, offset: int) -> v.LensBuildPage:
    async with read_session() as s:
        names = await region_names(s)
        stmt = select(m.LensBuild).where(m.LensBuild.workspace_id == ctx.workspace_id, m.LensBuild.mode == ctx.mode)
        if region_code is not None:
            stmt = stmt.where(m.LensBuild.region_code == region_code)
        total = await s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = list((await s.execute(
            stmt.order_by(m.LensBuild.finished_at.desc(), m.LensBuild.version.desc()).limit(limit).offset(offset))).scalars())
    return v.LensBuildPage(items=[build_view(r, names.get(r.region_code, r.region_code)) for r in rows], limit=limit, offset=offset, total=int(total))


# --- building ------------------------------------------------------------------------------------------------------


def _bad(field: str, message: str) -> ValidationFailed:
    return ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message=message)])


def _years(requested: list[int] | None, today_year: int) -> list[int]:
    return sorted(set(requested)) if requested else [today_year, today_year + 1]


def _gaps(profile: RegionProfile, *, include_grounding: bool) -> tuple[list[str], list[str]]:
    """Gaps and skipped sources, leaving out grounded research when nobody asked for it (it is opt-in, not missing)."""
    skipped = [name for name in profile.sources_skipped if include_grounding or name != GROUNDING_NAME]
    gaps = [g for g in profile.gaps if include_grounding or f"'{GROUNDING_NAME}'" not in g]
    return gaps, skipped


def _status(profile: RegionProfile, skipped: list[str]) -> str:
    failed = any(call.status == "error" for call in profile.call_log)
    return "partial" if failed or skipped else "completed"


async def _check_interval(ctx: LensContext, codes: list[str], settings: Settings) -> None:
    """Live builds of the same region are spaced out: Wikimedia's APIs are free and shared, and a repeat adds nothing."""
    if ctx.mode != "live" or settings.lens_live_build_min_interval_seconds <= 0:
        return
    async with read_session() as s:
        latest = await latest_builds(s, ctx.workspace_id, ctx.mode)
    now = utcnow()
    for code in codes:
        row = latest.get(code)
        if row is None or row.status == "failed":
            continue
        wait = settings.lens_live_build_min_interval_seconds - (now - row.finished_at).total_seconds()
        if wait > 0:
            raise RateLimited(f"{code} was built {int(settings.lens_live_build_min_interval_seconds - wait)} seconds ago. "
                              f"Live builds of one state are spaced {settings.lens_live_build_min_interval_seconds} seconds apart; "
                              f"try again in {int(wait) + 1} seconds.")


async def build_regions(user_id: UUID, campaign_id: UUID, body: v.LensBuildRequest) -> v.LensBuildBatch:
    settings = get_settings()
    ctx = await lens_context(user_id, campaign_id, writable=True)
    codes = list(dict.fromkeys(body.region_codes))
    async with read_session() as s:
        names = await region_names(s)
    unknown = [c for c in codes if c not in names]
    if unknown:
        raise NotFound("Region was not found: " + ", ".join(unknown) + ".")
    if ctx.mode == "live" and len(codes) > LIVE_MAX_REGIONS:
        raise _bad("region_codes", f"A live build takes at most {LIVE_MAX_REGIONS} states per request; it calls public APIs.")
    if body.include_grounding and ctx.mode == "demo":
        raise _bad("include_grounding", "Grounded research is a live source; demo mode uses fixtures only.")
    keys = [(ctx.workspace_id, code, ctx.mode) for code in codes]
    if any(key in _RUNNING for key in keys):
        raise Conflict("A build for one of these states is already running.")
    _RUNNING.update(keys)  # no await between the check and this line: two requests cannot both pass
    try:
        await _check_interval(ctx, codes, settings)
        builds = [await _build_one(ctx, code, names[code], body, settings) for code in codes]
    finally:
        _RUNNING.difference_update(keys)
    return v.LensBuildBatch(builds=builds)


async def _build_one(ctx: LensContext, code: str, name: str, body: v.LensBuildRequest, settings: Settings) -> v.LensBuildView:
    started = utcnow()
    years = _years(body.years, started.year)
    include_grounding = body.include_grounding and ctx.mode == "live"
    service = make_culture_service(settings, ctx.mode, include_grounding=include_grounding)
    profile: RegionProfile | None = None
    error: str | None = None
    try:
        async with asyncio.timeout(settings.lens_build_timeout_seconds):
            profile = await RegionProfileBuilder(service).build(
                code, years=tuple(years), trend_terms=None if body.include_trends else [], today=started.date())
    except TimeoutError:
        error = f"The build ran longer than {settings.lens_build_timeout_seconds} seconds and was stopped; nothing was stored."
    except Exception as exc:  # noqa: BLE001 - a source bug must not become a 500 with details; it is logged and reported
        logger.exception("lens build failed for %s", code)
        error = f"The build failed ({type(exc).__name__}); nothing was stored."
    options = {"include_trends": body.include_trends, "include_grounding": include_grounding}
    async with session() as s, s.begin():
        version = int(await s.scalar(select(func.max(m.LensBuild.version)).where(
            m.LensBuild.workspace_id == ctx.workspace_id, m.LensBuild.region_code == code, m.LensBuild.mode == ctx.mode)) or 0) + 1
        row = m.LensBuild(
            id=uuid4(), workspace_id=ctx.workspace_id, project_id=ctx.project_id, campaign_id=ctx.campaign_id, region_code=code,
            mode=ctx.mode, version=version, status="failed", years=years, options=options, categories={}, gaps=[],
            sources_skipped=[], error=error, created_by=ctx.user_id, started_at=started, finished_at=utcnow())
        calls: list[m.CultureCall] = []
        if profile is not None:
            claims = profile.all_claims()
            stored = await upsert_claims(s, claims, workspace_id=ctx.workspace_id, mode=ctx.mode)
            gaps, skipped = _gaps(profile, include_grounding=include_grounding)
            if include_grounding and GROUNDING_NAME in skipped:
                gaps = [*gaps, "Grounded research was requested but is not configured on this server."]
            row.status = _status(profile, skipped)
            row.claim_count, row.created_claims, row.updated_claims = len(claims), stored.created, stored.updated
            row.conflicts_opened, row.rejected_claims = stored.conflicts_opened, len(stored.rejected)
            row.categories = {c: len(items) for c, items in profile.claims_by_category.items() if items}
            row.gaps = gaps + [f"A claim was not stored: {why}" for _, why in stored.rejected]
            row.sources_skipped = skipped
            row.finished_at = utcnow()
            calls = [
                m.CultureCall(
                    id=uuid4(), workspace_id=ctx.workspace_id, build_id=row.id, mode=ctx.mode, source=c.source, operation=c.operation,
                    request_hash=c.request_hash, status=c.status, cached=c.cached, result_count=c.result_count,
                    duration_ms=c.duration_ms, error_type=c.error_type, error=c.error, retrieved_at=c.retrieved_at)
                for c in profile.call_log
            ]
        s.add(row)
        await s.flush()
        s.add_all(calls)
        await record_audit(
            s, action="lens.build", target_type="lens_build", target_id=str(row.id), workspace_id=ctx.workspace_id,
            actor_user_id=ctx.user_id, detail={"region": code, "mode": ctx.mode, "status": row.status, "claims": row.claim_count})
        await s.flush()
        return build_view(row, name, calls)


async def build_detail(ctx: LensContext, region_code: str, build_id: UUID) -> v.LensBuildView:
    async with read_session() as s:
        row = await s.scalar(select(m.LensBuild).where(
            m.LensBuild.id == build_id, m.LensBuild.workspace_id == ctx.workspace_id, m.LensBuild.region_code == region_code))
        if row is None:
            raise NotFound("Build was not found.")
        calls = list((await s.execute(select(m.CultureCall).where(m.CultureCall.build_id == row.id))).scalars())
        names = await region_names(s)
    return build_view(row, names.get(row.region_code, row.region_code), calls)


# --- Data Health: the culture call log ---------------------------------------------------------------------------------

# Adapter names (culture call log) -> the claim source types Data Health groups by. A curated claim cites Wikipedia or a
# government page, so both source types read the curated adapter's calls.
CALL_SOURCES: dict[str, tuple[str, ...]] = {
    "wikidata": ("wikidata",),
    "wikipedia": ("curated",),
    "wikipedia_pageviews": ("wikipedia_pageviews",),
    "holidays_package": ("holidays_calendar",),
    "census_2011": ("census_2011",),
    "curated_reference": ("curated",),
}


def _reader(sources: tuple[str, ...]) -> data_health.CallLogReader:
    async def read(s: AsyncSession, workspace_id: UUID) -> data_health.CallStats:
        """Real calls only: calls answered from the cache made no request, and demo fixtures call nothing."""
        where = (
            m.CultureCall.workspace_id == workspace_id, m.CultureCall.mode == "live", m.CultureCall.cached.is_(False),
            m.CultureCall.source.in_(sources))
        attempts = int(await s.scalar(select(func.count(m.CultureCall.id)).where(*where)) or 0)
        failed = int(await s.scalar(select(func.count(m.CultureCall.id)).where(*where, m.CultureCall.status == "error")) or 0)
        last = await s.scalar(select(func.max(m.CultureCall.retrieved_at)).where(*where))
        last_error = (await s.execute(
            select(m.CultureCall.retrieved_at, m.CultureCall.error_type).where(*where, m.CultureCall.status == "error")
            .order_by(m.CultureCall.retrieved_at.desc()).limit(1))).first()
        return data_health.CallStats(attempts, failed, last, (last_error[0], last_error[1]) if last_error else None)

    return read


for _source_type, _adapters in CALL_SOURCES.items():
    data_health.register_call_log(_source_type, _reader(_adapters))
