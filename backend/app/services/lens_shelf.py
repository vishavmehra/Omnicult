"""Category Shelf (Market Lens feature 14): the brands and products Wikidata records in the campaign's category, by state.

A refresh runs one discovery for the campaign's category pack (`integrations/culture/shelf.py`): Wikidata search, a batch read
of the items, a relevance rule on each item's class and description, and a walk up the located-in chain to the state. For the
best-referenced items placed in the campaign's states it also reads Wikipedia pageviews, with the same arithmetic as Trend
Radar. The discovery is stored as a versioned snapshot; a read shows the latest one.

Nothing is invented. A field Wikidata does not hold is listed under "not recorded" and left empty, a brand with no state link
is shown apart from the states, and an item the rule leaves out is listed with the reason. No price, sales, share or
advertising figure exists in these sources, so none is ever shown. A state link is where Wikidata places the headquarters or
origin, not where the item is sold. No model is involved.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import lens_trends as trends
from app.core.config import get_settings
from app.core.errors import Conflict, RateLimited, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.fixtures.lens_t3_demo import recorded_window
from app.integrations.culture import InMemoryCacheStore
from app.integrations.culture.base import CallLogRecord
from app.integrations.culture.regions import REGIONS, region_for
from app.integrations.culture.shelf import CategoryPack, ShelfDiscovery, ShelfEntity, pack_by_key
from app.schemas import lens_t3 as v
from app.schemas.common import ErrorDetail
from app.services import lens_t3 as shared
from app.services.audit import record_audit
from app.services.lens import LensContext, lens_context
from app.services.lens_trends import _codes, can_write, today

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 5
CACHE_TTL = timedelta(hours=24)
_CACHE = InMemoryCacheStore()
_RUNNING: set[tuple[UUID, str]] = set()

RANKING = ("Ordered by the number of Wikipedia language editions that have an article about the item, which is public reference "
           "and not sales, share or quality, then by name.")
RELEVANCE = ("Kept: Wikidata's class for the item says it is a business or a product, and its label or description names the "
             "category. Every other candidate is listed under Left out, with the rule that left it out.")
LIMITATIONS = [
    "Wikidata is edited by volunteers. A brand or product with no entry, no description or no state link is absent here, not absent from the market.",
    "A state link is where Wikidata places a brand's headquarters or a product's origin. It does not say where the item is sold.",
    "Wikidata holds no prices, sales, market share or advertising, so none is shown. An empty field is not recorded; it is never estimated.",
    "Wikipedia pageviews are attention to an article, not sales and not search volume.",
]


def _bad(field: str, message: str) -> ValidationFailed:
    return ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message=message)])


# --- reading -----------------------------------------------------------------------------------------------------


def _snapshot_view(row: m.LensShelfSnapshot) -> v.LensShelfSnapshotView:
    found = row.discovery
    return v.LensShelfSnapshotView(
        id=row.id, version=row.version, taken_at=row.taken_at, entities=len(found.get("entities", [])), excluded=len(found.get("excluded", [])))


def _attention(entity: ShelfEntity, stored: dict | None, region_code: str, mode: str) -> tuple[v.LensShelfAttention | None, str | None]:
    """(attention, why there is none). Read for the best-referenced placed items only; the rest say why."""
    if entity.wikipedia_languages == 0 or not entity.sitelinks:
        return None, "No Wikipedia article about it, so there is no attention to read."
    if stored is None:
        if not entity.region_codes:
            return None, "Not placed in a state, so there is no regional edition to read."
        return None, "Attention is read for the best-referenced items placed in the campaign's states only."
    if stored["region_code"] != region_code:
        return None, f"Attention is shown under {REGIONS[stored['region_code']].name}."
    region = region_for(region_code)
    regional = region.language if region else None
    primary, reference, basis = shared.pick_editions(stored["editions"], regional)
    if primary is None:
        return None, "No pageviews were recorded for its article."
    view, measured = shared.edition_view(primary, regional)
    _, ref_measure = shared.edition_view(reference, regional) if reference else (None, None)
    level, reasons = trends.confidence(measured, ref_measure, fixture=mode == "demo")
    if basis == "english_only":
        level, reasons = "low", ["Only the English edition has the article. It is read worldwide, not only in the state."]
    source = stored["source"]
    return v.LensShelfAttention(
        language=view.language, language_name=view.language_name, article=view.article, article_url=view.article_url,
        is_regional=view.is_regional, months=view.months, total_views=view.total_views, recent_mean=view.recent_mean, change=view.change,
        quarter_change=view.quarter_change, normalised=view.normalised, direction=view.direction, confidence=level,
        confidence_reasons=reasons, series=view.series,
        source=v.LensSourceLink(label=f"Wikimedia pageviews: {view.project}, {view.article}", url=view.article_url,
                                publisher="Wikimedia Foundation", retrieved_at=shared.parse_time(source["retrieved_at"]), kind="observed")), None


def _entity_view(entity: ShelfEntity, stored: dict | None, region_code: str, mode: str, retrieved_at: datetime) -> v.LensShelfEntity:
    attention, note = _attention(entity, stored, region_code, mode)
    unknown = [label for label, missing in (
        ("founded", entity.founded_year is None), ("headquarters or origin", not entity.places),
        ("official website", not entity.website)) if missing]
    sources = [v.LensSourceLink(
        label=f"Wikidata {entity.entity_id}", url=entity.wikidata_url, publisher="Wikidata", retrieved_at=retrieved_at, kind="observed")]
    if attention is not None:
        sources.append(attention.source)
    return v.LensShelfEntity(
        entity_id=entity.entity_id, label=entity.label, description=entity.description, kind=entity.kind,  # type: ignore[arg-type]
        classes=entity.classes, wikidata_url=entity.wikidata_url, website=entity.website, founded_year=entity.founded_year,
        places=[v.LensShelfPlace(entity_id=p.entity_id, label=p.label) for p in entity.places], basis=entity.region_basis,
        wikipedia_languages=entity.wikipedia_languages, attention=attention, attention_note=note, sources=sources, unknown=unknown)


async def _latest(s: AsyncSession, ctx: LensContext, pack_key: str) -> list[m.LensShelfSnapshot]:
    return list((await s.execute(
        select(m.LensShelfSnapshot).where(
            m.LensShelfSnapshot.workspace_id == ctx.workspace_id, m.LensShelfSnapshot.mode == ctx.mode,
            m.LensShelfSnapshot.pack_key == pack_key).order_by(m.LensShelfSnapshot.version.desc()).limit(HISTORY_LIMIT + 1))).scalars())


async def get_shelf(ctx: LensContext, region_codes: list[str] | None = None, pack_key: str | None = None) -> v.LensShelf:
    async with read_session() as s:
        facts = await shared.campaign_facts(s, ctx)
        names = await shared.region_names(s)
        codes = _codes(region_codes, facts.regions, names)
        ref, pack = shared.category_ref(facts.category_text, pack_key)
        if pack is None:  # the text names no pack: fall back to the pack this campaign last refreshed, if any
            last = await s.scalar(select(m.LensShelfSnapshot.pack_key).where(
                m.LensShelfSnapshot.campaign_id == ctx.campaign_id, m.LensShelfSnapshot.mode == ctx.mode)
                .order_by(m.LensShelfSnapshot.taken_at.desc()).limit(1))
            if last:
                ref, pack = shared.category_ref(facts.category_text, last)
        snapshots = await _latest(s, ctx, pack.key) if pack else []
        writable = await can_write(s, ctx)
    latest = snapshots[0] if snapshots else None
    regions: list[v.LensShelfRegion] = []
    unplaced: list[v.LensShelfEntity] = []
    excluded: list[v.LensShelfExcluded] = []
    gaps: list[str] = []
    if latest is not None and pack is not None:
        found = ShelfDiscovery.model_validate({**latest.discovery, "calls": []})
        shown: set[str] = set()
        for code in codes:
            region = region_for(code)
            entities = [e for e in found.entities if code in e.region_codes] if region else []
            shown.update(e.entity_id for e in entities)
            region_gaps: list[str] = []
            if region is None:
                region_gaps.append(f"Wikidata placement is mapped for {', '.join(r.name for r in REGIONS.values())} only, so nothing can be placed in {names[code]}.")
            elif not entities:
                region_gaps.append(f"Wikidata links no {pack.label.lower()} brand or product to {names[code]}. That is what Wikidata records, not a statement about the market.")
            regions.append(v.LensShelfRegion(
                region_code=code, region_name=names[code], supported=region is not None, gaps=region_gaps,
                entities=[_entity_view(e, latest.attention.get(e.entity_id), code, ctx.mode, found.retrieved_at) for e in entities]))
        unplaced = [_entity_view(e, None, "", ctx.mode, found.retrieved_at) for e in found.entities if e.entity_id not in shown]
        excluded = [v.LensShelfExcluded(entity_id=x.entity_id, label=x.label, reason=x.reason, url=f"https://www.wikidata.org/wiki/{x.entity_id}")
                    for x in found.excluded]
        gaps = list(latest.gaps)
    else:
        for code in codes:
            regions.append(v.LensShelfRegion(
                region_code=code, region_name=names[code], supported=region_for(code) is not None, entities=[],
                gaps=[]))
        if pack is not None:
            gaps = [f"The {pack.label.lower()} shelf has not been read yet in this mode."]
    return v.LensShelf(
        campaign_id=ctx.campaign_id, workspace_id=ctx.workspace_id, mode=ctx.mode,  # type: ignore[arg-type]
        generated_at=utcnow(), source_line=shared.source_line(ctx.mode, what="Wikidata statements and Wikipedia pageviews", taken_at=latest.taken_at if latest else None),
        category=ref, packs=shared.pack_options(), regions=regions, unplaced=unplaced, excluded=excluded, ranking=RANKING,
        relevance_rule=RELEVANCE, snapshot=_snapshot_view(latest) if latest else None,
        history=[_snapshot_view(r) for r in snapshots[1:]], gaps=gaps, can_refresh=writable and pack is not None,
        limitations=LIMITATIONS)


# --- refreshing --------------------------------------------------------------------------------------------------


async def refresh_shelf(user_id: UUID, campaign_id: UUID, body: v.LensShelfRefreshRequest) -> v.LensShelf:
    """Discover the category again and keep the result as a new version. Owner or editor role.

    Demo campaigns read the recording and make no network call. Live campaigns make about a dozen free Wikidata API requests
    through the bounded fetcher, spaced a second apart, then read pageviews for up to LENS_SHELF_MAX_ATTENTION items; the same
    pack is not read again within LENS_SHELF_MIN_INTERVAL_SECONDS (429)."""
    settings = get_settings()
    ctx = await lens_context(user_id, campaign_id, writable=True)
    async with read_session() as s:
        facts = await shared.campaign_facts(s, ctx)
        names = await shared.region_names(s)
    asked = _codes(body.region_codes, facts.regions, names)
    ref, pack = shared.category_ref(facts.category_text, body.pack_key)
    if body.pack_key and pack_by_key(body.pack_key) is None:
        raise _bad("pack_key", "That category is not one Market Lens covers.")
    if pack is None:
        raise _bad("pack_key", f"{ref.note} Choose one of: {', '.join(o.label for o in shared.pack_options())}.")
    key = (ctx.workspace_id, ctx.mode)
    if key in _RUNNING:
        raise Conflict("A Category Shelf refresh is already running for this workspace.")
    _RUNNING.add(key)  # no await between the check and this line: two requests cannot both pass
    try:
        await _check_interval(ctx, pack, settings.lens_shelf_min_interval_seconds)
        await _take(ctx, facts, asked, pack)
    finally:
        _RUNNING.discard(key)
    return await get_shelf(ctx, asked, pack.key)


async def _check_interval(ctx: LensContext, pack: CategoryPack, seconds: int) -> None:
    if ctx.mode != "live" or seconds <= 0:
        return
    async with read_session() as s:
        rows = await _latest(s, ctx, pack.key)
    if rows:
        wait = seconds - (utcnow() - rows[0].taken_at).total_seconds()
        if wait > 0:
            raise RateLimited(f"The {pack.label.lower()} shelf was read {int(seconds - wait)} seconds ago. A live shelf is read at most once "
                              f"every {seconds} seconds; try again in {int(wait) + 1} seconds.")


async def _take(ctx: LensContext, facts: shared.CampaignFacts, asked: list[str], pack: CategoryPack) -> None:
    settings = get_settings()
    log: list[CallLogRecord] = []
    source = shared.make_shelf_source(settings, ctx.mode)
    cached = await _CACHE.get(f"shelf:{pack.key}") if ctx.mode == "live" else None
    try:
        async with asyncio.timeout(settings.lens_build_timeout_seconds):
            discovery = ShelfDiscovery.model_validate(cached) if cached else await source.discover(pack)
            if not cached:
                log.extend(discovery.calls)
            if ctx.mode == "live" and not cached and not any("failed" in g for g in discovery.gaps):
                await _CACHE.put(f"shelf:{pack.key}", discovery.model_dump(mode="json"), ttl=CACHE_TTL)
            gaps = list(discovery.gaps)
            attention: dict[str, dict] = {}
            service = shared.make_trend_service(settings, ctx.mode)
            start, end = recorded_window() if ctx.mode == "demo" else shared.series_window(today())
            wanted = [(e, next(c for c in e.region_codes if c in asked)) for e in discovery.entities
                      if e.wikipedia_languages > 0 and any(c in asked for c in e.region_codes)][: settings.lens_shelf_max_attention]
            for entity, code in wanted:
                found = await service.trend_series(entity.entity_id, region_code=code, start=start, end=end, log=log)
                if not found or not found[0].editions:
                    last = log[-1] if log else None
                    if last is not None and last.status == "error":
                        gaps.append(f"Attention to \"{entity.label}\" could not be read ({last.error_type}), so it is not shown.")
                    continue
                series = found[0]
                attention[entity.entity_id] = {
                    "region_code": code, "editions": shared.stored_editions(series.editions),
                    "source": {"url": series.source.url, "title": series.source.title, "publisher": series.source.publisher,
                               "source_identifier": series.source.source_identifier, "retrieved_at": series.source.retrieved_at.isoformat()}}
    except TimeoutError:
        raise Conflict(f"The shelf read ran longer than {settings.lens_build_timeout_seconds} seconds and was stopped; nothing was stored.") from None
    async with session() as s, s.begin():
        version = int(await s.scalar(select(func.max(m.LensShelfSnapshot.version)).where(
            m.LensShelfSnapshot.workspace_id == ctx.workspace_id, m.LensShelfSnapshot.mode == ctx.mode,
            m.LensShelfSnapshot.pack_key == pack.key)) or 0) + 1
        row = m.LensShelfSnapshot(
            id=uuid4(), workspace_id=ctx.workspace_id, project_id=ctx.project_id, campaign_id=ctx.campaign_id, mode=ctx.mode,
            pack_key=pack.key, category_text=facts.category_text, version=version,
            discovery=discovery.model_dump(mode="json", exclude={"calls"}), attention=attention, gaps=gaps, created_by=ctx.user_id,
            taken_at=utcnow())
        s.add(row)
        await s.flush()
        s.add_all(shared.calls_to_rows(ctx, [c for c in log if not c.cached]))
        await record_audit(
            s, action="lens.shelf_refresh", target_type="lens_shelf_snapshot", target_id=str(row.id), workspace_id=ctx.workspace_id,
            actor_user_id=ctx.user_id, detail={"pack": pack.key, "mode": ctx.mode, "version": version,
                                              "entities": len(discovery.entities), "attention": len(attention)})
