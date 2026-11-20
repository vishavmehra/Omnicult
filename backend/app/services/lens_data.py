"""Market Lens state data: what public datasets say about every state, shown as data beside the claims.

Claims feed the Evidence Meter; this does not. Every state, built or not, gets the figures the datasets publish for it:
State facts (data.gov.in and Google Data Commons), Search pulse (Google Trends in BigQuery), Census 2011 mother tongues, its public-holiday list
(python-holidays) and its official languages (reference data). Every number is copied from its dataset; the code only picks
the newest period, orders, counts and finds the highest value in a row. Reads never call a source: live campaigns read the
stored snapshots (State facts loads its all-states recording first when the table is empty, as the seed job does), demo
campaigns read the recordings.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.integrations.culture.adapters.census import load_census
from app.integrations.culture.adapters.datagov import NATIONAL, RESOURCES
from app.reference import india
from app.schemas import lens as v
from app.services import lens_moments, state_facts
from app.services.lens import LensContext

LANGUAGE_NAMES = {row.code: row.name for row in india.LANGUAGES}
REFERENCE = {row.code: row for row in india.REGIONS}
TOP_TERMS = 3
TOP_LANGUAGES = 4
NEXT_HOLIDAYS = 3
SOURCE_PERIODS = sorted({metric.period for r in RESOURCES for metric in r.metrics})


@dataclass
class Bundle:
    """Everything the state data of a page needs, read once."""

    mode: str
    today: date
    facts: dict[str, list[Any]] = field(default_factory=dict)  # region code (and "IN") -> snapshot rows
    facts_at: datetime | None = None
    pulse: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # region code -> rows of the newest week of each kind
    pulse_week: date | None = None
    pulse_at: datetime | None = None


# --- loading ------------------------------------------------------------------------------------------------------


async def _live_facts() -> tuple[list[Any], datetime | None]:
    async with read_session() as s:
        rows = list((await s.execute(select(m.StateFactSnapshot))).scalars())
    if not rows:  # a database the seed job has not reached yet: load the same recording it would, once
        async with state_facts._LOCK:
            async with read_session() as s:
                empty = not await s.scalar(select(func.count(m.StateFactSnapshot.id)))
            if empty:
                async with session() as s, s.begin():
                    await state_facts.load_recording(s)
        async with read_session() as s:
            rows = list((await s.execute(select(m.StateFactSnapshot))).scalars())
    return rows, max((r.retrieved_at for r in rows), default=None)


def _newest_week(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    newest = {kind: max((r["week"] for r in rows if r["kind"] == kind), default=None) for kind in ("top", "rising")}
    return [r for r in rows if r["week"] == newest[r["kind"]]]


async def _live_pulse() -> tuple[list[dict[str, Any]], datetime | None]:
    t = m.LensSearchPulse
    async with read_session() as s:
        newest = dict((await s.execute(select(t.kind, func.max(t.week)).group_by(t.kind))).all())
        if not newest:
            return [], None
        rows = list((await s.execute(select(t).where(or_(*(
            (t.kind == kind) & (t.week == week) for kind, week in newest.items()))))).scalars())
    return [{k: getattr(r, k) for k in ("region_code", "kind", "term", "week", "rank", "score", "percent_gain")} for r in rows], \
        max((r.retrieved_at for r in rows), default=None)


def _demo_pulse() -> tuple[list[dict[str, Any]], datetime]:
    from app.services import lens_search_pulse  # noqa: PLC0415 - it imports lens_trends, which imports lens_views, which imports this

    data = lens_search_pulse.recorded()
    columns = data["columns"]
    rows = [{**dict(zip(columns, r, strict=True)), "week": date.fromisoformat(r[columns.index("week")])} for r in data["rows"]]
    return _newest_week(rows), datetime.combine(date.fromisoformat(data["recorded_on"]), datetime.min.time(), tzinfo=UTC)


async def load(ctx: LensContext, today: date | None = None) -> Bundle:
    bundle = Bundle(mode=ctx.mode, today=today or utcnow().date())
    if ctx.mode == "demo":
        facts, bundle.facts_at = state_facts.recorded_rows(), state_facts.recorded_at()
        pulse, bundle.pulse_at = _demo_pulse()
    else:
        facts, bundle.facts_at = await _live_facts()
        pulse, bundle.pulse_at = await _live_pulse()
    for row in facts:
        bundle.facts.setdefault(row.region_code, []).append(row)
    for row in pulse:
        bundle.pulse.setdefault(row["region_code"], []).append(row)
    bundle.pulse_week = max((r["week"] for r in pulse), default=None)
    return bundle


# --- one state ----------------------------------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def figures(bundle: Bundle, code: str) -> list[v.LensFigure]:
    """The state's State facts as flat figures: each fact's newest value, and each of its parts (rural, urban, women, men)."""
    groups = state_facts.facts_from_rows(bundle.facts.get(code, []) + bundle.facts.get(NATIONAL, []), code)
    out: list[v.LensFigure] = []
    for group in groups:
        for fact in group.facts:
            if fact.value is not None:
                out.append(v.LensFigure(key=fact.key, label=fact.label, unit=fact.unit, value=fact.value, national=fact.national,
                                        period=fact.period))
            for part in fact.parts:
                out.append(v.LensFigure(key=f"{fact.key}_{_slug(part.label)}", label=f"{fact.label}, {part.label.lower()}",
                                        unit=fact.unit, value=part.value, national=part.national, period=part.period))
    return out


def _role(code: str, language: str | None) -> str | None:
    row = REFERENCE.get(code)
    if row is None or language is None:
        return None
    return "primary" if language == row.primary else "secondary" if language in row.secondary else None


def _code_by_name(name: str) -> str | None:
    """The reference language code of a census language name ("Konkani" -> kok, "Manipuri" -> mni)."""
    key = name.casefold()
    for row in india.LANGUAGES:
        if key == row.name.casefold() or f"({key})" in row.name.casefold():
            return row.code
    return None


def languages(code: str) -> tuple[list[v.LensLanguageFact], int | None]:
    """Census 2011 mother tongues by share where the census covers the state; otherwise the reference languages."""
    state = load_census()["states"].get(code)
    if state:
        population = state["population"]
        ranked = sorted(state["languages"], key=lambda lang: -lang["speakers"])[:TOP_LANGUAGES]
        out = []
        for lang in ranked:
            lc = lang["iso639_1"] or _code_by_name(lang["name"])
            out.append(v.LensLanguageFact(code=lc, name=lang["name"], role=_role(code, lc),  # type: ignore[arg-type]
                                          share=round(100 * lang["speakers"] / population, 2)))
        return out, population
    row = REFERENCE.get(code)
    if row is None:
        return [], None
    return [v.LensLanguageFact(code=lc, name=LANGUAGE_NAMES.get(lc, lc), role=_role(code, lc), share=None)  # type: ignore[arg-type]
            for lc in (row.primary, *row.secondary)], None


def _terms(rows: list[dict[str, Any]], kind: str) -> list[v.LensSearchTerm]:
    scored = [r for r in rows if r["kind"] == kind and r["score"] is not None]
    scored.sort(key=lambda r: (-r["score"], -(r["percent_gain"] or 0), r["rank"] or 0, r["term"]))
    return [v.LensSearchTerm(term=r["term"], kind=kind, score=r["score"], percent_gain=r["percent_gain"]) for r in scored[:TOP_TERMS]]  # type: ignore[arg-type]


def state_data(bundle: Bundle, code: str) -> v.LensStateData:
    figs = figures(bundle, code)
    langs, population = languages(code)
    pulse = bundle.pulse.get(code, [])
    year = bundle.today.year
    this_year = lens_moments.state_holidays(code, year)
    upcoming = [(d, n) for d, n in (*this_year, *lens_moments.state_holidays(code, year + 1)) if d >= bundle.today][:NEXT_HOLIDAYS]
    families: list[str] = []
    if figs:
        families.append("state_facts")
    if pulse:
        families.append("search_pulse")
    if population:
        families.append("census_2011")
    if this_year:
        families.append("public_holidays")
    if code in REFERENCE:
        families.append("reference")
    return v.LensStateData(
        figures=figs, languages=langs, census_population=population, searches=_terms(pulse, "top"), rising=_terms(pulse, "rising"),
        search_week=max((r["week"] for r in pulse), default=None), holidays_year=year, holidays=len(this_year),
        next_holidays=[v.LensHoliday(date=d, name=n) for d, n in upcoming], families=families)  # type: ignore[arg-type]


def data_sources(bundle: Bundle, families: set[str]) -> list[v.LensDataSource]:
    """The datasets behind the state data on a page, in a fixed order, only those that gave something."""
    census = load_census()
    rows = [
        v.LensDataSource(
            key="state_facts", label="State facts", publisher="State-wise statistics", url=None,
            detail="NFHS-5 2019-21, NFHS-4 2015, Census 2011, tele-density and internet subscriptions 2024, tourist visits 2023 and 2024, "
                   "income per person 2022-23, household spending 2023-24, homes without internet 2025, population projected to 2026, "
                   "average monthly wage, electricity use and a development score. By state, with the all-India figure where there is one.",
            period=f"{SOURCE_PERIODS[0]} to {SOURCE_PERIODS[-1]}", retrieved_at=bundle.facts_at),
        v.LensDataSource(
            key="search_pulse", label="Searches", publisher="Google Trends public dataset (BigQuery)",
            url="https://console.cloud.google.com/marketplace/product/bigquery-public-datasets/google-search-trends",
            detail="Top and rising searches of the newest week, with each state's 0 to 100 score.",
            period=f"Week of {bundle.pulse_week:%d %b %Y}".replace(" 0", " ") if bundle.pulse_week else None, retrieved_at=bundle.pulse_at),
        v.LensDataSource(
            key="census_2011", label="Mother tongues", publisher="Census of India 2011, table C-16", url="https://censusindia.gov.in/nada/",
            detail="Mother-tongue shares for the 31 states and union territories whose territory is unchanged since 2011. Never a current language mix.",
            period="2011", retrieved_at=datetime.combine(date.fromisoformat(census["retrieved_on"]), datetime.min.time(), tzinfo=UTC)),
        v.LensDataSource(
            key="public_holidays", label="Public holidays", publisher=f"python-holidays {lens_moments.holidays_version()}",
            url="https://pypi.org/project/holidays/", detail="Each state's public-holiday list, as the package release encodes it.",
            period=str(bundle.today.year), retrieved_at=None),
        v.LensDataSource(
            key="reference", label="Official languages", publisher="State and union territory official-language legislation",
            url=None, detail="Principal and additional official languages and their scripts. Not a speaker share.", period=None, retrieved_at=None),
    ]
    return [r for r in rows if r.key in families]


async def all_states(ctx: LensContext, codes: list[str] | None = None) -> tuple[dict[str, v.LensStateData], list[v.LensDataSource]]:
    bundle = await load(ctx)
    wanted = codes if codes is not None else [r.code for r in india.REGIONS]
    datas = {code: state_data(bundle, code) for code in wanted}
    families = {f for d in datas.values() for f in d.families}
    return datas, data_sources(bundle, families)


# --- comparison ---------------------------------------------------------------------------------------------------


def data_rows(datas: dict[str, v.LensStateData]) -> list[v.LensDataRow]:
    """One row per figure any compared state has, in the State facts order. `highest` names the state or states with the
    largest value when at least two have one: a fact about the numbers, not a judgement (higher is not always better)."""
    order: list[str] = []
    meta: dict[str, v.LensFigure] = {}
    for data in datas.values():
        for fig in data.figures:
            if fig.key not in meta:
                order.append(fig.key)
                meta[fig.key] = fig
    rows = []
    for key in order:
        cells = []
        for code, data in datas.items():
            fig = next((f for f in data.figures if f.key == key), None)
            cells.append(v.LensDataCell(region_code=code, value=fig.value if fig else None, national=fig.national if fig else None,
                                        period=fig.period if fig else None))
        values = [c.value for c in cells if c.value is not None]
        top = max(values) if len(values) >= 2 else None
        rows.append(v.LensDataRow(key=key, label=meta[key].label, unit=meta[key].unit, cells=cells,
                                  highest=[c.region_code for c in cells if top is not None and c.value == top]))
    return rows


# --- the campaign's states ----------------------------------------------------------------------------------------


async def campaign_roles(s: AsyncSession, campaign_id: Any) -> dict[str, str]:
    """origin and targets from the latest saved brief; without one, the campaign's region-coded target markets as targets."""
    brief = (await s.execute(
        select(m.CampaignBriefRow).where(m.CampaignBriefRow.campaign_id == campaign_id)
        .order_by(m.CampaignBriefRow.version_number.desc()).limit(1))).scalar_one_or_none()
    regions = (brief.content if brief else {}).get("regions") or {}
    roles: dict[str, str] = {}
    if regions.get("origin"):
        roles[regions["origin"]] = "origin"
    for code in regions.get("targets") or []:
        roles.setdefault(code, "target")
    if not roles:
        campaign = await s.get(m.Campaign, campaign_id)
        for market in (campaign.target_markets if campaign else []) or []:
            if isinstance(market, dict) and market.get("region_code"):
                roles.setdefault(market["region_code"], "target")
    return {code: role for code, role in roles.items() if code in REFERENCE}
