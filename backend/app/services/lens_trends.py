"""Trend Radar (Market Lens feature 12): rising and falling public attention for the campaign's states and category.

A refresh reads Wikipedia pageviews (monthly, 24 whole months) of the festival articles the state's claims cite and of the
category's own topics, in the state's language edition with English beside it, and keeps each reading as a snapshot. A read
recomputes every direction from the stored series with `app.analytics.lens_trends`, so what is shown is always the method
stated on the page applied to numbers that were retrieved on the date shown. Nothing is estimated: an article with no
pageviews, no article, or a failed request is listed as not read, with the reason.

Pageviews are attention, not search volume and not demand. Moments come from the Moment Calendar: the dated festivals and
holidays in the campaign's dates (or the next 120 days) that Market Lens stored for the state.
"""

import asyncio
import logging
from collections import defaultdict
from datetime import date, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import lens as logic
from app.analytics import lens_trends as trends
from app.core.config import get_settings
from app.core.errors import Conflict, NotFound, RateLimited, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.fixtures.lens_t3_demo import recorded_window
from app.integrations.culture.base import CallLogRecord
from app.integrations.culture.regions import LANGUAGE_NAMES, region_for
from app.schemas import lens as lens_schema
from app.schemas import lens_t3 as v
from app.schemas.common import ErrorDetail
from app.services import lens_t3 as shared
from app.services.audit import record_audit
from app.services.common import WRITE_ROLES, get_owned
from app.services.lens import LensContext, lens_context
from app.services.lens_views import _load_views

logger = logging.getLogger(__name__)

MOMENT_LIMIT = 8
NEXT_DAYS = 120
HISTORY_LIMIT = 5
ORDER = {"rising": 0, "falling": 1, "mixed": 2, "steady": 3, "insufficient": 4}
_RUNNING: set[tuple[UUID, str]] = set()  # (workspace, mode) refreshes in progress in this process

LIMITATIONS = [
    "Pageviews count reads of a Wikipedia article. They are attention, not search volume, purchase intent or market size, and Wikipedia readers are not a representative sample of a state.",
    "A state's own language edition is read mostly, not only, from that state. The English edition is read worldwide.",
    "Wikipedia readership has fallen across the regional editions, so attention is read as a share of each edition's readership. Raw views and the edition's own change are shown beside it.",
    "A label describes the last months of a series; it does not forecast the next ones.",
]


def today() -> date:
    return utcnow().date()


def method() -> v.LensTrendMethod:
    return v.LensTrendMethod(
        version=trends.METHOD_VERSION, measure="Wikipedia pageviews (attention to an article)", granularity="monthly",
        series_months=shared.SERIES_MONTHS, year_months=trends.YEAR_MONTHS, quarter_months=trends.QUARTER_MONTHS,
        change_threshold=trends.CHANGE_THRESHOLD, min_months=trends.MIN_MONTHS, min_views_per_month=int(trends.MIN_MEAN_VIEWS),
        description=(
            f"Each article is read as monthly pageviews for {shared.SERIES_MONTHS} whole months and compared as two years: the last "
            f"{trends.YEAR_MONTHS} complete months against the {trends.YEAR_MONTHS} before them, so a festival that moves between years is "
            f"compared with itself. Views are taken as a share of the edition's own readership (views per million edition views), because "
            f"the regional Wikipedias have lost a third or more of their readers in a year and every article falls with them. Rising means "
            f"the share is at least {trends.CHANGE_THRESHOLD:.0%} higher and the slope through the two years is positive; falling is the "
            f"mirror image; steady is a change inside {trends.CHANGE_THRESHOLD:.0%}. If the change passes {trends.CHANGE_THRESHOLD:.0%} but the "
            f"slope points the other way the label is mixed. Under {trends.MIN_MONTHS} months, or under {trends.MIN_MEAN_VIEWS:.0f} views a "
            f"month in both years, is not enough to read a direction. The last {trends.QUARTER_MONTHS} months against the same months a "
            f"year earlier is shown beside the label as lately; it never changes the label."))


# --- reading -----------------------------------------------------------------------------------------------------


def _codes(requested: list[str] | None, campaign_codes: list[str], names: dict[str, str]) -> list[str]:
    codes = list(dict.fromkeys(requested if requested is not None else campaign_codes))
    unknown = [c for c in codes if c not in names]
    if unknown:
        raise NotFound("Region was not found: " + ", ".join(unknown) + ".")
    return codes


async def can_write(s: AsyncSession, ctx: LensContext) -> bool:
    _, project = await get_owned(s, m.Campaign, ctx.campaign_id, ctx.user_id, "Campaign")
    return project.access_role in WRITE_ROLES and project.status != "archived"


def _build_item(row: m.LensTrendSnapshot, region_name: str, earlier: list[m.LensTrendSnapshot]) -> v.LensTrendItem | None:
    region = region_for(row.region_code)
    regional = region.language if region else None
    primary, reference, basis = shared.pick_editions(row.editions, regional)
    if primary is None:
        return None
    p_view, p_measure = shared.edition_view(primary, regional)
    r_view, r_measure = shared.edition_view(reference, regional) if reference else (None, None)
    fixture = row.mode == "demo" or str(row.source.get("source_identifier", "")).startswith("fixture:")
    level, reasons = trends.confidence(p_measure, r_measure, fixture=fixture)
    if basis == "english_only":
        level = "low"
        reasons = ["Only the English edition has this article. It is read worldwide, not only in the state, so it says little about the state."]
    history = []
    for old in earlier[:HISTORY_LIMIT]:
        old_primary, _, _ = shared.pick_editions(old.editions, regional)
        if old_primary is None:
            continue
        measured = trends.measure(shared.month_points(old_primary), shared.baseline_points(old_primary))
        history.append(v.LensTrendHistoryEntry(
            taken_at=old.taken_at, direction=measured.direction, change=measured.change,
            last_month=measured.last_month.strftime("%Y-%m") if measured.last_month else None))
    return v.LensTrendItem(
        key=f"{row.region_code}:{row.term}", term=row.term, label=row.label, term_kind=row.term_kind,  # type: ignore[arg-type]
        festival_subject=row.festival_subject, region_code=row.region_code, region_name=region_name,
        direction=p_measure.direction, change=p_measure.change, quarter_change=p_measure.quarter_change,
        confidence=level, confidence_reasons=reasons, reasons=p_measure.reasons, basis=basis,  # type: ignore[arg-type]
        primary=p_view, reference=r_view, windows=shared.windows_of(p_measure),
        source=v.LensSourceLink(
            label=f"Wikimedia pageviews: {primary['project']}, {primary['article']}", url=p_view.article_url,
            publisher="Wikimedia Foundation", retrieved_at=shared.parse_time(row.source["retrieved_at"]), kind="observed"),
        taken_at=row.taken_at, snapshots=1 + len(earlier), history=history)


def _moments_window(facts: shared.CampaignFacts, now: date) -> tuple[lens_schema.LensWindow, str]:
    if facts.window and facts.window[1] >= now:
        return lens_schema.LensWindow(date_from=max(facts.window[0], now), date_to=facts.window[1]), "campaign_dates"
    return lens_schema.LensWindow(date_from=now, date_to=now + timedelta(days=NEXT_DAYS)), "next_120_days"


async def _dated_in_window(s: AsyncSession, ctx: LensContext, code: str, window: lens_schema.LensWindow) -> tuple[list, list, list]:
    """(dated moments inside the window, timed moments that may overlap it, the festival claims) for a state, from the Moment
    Calendar's own rules. A timed moment is a festival its sources date only in words, with months that overlap the window."""
    views = await _load_views(s, ctx, region_codes=[code], categories=("festival", "moment"))
    found, timed, seen = [], [], set()
    for year in range(window.date_from.year, window.date_to.year + 1):
        dated, undated = logic.calendar_entries(views, year=year, window=window)
        found.extend(d for d in dated if d.in_window)
        for t in undated:
            if t.may_overlap_window and t.timings and t.subject not in seen:
                seen.add(t.subject)
                timed.append(t)
    found.sort(key=lambda d: (d.date, d.name, d.key))
    return found, timed, [c for c in views if c.category == "festival"]


async def get_radar(ctx: LensContext, region_codes: list[str] | None = None) -> v.LensTrendRadar:
    now = today()
    async with read_session() as s:
        facts = await shared.campaign_facts(s, ctx)
        names = await shared.region_names(s)
        codes = _codes(region_codes, facts.regions, names)
        window, basis = _moments_window(facts, now)
        batches = list((await s.execute(
            select(m.LensTrendBatch).where(m.LensTrendBatch.workspace_id == ctx.workspace_id, m.LensTrendBatch.mode == ctx.mode)
            .order_by(m.LensTrendBatch.taken_at.desc()).limit(80))).scalars())
        latest: dict[str, m.LensTrendBatch] = {}
        for batch in batches:
            for code in codes:
                if code in batch.regions and code not in latest:
                    latest[code] = batch
        rows = list((await s.execute(
            select(m.LensTrendSnapshot).where(
                m.LensTrendSnapshot.workspace_id == ctx.workspace_id, m.LensTrendSnapshot.mode == ctx.mode,
                m.LensTrendSnapshot.region_code.in_(codes))
            .order_by(m.LensTrendSnapshot.taken_at.desc(), m.LensTrendSnapshot.term).limit(600))).scalars())
        by_term: dict[tuple[str, str], list[m.LensTrendSnapshot]] = defaultdict(list)
        for row in rows:
            by_term[(row.region_code, row.term)].append(row)  # newest first
        writable = await can_write(s, ctx)
        regions: list[v.LensTrendRegion] = []
        for code in codes:
            region = region_for(code)
            batch = latest.get(code)
            items: list[v.LensTrendItem] = []
            if batch is not None:
                for row in by_term_latest(by_term, code, batch.id):
                    item = _build_item(row, names[code], [r for r in by_term[(code, row.term)] if r.id != row.id and r.taken_at < row.taken_at])
                    if item is not None:
                        items.append(item)
            items.sort(key=lambda i: (ORDER[i.direction], -abs(i.change or 0), i.label.casefold()))
            moments: list[v.LensTrendMoment] = []
            dated, timed, _ = await _dated_in_window(s, ctx, code, window)
            by_subject = {i.festival_subject: i.key for i in items if i.festival_subject}
            for d in dated:
                moments.append(v.LensTrendMoment(
                    name=d.name, date=d.date, days_until=(d.date - now).days, date_basis=d.date_basis,  # type: ignore[arg-type]
                    timing_text=None, festival_subject=d.festival_subject, term_key=by_subject.get(d.festival_subject),
                    claim_id=d.claim.id,
                    source_label="Public holiday list" if d.date_basis == "public_holiday_list" else "Date stated by a source"))
            for t in timed:  # after the dated ones: the sources give months, not a day
                moments.append(v.LensTrendMoment(
                    name=t.name, date=None, days_until=None, date_basis="timing_text", timing_text=t.timings[0].text,
                    festival_subject=t.subject if t.subject.startswith("festival:") else None,
                    term_key=by_subject.get(t.subject), claim_id=t.timings[0].claim.id, source_label="Timing as the source states it"))
            gaps = list(batch.regions[code]["gaps"]) if batch is not None else []
            if region is None:
                gaps = [f"No regional-language Wikipedia edition is mapped for {names[code]}. Attention is read for "
                        "Maharashtra, Tamil Nadu, Kerala and West Bengal."]
            elif batch is None:
                gaps = [f"{names[code]} has not been refreshed yet in this mode."]
            regions.append(v.LensTrendRegion(
                region_code=code, region_name=names[code], supported=region is not None,
                edition_language=region.language if region else None, edition_name=shared.edition_name(region.language) if region else None,
                items=items, moments=moments[:MOMENT_LIMIT], gaps=gaps, refreshed_at=batch.taken_at if batch else None))
        pack_ref, _ = shared.category_ref(facts.category_text)
    every = [i for r in regions for i in r.items]
    counts = {d: sum(1 for i in every if i.direction == d) for d in ORDER}
    stamps = [r.refreshed_at for r in regions if r.refreshed_at]
    return v.LensTrendRadar(
        campaign_id=ctx.campaign_id, workspace_id=ctx.workspace_id, mode=ctx.mode,  # type: ignore[arg-type]
        generated_at=utcnow(), source_line=shared.source_line(ctx.mode, what="Wikipedia pageviews, regional language editions", taken_at=max(stamps) if stamps else None),
        category=pack_ref, method=method(), summary=v.LensTrendSummary(items=len(every), **counts), regions=regions,
        moments_window=window, moments_window_basis=basis,  # type: ignore[arg-type]
        can_refresh=writable and any(r.supported for r in regions), refreshed_at=max(stamps) if stamps else None,
        limitations=LIMITATIONS)


def by_term_latest(by_term: dict[tuple[str, str], list[m.LensTrendSnapshot]], code: str, batch_id: UUID) -> list[m.LensTrendSnapshot]:
    return [rows[0] for (c, _), rows in by_term.items() if c == code and rows[0].batch_id == batch_id]


# --- refreshing --------------------------------------------------------------------------------------------------


def _unread(label: str, region: object, mode: str, last: CallLogRecord | None) -> str:
    if last is not None and last.status == "error":
        return f"\"{label}\" could not be read ({last.error_type}), so it is not shown."
    if mode == "demo":
        return f"\"{label}\" is not in the demo recording, so it is not shown."
    language = LANGUAGE_NAMES.get(region.language, region.language)  # type: ignore[attr-defined]
    return f"\"{label}\" has no Wikipedia article in the {language} or English edition, so it is not shown."


def _bad(field: str, message: str) -> ValidationFailed:
    return ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field=field, message=message)])


async def _check_interval(ctx: LensContext, codes: list[str], seconds: int) -> None:
    """Live refreshes of one state are spaced out: the sources are free and shared, and a repeat adds nothing."""
    if ctx.mode != "live" or seconds <= 0:
        return
    async with read_session() as s:
        batches = list((await s.execute(
            select(m.LensTrendBatch).where(m.LensTrendBatch.workspace_id == ctx.workspace_id, m.LensTrendBatch.mode == "live")
            .order_by(m.LensTrendBatch.taken_at.desc()).limit(40))).scalars())
    now = utcnow()
    for code in codes:
        batch = next((b for b in batches if code in b.regions), None)
        wait = seconds - (now - batch.taken_at).total_seconds() if batch else 0
        if wait > 0:
            raise RateLimited(f"{code} was refreshed {int(seconds - wait)} seconds ago. Live refreshes of one state are spaced "
                              f"{seconds} seconds apart; try again in {int(wait) + 1} seconds.")


async def refresh_radar(user_id: UUID, campaign_id: UUID, body: v.LensTrendRefreshRequest) -> v.LensTrendRadar:
    """Read the pageviews again and keep the new readings beside the old ones. Owner or editor role.

    Demo campaigns read the recording and make no network call. Live campaigns call the free Wikimedia APIs through the
    bounded fetcher; a state refreshed less than LENS_TREND_MIN_INTERVAL_SECONDS ago answers 429, and a source that fails
    or rate-limits is reported in that state's gaps, never hidden or replaced."""
    settings = get_settings()
    ctx = await lens_context(user_id, campaign_id, writable=True)
    async with read_session() as s:
        facts = await shared.campaign_facts(s, ctx)
        names = await shared.region_names(s)
    asked = _codes(body.region_codes, facts.regions, names)
    if not asked:
        raise _bad("region_codes", "The campaign names no state. Add target regions to the brief, or name the states to read.")
    if ctx.mode == "live" and len(asked) > settings.lens_trend_max_regions_live:
        raise _bad("region_codes", f"A live refresh takes at most {settings.lens_trend_max_regions_live} states per request; it calls public APIs.")
    key = (ctx.workspace_id, ctx.mode)
    if key in _RUNNING:
        raise Conflict("A Trend Radar refresh is already running for this workspace.")
    _RUNNING.add(key)  # no await between the check and this line: two requests cannot both pass
    try:
        await _check_interval(ctx, asked, settings.lens_trend_min_interval_seconds)
        await _take(ctx, facts, names, asked, body.max_terms or settings.lens_trend_max_terms)
    finally:
        _RUNNING.discard(key)
    return await get_radar(ctx, asked)


async def _take(ctx: LensContext, facts: shared.CampaignFacts, names: dict[str, str], asked: list[str], max_terms: int) -> None:
    settings = get_settings()
    now = today()
    start, end = recorded_window() if ctx.mode == "demo" else shared.series_window(now)
    _, pack = shared.category_ref(facts.category_text)
    window, _ = _moments_window(facts, now)
    service = shared.make_trend_service(settings, ctx.mode)
    log: list[CallLogRecord] = []
    batch_id, taken_at = uuid4(), utcnow()
    meta: dict[str, dict] = {}
    snapshots: list[m.LensTrendSnapshot] = []
    try:
        async with asyncio.timeout(settings.lens_build_timeout_seconds):
            for code in asked:
                region = region_for(code)
                if region is None:
                    meta[code] = {"asked": 0, "read": 0, "gaps": [
                        f"No regional-language Wikipedia edition is mapped for {names[code]}. Attention is read for Maharashtra, "
                        "Tamil Nadu, Kerala and West Bengal."]}
                    continue
                async with read_session() as s:
                    dated, timed, festival_claims = await _dated_in_window(s, ctx, code, window)
                articles = trends.festival_articles(
                    [(c.subject, [(src.source_type, src.url) for src in c.sources]) for c in festival_claims], region.name)
                in_window = {d.festival_subject for d in dated if d.festival_subject} | {t.subject for t in timed}
                articles.sort(key=lambda a: a[0] not in in_window)  # festivals inside the campaign dates first; the sort is stable
                terms = [(title, title, "festival", subject) for subject, title in articles[:max_terms]]
                terms += [(t.entity_id, t.label, "category", None) for t in (pack.topics if pack else [])]
                gaps: list[str] = []
                if not festival_claims:
                    gaps.append(f"No festival claims are stored for {region.name} in this mode, so no festival article is read. Build the state in Atlas first.")
                elif not articles:
                    gaps.append(f"None of the festivals stored for {region.name} cites a Wikipedia article of its own, so none is read.")
                if pack is None:
                    gaps.append("The campaign's category names no category pack, so attention to the category itself is not read.")
                read = 0
                for term, label, kind, subject in terms:
                    found = await service.trend_series(term, region_code=code, start=start, end=end, log=log)
                    series = found[0] if found else None
                    if series is None or not series.editions:
                        gaps.append(_unread(label, region, ctx.mode, log[-1] if log else None))
                        continue
                    read += 1
                    snapshots.append(m.LensTrendSnapshot(
                        id=uuid4(), workspace_id=ctx.workspace_id, project_id=ctx.project_id, campaign_id=ctx.campaign_id,
                        batch_id=batch_id, mode=ctx.mode, region_code=code, term=term, term_kind=kind, label=label,
                        festival_subject=subject, granularity="monthly", window_start=series.start, window_end=series.end,
                        method_version=trends.METHOD_VERSION, editions=shared.stored_editions(series.editions),
                        source={"url": series.source.url, "title": series.source.title, "publisher": series.source.publisher,
                                "source_identifier": series.source.source_identifier,
                                "retrieved_at": series.source.retrieved_at.isoformat()},
                        created_by=ctx.user_id, taken_at=taken_at))
                meta[code] = {"asked": len(terms), "read": read, "gaps": gaps}
    except TimeoutError:
        raise Conflict(f"The refresh ran longer than {settings.lens_build_timeout_seconds} seconds and was stopped; nothing was stored.") from None
    async with session() as s, s.begin():
        s.add(m.LensTrendBatch(
            id=batch_id, workspace_id=ctx.workspace_id, project_id=ctx.project_id, campaign_id=ctx.campaign_id, mode=ctx.mode,
            category_text=facts.category_text, pack_key=pack.key if pack else None, regions=meta, window_start=start, window_end=end,
            method_version=trends.METHOD_VERSION, created_by=ctx.user_id, taken_at=taken_at))
        await s.flush()
        s.add_all(snapshots)
        s.add_all(shared.calls_to_rows(ctx, log))
        await record_audit(
            s, action="lens.trend_refresh", target_type="lens_trend_batch", target_id=str(batch_id), workspace_id=ctx.workspace_id,
            actor_user_id=ctx.user_id, detail={"regions": asked, "mode": ctx.mode, "snapshots": len(snapshots)})
