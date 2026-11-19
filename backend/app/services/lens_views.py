"""Market Lens reads: the atlas, a state profile, a comparison, the moment calendar and the language map.

Claims are read through the existing evidence code (`claims`, `data_health`), so the Evidence Meter, confidence and
conflicts are the ones used everywhere else. Beside them every state carries its state data (`lens_data`): published figures,
searches, languages and holidays, shown as data and never counted as evidence. Reads never call a culture source: they show
what a build stored and what the datasets hold. Demo campaigns read demo claims only; live campaigns read live only.
"""

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import lens as logic
from app.core.errors import NotFound, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session
from app.integrations.culture.adapters.census import load_census
from app.schemas import lens as v
from app.schemas.common import ErrorDetail
from app.schemas.regions import ClaimView, Conflict, Region
from app.services import claims as claim_service
from app.services import data_health, lens_data, lens_moments, regions
from app.services.claims import LIVE_STATUSES, _claim_view, _open_conflicts_by_claim, _sources
from app.services.lens import LensContext, build_view, latest_builds, mode_label, region_names
from app.services.lens_t3 import campaign_facts

COMPARE_MIN, COMPARE_MAX = 2, 4
CAMPAIGN_NOTE = "Evidence from sources, not a forecast: nothing here says a campaign will work in a state."
MISSING_NOTE = "A missing claim means no source was collected for it, not that the thing does not exist."
CONFIDENCE_NOTE = "Confidence is a rule-based level computed from the sources, never a probability. No native reviewer has confirmed any claim, so none is High."


async def _load_views(
    s: AsyncSession, ctx: LensContext, *, region_codes: list[str] | None = None, categories: tuple[str, ...] | None = None,
    attributes: frozenset[str] | None = None,
) -> list[ClaimView]:
    """ClaimViews of the claims this workspace sees in the campaign's mode (its own and shared ones), filtered."""
    stmt = select(m.Claim).where(
        or_(m.Claim.workspace_id == ctx.workspace_id, m.Claim.workspace_id.is_(None)),
        m.Claim.mode == ctx.mode, m.Claim.status.in_(LIVE_STATUSES))
    if region_codes is not None:
        ids = list((await s.execute(select(m.Region.id).where(m.Region.code.in_(region_codes)))).scalars())
        stmt = stmt.where(m.Claim.region_id.in_(ids))
    if categories is not None:
        stmt = stmt.where(m.Claim.category.in_(categories))
    if attributes is not None:
        stmt = stmt.where(m.Claim.attribute.in_(attributes))
    rows = list((await s.execute(stmt.order_by(m.Claim.category, m.Claim.attribute, m.Claim.created_at, m.Claim.id))).scalars())
    sources: dict[UUID, list[m.ClaimSource]] = defaultdict(list)
    for src in await _sources(s, [c.id for c in rows]) if rows else []:
        sources[src.claim_id].append(src)
    open_by_claim = await _open_conflicts_by_claim(s, ctx.workspace_id)
    now = utcnow()
    return [_claim_view(c, sources, open_by_claim, now) for c in rows]


async def _conflicts(ctx: LensContext, region_code: str | None) -> list[Conflict]:
    """Records any unrecorded disagreement between visible claims first, then lists them (open ones first)."""
    items, _ = await claim_service.list_conflicts(
        ctx.user_id, ctx.workspace_id, region_code=region_code, status=None, mode=ctx.mode, limit=100, offset=0)
    return items


# --- atlas -------------------------------------------------------------------------------------------------------


DATA_NOTE = ("State data (figures, searches, languages, holidays) is copied from public datasets with its period. It is shown beside "
             "the evidence and never counted in the Evidence Meter.")


async def atlas(ctx: LensContext) -> v.LensAtlas:
    await _conflicts(ctx, None)  # records conflicts so the per-state counts include them
    health = await data_health.workspace_data_health(ctx.user_id, ctx.workspace_id, ctx.mode)  # type: ignore[arg-type]
    coverage = {c.region_code: c for c in health.regions}
    async with read_session() as s:
        views = await _load_views(s, ctx)
        builds = await latest_builds(s, ctx.workspace_id, ctx.mode)
        names = await region_names(s)
        roles = await lens_data.campaign_roles(s, ctx.campaign_id)
    india = (await regions.list_regions("IN", 100, 0)).items
    datas, data_sources = await lens_data.all_states(ctx, [r.code for r in india])
    states = []
    for region in india:
        c = coverage.get(region.code)
        row = builds.get(region.code)
        states.append(v.LensAtlasState(
            code=region.code, name=region.name, kind=region.kind, primary_language=region.primary_language,
            primary_script=region.primary_script, strength=c.strength if c else "weak",
            strength_reasons=c.strength_reasons if c else ["No claims are recorded for this region yet."],
            claims=c.claims if c else 0, supported_claims=c.supported_claims if c else 0,
            categories_covered=c.categories_covered if c else 0, categories_total=c.categories_total if c else 0,
            missing_categories=c.missing_categories if c else [], sources=c.sources if c else 0,
            source_types=c.source_types if c else [], newest_source_date=c.newest_source_date if c else None,
            open_conflicts=c.open_conflicts if c else 0, stale_claims=c.stale_claims if c else 0, built=row is not None,
            last_build=build_view(row, names.get(row.region_code, row.region_code)) if row else None,
            campaign_role=roles.get(region.code), data=datas[region.code]))  # type: ignore[arg-type]
    summary = v.LensAtlasSummary(
        states_total=len(states), states_with_claims=sum(1 for s_ in states if s_.claims),
        states_with_data=sum(1 for s_ in states if s_.data.figures or s_.data.searches or s_.data.holidays),
        weak=sum(1 for s_ in states if s_.strength == "weak"),
        partial=sum(1 for s_ in states if s_.strength == "partial"), solid=sum(1 for s_ in states if s_.strength == "solid"),
        claims=sum(s_.claims for s_ in states), open_conflicts=sum(s_.open_conflicts for s_ in states))
    return v.LensAtlas(
        campaign_id=ctx.campaign_id, workspace_id=ctx.workspace_id, mode=ctx.mode,  # type: ignore[arg-type]
        mode_label=mode_label(ctx.mode), generated_at=utcnow(), summary=summary, states=states,
        sources=logic.summarise_sources(views), data_sources=data_sources,
        limitations=[
            "Evidence strength is the Evidence Meter's rating of the claims stored for a state. Weak means little is recorded, not that the state matters little.",
            DATA_NOTE,
            "Four states (Maharashtra, Tamil Nadu, Kerala, West Bengal) have curated festival, food and custom references; the census "
            "mother-tongue table covers 31 states and union territories.",
            "Cultural evidence is not demand: nothing here establishes that a product will sell in a state.",
            CONFIDENCE_NOTE])


# --- state profile -----------------------------------------------------------------------------------------------

SECTIONS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("languages", "Languages and scripts", "Official and principal languages and scripts. Census shares are in the Language Map.", ("language", "script")),
    ("festivals", "Festivals and moments", "Festivals and cultural moments as sources describe them. Dated public holidays are in the Calendar.", ("festival", "moment")),
    ("references", "Cultural references", "Food, colours, symbols, customs and family roles that sources document.", ("food", "colour", "symbol", "custom", "family", "demographic", "media")),
    ("tone", "Humour and tone", "How sources describe humour and what they flag as sensitive.", ("humour", "sensitivity")),
    ("trends", "Public attention", "Reader attention over time for articles about festivals: attention, not demand.", ("trend",)),
)
ELSEWHERE = {"public_holiday_date": ("calendar", "dated public holidays"), "language_share": ("language_map", "census language claims"),
             "mother_tongue_speakers": ("language_map", "census language claims")}


async def state_profile(ctx: LensContext, region_code: str) -> v.LensStateProfile:
    profile = await claim_service.build_region_profile(ctx.user_id, ctx.workspace_id, region_code, mode=ctx.mode)
    conflicts = await _conflicts(ctx, region_code)
    async with read_session() as s:
        row = (await latest_builds(s, ctx.workspace_id, ctx.mode)).get(region_code)
        names = await region_names(s)
        roles = await lens_data.campaign_roles(s, ctx.campaign_id)
    datas, data_sources = await lens_data.all_states(ctx, [region_code])
    by_category = {c.category: c.claims for c in profile.categories}
    every = [c for items in by_category.values() for c in items]
    sections = []
    for key, title, description, categories in SECTIONS:
        shown, elsewhere = [], defaultdict(int)
        for category in categories:
            for claim in by_category.get(category, []):
                if claim.attribute in ELSEWHERE:
                    elsewhere[claim.attribute] += 1
                else:
                    shown.append(claim)
        moved: dict[tuple[str, str], int] = defaultdict(int)
        for attribute, count in elsewhere.items():
            moved[ELSEWHERE[attribute]] += count
        sections.append(v.LensProfileSection(
            key=key,  # type: ignore[arg-type]
            title=title, description=description, categories=list(categories), claims=shown,
            elsewhere=[v.LensElsewhere(view=view, label=label, claims=n) for (view, label), n in sorted(moved.items())],  # type: ignore[arg-type]
            empty_reason=None if shown else f"No claim in this section is recorded for this state yet. {MISSING_NOTE}"))
    gaps = list(row.gaps) if row else ["No profile has been built for this state in this mode yet. Build it to gather claims."]
    return v.LensStateProfile(
        campaign_id=ctx.campaign_id, workspace_id=ctx.workspace_id, mode=ctx.mode,  # type: ignore[arg-type]
        mode_label=mode_label(ctx.mode), generated_at=utcnow(), region=profile.region, meter=profile.meter, sections=sections,
        conflicts=conflicts, build=build_view(row, names.get(region_code, region_code)) if row else None,
        campaign_role=roles.get(region_code), data=datas[region_code],  # type: ignore[arg-type]
        sources=logic.summarise_sources(every), data_sources=data_sources, gaps=gaps,
        limitations=[MISSING_NOTE, CONFIDENCE_NOTE, CAMPAIGN_NOTE, DATA_NOTE,
                     "A claim says what a source states. It is not what every person in the state thinks or does."])


# --- compare -----------------------------------------------------------------------------------------------------


async def compare(ctx: LensContext, codes: list[str]) -> v.LensCompare:
    codes = list(dict.fromkeys(codes))
    if not COMPARE_MIN <= len(codes) <= COMPARE_MAX:
        raise ValidationFailed("The supplied request is invalid.", details=[
            ErrorDetail(field="region_code", message=f"Compare {COMPARE_MIN} to {COMPARE_MAX} different states.")])
    profiles = [await claim_service.build_region_profile(ctx.user_id, ctx.workspace_id, code, mode=ctx.mode) for code in codes]
    async with read_session() as s:
        built = await latest_builds(s, ctx.workspace_id, ctx.mode)
    datas, data_sources = await lens_data.all_states(ctx, codes)
    per_region = {p.region.code: [c for cat in p.categories for c in cat.claims] for p in profiles}
    cols = []
    for p in profiles:
        meter = p.meter
        cols.append(v.LensCompareRegion(
            region=p.region, strength=meter.strength, strength_reasons=meter.strength_reasons, claims=meter.claims,
            supported_claims=meter.supported_claims, categories_covered=meter.categories_covered,
            categories_total=meter.categories_total, missing_categories=[c.category for c in meter.coverage if c.supported_claims == 0],
            sources=meter.sources, newest_source_date=meter.freshness.newest_source_date, open_conflicts=meter.open_conflicts,
            stale_claims=meter.stale_claims, low=meter.confidence.low, moderate=meter.confidence.moderate,
            high=meter.confidence.high, built=p.region.code in built, data=datas[p.region.code]))
    return v.LensCompare(
        campaign_id=ctx.campaign_id, workspace_id=ctx.workspace_id, mode=ctx.mode,  # type: ignore[arg-type]
        mode_label=mode_label(ctx.mode), generated_at=utcnow(), regions=cols, data_rows=lens_data.data_rows(datas),
        rows=logic.compare_rows(per_region), sources=logic.summarise_sources([c for items in per_region.values() for c in items]),
        data_sources=data_sources,
        limitations=[
            "A claim in two columns means two sources were found, not that the two things mean the same. Check the evidence before treating them as equivalent.",
            "Figures of different periods are not strictly comparable; each cell carries its own period. Highest means the largest number, not the best.",
            MISSING_NOTE, CONFIDENCE_NOTE, CAMPAIGN_NOTE, DATA_NOTE])


# --- moment calendar ---------------------------------------------------------------------------------------------


def _festivals(views: list[ClaimView]) -> list[tuple[str, int]]:
    """(festival name, distinct cited sources) for each festival subject the state's claims name."""
    names: dict[str, str] = {}
    sources: dict[str, set[str]] = defaultdict(set)
    for c in views:
        if c.category != "festival":
            continue
        if (name := logic.claim_name(c)) and c.subject not in names:
            names[c.subject] = name
        sources[c.subject].update(src.source_identifier for src in c.sources)
    return [(name, len(sources[subject])) for subject, name in names.items()]


async def calendar(ctx: LensContext, region_code: str, year: int | None, window: v.LensWindow | None) -> v.LensCalendar:
    region = await _region(region_code)
    conflicts = [c for c in await _conflicts(ctx, region_code) if c.claim_a.category in ("festival", "moment")]
    async with read_session() as s:
        views = await _load_views(s, ctx, region_codes=[region_code], categories=("festival", "moment"))
        facts = await campaign_facts(s, ctx)
    basis = "request" if window is not None else None
    if window is None and facts.window is not None:  # the campaign's own dates, from its brief
        window, basis = v.LensWindow(date_from=facts.window[0], date_to=facts.window[1]), "campaign"
    if year is None:  # open on the year the campaign runs in, so its dates are on the page
        year = window.date_from.year if window is not None else utcnow().year
    years = sorted({int(c.scope.period) for c in views if c.attribute == logic.HOLIDAY_ATTRIBUTE and c.scope.period and c.scope.period.isdigit()})
    dated, timed = logic.calendar_entries(views, year=year, window=window)
    datas, data_sources = await lens_data.all_states(ctx, [region_code])
    data = datas[region_code]
    google = await lens_moments.google_events(ctx.mode, year)
    entries = lens_moments.build_entries(
        state=region.name, year=year, window=window, dated=dated, festivals=_festivals(views),
        state_list=lens_moments.state_holidays(region_code, year), google=google, region_code=region_code,
        searches=[*data.searches, *data.rising])
    if google:
        stamp = max((e.retrieved_at for e in google if e.retrieved_at), default=None)
        data_sources.append(v.LensDataSource(
            key="google_calendar", label="Holidays and observances", publisher="Google Calendar, Holidays in India (Calendar API)",
            url=lens_moments.CALENDAR_PAGE, detail="National public holidays and observances, with Google's tentative flag for lunar dates.",
            period=str(year), retrieved_at=stamp))
    if any(e.about for e in entries):
        recorded_on = lens_moments.notes_recorded_on()
        data_sources.append(v.LensDataSource(
            key="knowledge_graph", label="What a moment is", publisher="Google Knowledge Graph Search API",
            url="https://developers.google.com/knowledge-graph", detail=lens_moments.NOTE_ATTRIBUTION + "; kept only where the result names the moment itself.",
            period=None, retrieved_at=datetime.combine(recorded_on, datetime.min.time(), tzinfo=UTC) if recorded_on else None))
    gaps = [] if entries else [f"No dated moment is listed for {region.name} in {year}."]
    return v.LensCalendar(
        campaign_id=ctx.campaign_id, workspace_id=ctx.workspace_id, mode=ctx.mode,  # type: ignore[arg-type]
        mode_label=mode_label(ctx.mode), generated_at=utcnow(), region=region, year=year, years_available=years, window=window,
        window_basis=basis, entries=entries, typical=lens_moments.typical_moments(region_code, entries),  # type: ignore[arg-type]
        months=logic.months_of(dated), timed=timed, conflicts=conflicts, sources=logic.summarise_sources(views),
        data_sources=data_sources, gaps=gaps,
        limitations=[
            "Dates come from the state's public-holiday list (python-holidays), Google's Holidays in India calendar and cited claims. "
            "A festival on none of them has no exact date here, only the timing its sources state.",
            "Lunar festival dates are announced late and can move by a day: verify against a current panchang or official notice before a launch.",
            "Why a moment matters is computed from the lists that name it, the campaign dates, the weekday and this week's searches; it is not a forecast.",
            "Months named in timing text are read from the source's words; they are hints for overlap, not dates.",
            "Where two sources disagree the calendar keeps both and shows the conflict.", MISSING_NOTE])


async def _region(code: str) -> Region:
    return await regions.get_region(code)


# --- language map ------------------------------------------------------------------------------------------------


async def language_map(ctx: LensContext) -> v.LensLanguageMap:
    conflicts = [c for c in await _conflicts(ctx, None) if c.claim_a.attribute == "language_share"]
    async with read_session() as s:
        views = await _load_views(s, ctx, categories=("language",), attributes=frozenset({"language_share"}))
        languages = {row.code: row for row in (await s.execute(select(m.Language))).scalars()}
    india = (await regions.list_regions("IN", 100, 0)).items
    census = load_census()["states"]
    shares: dict[str, list[ClaimView]] = defaultdict(list)
    for view in views:
        if view.scope.region_code and isinstance(view.value, int | float):
            shares[view.scope.region_code].append(view)
    rows = []
    for region in india:
        entries: dict[str, v.LensLanguageEntry] = {}
        for lang in region.languages:
            entries[lang.code] = v.LensLanguageEntry(
                code=lang.code, name=lang.name, native_name=lang.native_name, script=lang.script, role=lang.role, shares=[], disputed=False)
        table = census.get(region.code)
        for row in (table or {}).get("languages", []):  # the census table itself, as data: every covered state, built or not
            code = row["iso639_1"] or lens_data._code_by_name(row["name"])
            key = code if code in entries else (code or f"language:{row['name'].casefold()}")
            share = round(100 * row["speakers"] / table["population"], 2)  # type: ignore[index]
            known = languages.get(code) if code else None
            base = entries.get(key)
            entries[key] = (base.model_copy(update={"census_share": share, "census_speakers": row["speakers"]}) if base else v.LensLanguageEntry(
                code=code if known else None, name=known.name if known else row["name"], native_name=known.native_name if known else None,
                script=known.script if known else None, role=None, shares=[], disputed=False, census_share=share,
                census_speakers=row["speakers"]))
        grouped: dict[str, list[ClaimView]] = defaultdict(list)
        for view in shares.get(region.code, []):
            grouped[logic.language_key(view)].append(view)
        for key, claims in grouped.items():
            guess = logic.share_language_name(claims[0])
            key = key if key in entries else next((k for k, e in entries.items() if e.name.casefold() == guess.casefold()), key)  # noqa: PLW2901
            known = languages.get(key)
            base = entries.get(key)
            found = sorted((v.LensShare(percent=float(c.value), speakers=None, claim=c) for c in claims), key=lambda x: -x.percent)
            values = {round(x.percent, 4) for x in found}
            entries[key] = v.LensLanguageEntry(
                code=key if known else None, name=base.name if base else (known.name if known else guess),
                native_name=base.native_name if base else (known.native_name if known else None),
                script=base.script if base else (known.script if known else None), role=base.role if base else None,
                shares=found, disputed=len(values) > 1, census_share=base.census_share if base else None,
                census_speakers=base.census_speakers if base else None)
        order = {"primary": 0, "secondary": 1, "code_mixed": 2, None: 3}

        def size(e: v.LensLanguageEntry) -> float:
            return max([x.percent for x in e.shares] + ([e.census_share] if e.census_share is not None else []), default=-1)

        ranked = sorted(entries.values(), key=lambda e: (order[e.role], -size(e), e.name))
        rows.append(v.LensLanguageRegion(
            region_code=region.code, region_name=region.name, primary_language=region.primary_language,
            primary_script=region.primary_script, has_census=bool(shares.get(region.code)) or table is not None, languages=ranked,
            conflicts=[c for c in conflicts if c.region_code == region.code]))
    return v.LensLanguageMap(
        campaign_id=ctx.campaign_id, workspace_id=ctx.workspace_id, mode=ctx.mode,  # type: ignore[arg-type]
        mode_label=mode_label(ctx.mode), generated_at=utcnow(), period="2011", regions=rows,
        code_mixing=v.LensCodeMixing(
            status="no_sourced_claims",
            note="Code-mixed varieties (for example Tanglish or Hinglish) are not covered: no sourced claim about them has been collected, so none is shown."),
        sources=logic.summarise_sources(views),
        limitations=[
            "Shares are from the Census of India 2011 (mother tongue, table C-16): more than a decade old and never a current language mix.",
            "Mother tongue is the language a person reports from childhood. It is not proficiency, media language or the language to advertise in.",
            "The census table covers the 31 states and union territories whose territory is unchanged since 2011; Andhra Pradesh, Telangana, "
            "Jammu and Kashmir, Ladakh and Dadra and Nagar Haveli and Daman and Diu have none. Roles (principal, additional) come from "
            "reference data and are not speaker shares.",
            "Where two sources give different shares for a language, both are shown and the conflict is open."])
