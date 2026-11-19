"""Shared pieces of Trend Radar and Category Shelf: a campaign's states and category, the sources a request reads, and how a
stored series becomes the measured edition the pages show.

Both features build on Market Lens (`services/lens.py`: its context, modes and claims) and read public data only: Wikipedia
pageviews (attention) and Wikidata statements. Demo campaigns read the recording in `app/fixtures/lens_t3_demo.py` and make
no network call; live campaigns read the live sources through `HttpFetcher` (User-Agent, bounded retries, cool-down) with a
cache in front and a minimum interval between refreshes of the same state.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import quote
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import lens_trends as trends
from app.core.config import Settings
from app.db import models as m
from app.db.session import read_session
from app.fixtures.lens_t3_demo import RecordedPageviewsSource, RecordedShelfSource
from app.integrations.culture import CultureService, InMemoryCacheStore
from app.integrations.culture.adapters.wikipedia_attention import WikipediaAttentionSource
from app.integrations.culture.base import CallLogRecord
from app.integrations.culture.regions import LANGUAGE_NAMES
from app.integrations.culture.shelf import CategoryPack, WikidataShelfSource, match_pack, pack_by_key, packs
from app.schemas import lens_t3 as v
from app.services.campaign_regions import campaign_region_codes
from app.services.lens import LensContext

logger = logging.getLogger(__name__)

SERIES_MONTHS = 24
_CACHE = InMemoryCacheStore()  # live pageviews, process-wide: a repeated refresh does not repeat free API calls
_LIVE: dict[str, object] = {}  # one live source per kind, so a cool-down a host asked for outlives a request


# --- sources -----------------------------------------------------------------------------------------------------


def make_trend_service(settings: Settings, mode: str) -> CultureService:
    """demo: the recording only. live: the Wikipedia pageviews adapter, cached for 12 hours."""
    if mode == "demo":
        return CultureService([RecordedPageviewsSource()], mode="fixture")
    source = _LIVE.get("pageviews")
    if source is None:
        source = _LIVE["pageviews"] = WikipediaAttentionSource(
            user_agent=settings.wikimedia_user_agent, timeout=settings.culture_http_timeout_seconds)
    return CultureService([source], cache=_CACHE, mode="live")  # type: ignore[list-item]


def make_shelf_source(settings: Settings, mode: str) -> RecordedShelfSource | WikidataShelfSource:
    if mode == "demo":
        return RecordedShelfSource()
    source = _LIVE.get("shelf")
    if source is None:
        source = _LIVE["shelf"] = WikidataShelfSource(
            user_agent=settings.wikimedia_user_agent, timeout=settings.culture_http_timeout_seconds)
    return source  # type: ignore[return-value]


def series_window(today: date) -> tuple[date, date]:
    """The 24 whole months ending with the last complete one (monthly pageviews exist from 2015-07)."""
    end = trends.month_start(today) - timedelta(days=1)
    return trends.add_months(trends.month_start(end), -(SERIES_MONTHS - 1)), end


def source_line(mode: str, *, what: str, taken_at: datetime | None = None) -> str:
    """The one quiet line each view carries about where its numbers come from."""
    if mode == "demo":
        return ""
    return f"Public data: {what}" + (f", retrieved {taken_at:%d %b %Y}".replace(" 0", " ") if taken_at else "")


# --- what the campaign says --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CampaignFacts:
    regions: list[str]
    window: tuple[date, date] | None
    category_text: str | None


async def campaign_facts(s: AsyncSession, ctx: LensContext) -> CampaignFacts:
    """The states, dates and category the campaign states: its latest saved brief, then its target markets."""
    campaign = await s.get(m.Campaign, ctx.campaign_id)
    brief = (await s.execute(
        select(m.CampaignBriefRow).where(m.CampaignBriefRow.campaign_id == ctx.campaign_id)
        .order_by(m.CampaignBriefRow.version_number.desc()).limit(1))).scalar_one_or_none()
    content = brief.content if brief else {}
    regions = content.get("regions") or {}
    codes = [c for c in [regions.get("origin"), *(regions.get("targets") or [])] if c]
    if not codes and campaign is not None:
        codes = campaign_region_codes(campaign.target_markets, None)[0]
    dates = content.get("dates") or {}
    window = None
    if dates.get("start") and dates.get("end"):
        window = (date.fromisoformat(str(dates["start"])), date.fromisoformat(str(dates["end"])))
    design = await s.scalar(select(m.BrandKitDesignRow.design).where(m.BrandKitDesignRow.project_id == ctx.project_id))
    text = (design or {}).get("category")
    if not text:
        text = await s.scalar(select(m.BrandKit.positioning).where(m.BrandKit.project_id == ctx.project_id))
    return CampaignFacts(list(dict.fromkeys(codes)), window, (text or "").strip()[:200] or None)


def category_ref(text: str | None, pack_key: str | None = None) -> tuple[v.LensCategoryRef, CategoryPack | None]:
    """Which category pack the campaign's category names. A request can name one when the text names none; nothing is guessed."""
    chosen = pack_by_key(pack_key) if pack_key else None
    if chosen is not None:
        return v.LensCategoryRef(text=text, pack_key=chosen.key, pack_label=chosen.label, status="chosen", note=None), chosen
    if not text:
        return v.LensCategoryRef(
            text=None, pack_key=None, pack_label=None, status="no_category",
            note="The brand kit states no category. Set one, or choose a category here."), None
    pack = match_pack(text)
    if pack is None:
        return v.LensCategoryRef(
            text=text, pack_key=None, pack_label=None, status="unmatched",
            note=f"\"{text}\" names none of the categories Market Lens covers. Choose the nearest one; nothing is guessed."), None
    return v.LensCategoryRef(text=text, pack_key=pack.key, pack_label=pack.label, status="matched", note=None), pack


def pack_options() -> list[v.LensCategoryPackOption]:
    return [v.LensCategoryPackOption(key=p.key, label=p.label, topics=[t.label for t in p.topics]) for p in packs()]


async def region_names(s: AsyncSession) -> dict[str, str]:
    return {code: name for code, name in (await s.execute(select(m.Region.code, m.Region.name).where(m.Region.is_active))).all()}


def edition_name(language: str | None) -> str | None:
    return LANGUAGE_NAMES.get(language) if language else None


# --- series ------------------------------------------------------------------------------------------------------


def stored_editions(series_editions: list) -> list[dict]:
    """TrendEditions as stored: points (and the edition's own monthly totals) as [YYYY-MM, views] pairs, nothing else."""
    return [{"language": e.language, "project": e.project, "article": e.article,
             "points": [[p.date.strftime("%Y-%m"), p.views] for p in e.points],
             "baseline": [[p.date.strftime("%Y-%m"), p.views] for p in e.baseline] if e.baseline else None} for e in series_editions]


def _pairs(pairs: list) -> list[trends.MonthPoint]:
    return trends.monthly([(date.fromisoformat(f"{month}-01"), int(views)) for month, views in pairs])


def month_points(edition: dict) -> list[trends.MonthPoint]:
    return _pairs(edition["points"])


def baseline_points(edition: dict) -> list[trends.MonthPoint] | None:
    return _pairs(edition["baseline"]) if edition.get("baseline") else None


def article_url(project: str, article: str) -> str:
    return f"https://{project}.org/wiki/{quote(article.replace(' ', '_'), safe='()')}"


def edition_view(edition: dict, regional_language: str | None) -> tuple[v.LensTrendEdition, trends.Measure]:
    points, baseline = month_points(edition), baseline_points(edition)
    measured = trends.measure(points, baseline)
    totals = {b.month: b.views for b in baseline or []}
    view = v.LensTrendEdition(
        language=edition["language"], language_name=LANGUAGE_NAMES.get(edition["language"], edition["language"]),
        project=edition["project"], article=edition["article"], article_url=article_url(edition["project"], edition["article"]),
        is_regional=edition["language"] == regional_language, months=len(points), total_views=sum(p.views for p in points),
        normalised=measured.normalised, recent_mean=measured.recent_mean, prior_mean=measured.prior_mean,
        recent_per_million=measured.recent_share, prior_per_million=measured.prior_share, change=measured.change,
        raw_change=measured.raw_change, edition_change=measured.edition_change, slope_per_month=measured.slope_per_month,
        quarter_change=measured.quarter_change, direction=measured.direction,
        series=[v.LensMonth(
            month=p.month.strftime("%Y-%m"), views=p.views, edition_views=totals.get(p.month) or None,
            per_million=round(p.views / totals[p.month] * 1_000_000, 2) if totals.get(p.month) else None) for p in points])
    return view, measured


def pick_editions(editions: list[dict], regional_language: str | None) -> tuple[dict | None, dict | None, str]:
    """(primary, reference, basis). The state's own language edition leads and the English edition is the reference; an
    article that has no regional edition is read from English alone, which readers worldwide use, and says so."""
    regional = next((e for e in editions if e["language"] == regional_language and regional_language != "en"), None)
    english = next((e for e in editions if e["language"] == "en"), None)
    if regional is not None:
        return regional, english, "regional_edition"
    return english, None, "english_only"


def windows_of(measured: trends.Measure) -> v.LensTrendWindows | None:
    windows = (measured.recent_window, measured.prior_window, measured.quarter_window, measured.quarter_year_ago_window)
    if any(w is None for w in windows):
        return None
    (rf, rt), (pf, pt), (qf, qt), (af, at) = [(a.strftime("%Y-%m"), b.strftime("%Y-%m")) for a, b in windows]  # type: ignore[misc,union-attr]
    return v.LensTrendWindows(
        recent_from=rf, recent_to=rt, prior_from=pf, prior_to=pt, quarter_from=qf, quarter_to=qt, quarter_ago_from=af, quarter_ago_to=at)


def parse_time(value: str | datetime) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def calls_to_rows(ctx: LensContext, log: list[CallLogRecord]) -> list[m.CultureCall]:
    """The culture call log of a refresh, stored so Data Health counts real attempts and errors (build_id is empty)."""
    return [
        m.CultureCall(
            id=uuid4(), workspace_id=ctx.workspace_id, build_id=None, mode=ctx.mode, source=c.source, operation=c.operation,
            request_hash=c.request_hash, status=c.status, cached=c.cached, result_count=c.result_count, duration_ms=c.duration_ms,
            error_type=c.error_type, error=c.error, retrieved_at=c.retrieved_at) for c in log]


async def has_demo_snapshots(ctx: LensContext) -> bool:
    async with read_session() as s:
        return await s.scalar(select(m.LensTrendBatch.id).where(
            m.LensTrendBatch.workspace_id == ctx.workspace_id, m.LensTrendBatch.mode == ctx.mode).limit(1)) is not None


async def seed_lens_t3_demo(user_id: UUID, campaign_id: UUID) -> None:
    """Demo hook for services/demo_journey.py: store the recorded Trend Radar series and Category Shelf discovery for the demo
    campaign so both views open populated. No network call and no model call; idempotent."""
    from app.services import lens, lens_shelf, lens_trends  # noqa: PLC0415 - these import this module

    ctx = await lens.lens_context(user_id, campaign_id, writable=True)
    if ctx.mode != "demo":
        return
    if not await has_demo_snapshots(ctx):
        await lens_trends.refresh_radar(user_id, campaign_id, v.LensTrendRefreshRequest())
    async with read_session() as s:
        shelf = await s.scalar(select(m.LensShelfSnapshot.id).where(
            m.LensShelfSnapshot.workspace_id == ctx.workspace_id, m.LensShelfSnapshot.mode == "demo").limit(1))
    if shelf is None:
        await lens_shelf.refresh_shelf(user_id, campaign_id, v.LensShelfRefreshRequest())

