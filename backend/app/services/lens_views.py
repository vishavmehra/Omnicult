"""Market Lens reads: the atlas, a state profile, a comparison, the moment calendar and the language map.

Everything is built from stored claims through the existing evidence code (`claims`, `data_health`), so the Evidence
Meter, confidence and conflicts are the ones used everywhere else. Reads never call a source: they show what a build
stored, and say so when a state has not been built. Demo campaigns read demo claims only; live campaigns read live only.
"""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import lens as logic
from app.core.errors import NotFound, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session
from app.schemas import lens as v
from app.schemas.common import ErrorDetail
from app.schemas.regions import ClaimView, Conflict, Region
from app.services import claims as claim_service
from app.services import data_health, regions
from app.services.claims import LIVE_STATUSES, _claim_view, _open_conflicts_by_claim, _sources
from app.services.lens import LensContext, build_view, latest_builds, mode_label, region_names

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


async def atlas(ctx: LensContext) -> v.LensAtlas:
    await _conflicts(ctx, None)  # records conflicts so the per-state counts include them
    health = await data_health.workspace_data_health(ctx.user_id, ctx.workspace_id, ctx.mode)  # type: ignore[arg-type]
    coverage = {c.region_code: c for c in health.regions}
    async with read_session() as s:
        views = await _load_views(s, ctx)
        builds = await latest_builds(s, ctx.workspace_id, ctx.mode)
        names = await region_names(s)
    india = (await regions.list_regions("IN", 100, 0)).items
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
            last_build=build_view(row, names.get(row.region_code, row.region_code)) if row else None))
    summary = v.LensAtlasSummary(
        states_total=len(states), states_with_claims=sum(1 for s_ in states if s_.claims), weak=sum(1 for s_ in states if s_.strength == "weak"),
        partial=sum(1 for s_ in states if s_.strength == "partial"), solid=sum(1 for s_ in states if s_.strength == "solid"),
        claims=sum(s_.claims for s_ in states), open_conflicts=sum(s_.open_conflicts for s_ in states))
    return v.LensAtlas(
        campaign_id=ctx.campaign_id, workspace_id=ctx.workspace_id, mode=ctx.mode,  # type: ignore[arg-type]
        mode_label=mode_label(ctx.mode), generated_at=utcnow(), summary=summary, states=states,
        sources=logic.summarise_sources(views),
        limitations=[
            "Evidence strength is the Evidence Meter's rating of the claims stored for a state. Weak means little is recorded, not that the state matters little.",
            "Four states (Maharashtra, Tamil Nadu, Kerala, West Bengal) have curated festival, food and custom references and census language shares; "
            "the other states have public-holiday dates at most.",
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
        sources=logic.summarise_sources(every), gaps=gaps,
        limitations=[MISSING_NOTE, CONFIDENCE_NOTE, CAMPAIGN_NOTE,
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
            high=meter.confidence.high, built=p.region.code in built))
    return v.LensCompare(
        campaign_id=ctx.campaign_id, workspace_id=ctx.workspace_id, mode=ctx.mode,  # type: ignore[arg-type]
        mode_label=mode_label(ctx.mode), generated_at=utcnow(), regions=cols, rows=logic.compare_rows(per_region),
        sources=logic.summarise_sources([c for items in per_region.values() for c in items]),
        limitations=[
            "A claim in two columns means two sources were found, not that the two things mean the same. Check the evidence before treating them as equivalent.",
            MISSING_NOTE, CONFIDENCE_NOTE, CAMPAIGN_NOTE])


# --- moment calendar ---------------------------------------------------------------------------------------------


async def calendar(ctx: LensContext, region_code: str, year: int, window: v.LensWindow | None) -> v.LensCalendar:
    region = await _region(region_code)
    conflicts = [c for c in await _conflicts(ctx, region_code) if c.claim_a.category in ("festival", "moment")]
    async with read_session() as s:
        views = await _load_views(s, ctx, region_codes=[region_code], categories=("festival", "moment"))
    years = sorted({int(c.scope.period) for c in views if c.attribute == logic.HOLIDAY_ATTRIBUTE and c.scope.period and c.scope.period.isdigit()})
    dated, timed = logic.calendar_entries(views, year=year, window=window)
    gaps = []
    if not views:
        gaps.append("No festival or moment claims are stored for this state in this mode. Build the state first.")
    elif year not in years:
        gaps.append(f"No public-holiday dates are stored for {year}" + (f" (stored years: {', '.join(map(str, years))})." if years else ".")
                    + " Build the state with that year to add them.")
    return v.LensCalendar(
        campaign_id=ctx.campaign_id, workspace_id=ctx.workspace_id, mode=ctx.mode,  # type: ignore[arg-type]
        mode_label=mode_label(ctx.mode), generated_at=utcnow(), region=region, year=year, years_available=years, window=window,
        months=logic.months_of(dated), timed=timed, conflicts=conflicts, sources=logic.summarise_sources(views), gaps=gaps,
        limitations=[
            "Exact dates come from a public-holiday list. A festival that is not a public holiday has no exact date here, only the timing its sources state.",
            "Movable festival dates follow the holiday package's release: verify against a current panchang or official notice before a launch.",
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
        grouped: dict[str, list[ClaimView]] = defaultdict(list)
        for view in shares.get(region.code, []):
            grouped[logic.language_key(view)].append(view)
        for key, claims in grouped.items():
            known = languages.get(key)
            base = entries.get(key)
            found = sorted((v.LensShare(percent=float(c.value), speakers=None, claim=c) for c in claims), key=lambda x: -x.percent)
            values = {round(x.percent, 4) for x in found}
            entries[key] = v.LensLanguageEntry(
                code=key if known else None, name=base.name if base else (known.name if known else logic.share_language_name(claims[0])),
                native_name=base.native_name if base else (known.native_name if known else None),
                script=base.script if base else (known.script if known else None), role=base.role if base else None,
                shares=found, disputed=len(values) > 1)
        order = {"primary": 0, "secondary": 1, "code_mixed": 2, None: 3}
        ranked = sorted(entries.values(), key=lambda e: (order[e.role], -max((x.percent for x in e.shares), default=-1), e.name))
        rows.append(v.LensLanguageRegion(
            region_code=region.code, region_name=region.name, primary_language=region.primary_language,
            primary_script=region.primary_script, has_census=bool(shares.get(region.code)), languages=ranked,
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
            "Only four states have census shares here. Roles (principal, additional) for every state come from reference data and are not speaker shares.",
            "Where two sources give different shares for a language, both are shown and the conflict is open."])
