"""State facts: official state-wise statistics (data.gov.in and Google Data Commons) shown beside a state's profile in Market Lens.

Why not Lens claims: claims are cultural evidence that feeds the Evidence Meter, confidence and conflicts; these are plain
published statistics with a year, compared with the all-India figure, so they are their own typed panel and the meter is
untouched. They are public and the same for every workspace, so they are stored once (`state_fact_snapshots`).

Reads never wait for a schedule: the read path serves the latest snapshot and pulls a resource itself only when none exists or
the stored copy is older than that resource's cadence (the scheduler normally keeps them fresh). A resource whose own
`updated_date` has not changed is not downloaded again. Demo campaigns read the recorded fixture and never touch the network
or the table.

Two sources share the one table. data.gov.in is a recorded source on the deployed service (it refuses Google Cloud addresses, so
the seed job loads its recording). Google Data Commons is fetched live: one source (`datacommons`) whose rows carry resource ids
`datacommons:<variable>` and a provenance per figure; two requests fetch every state. When it fails the stored copy is served
beside the data.gov.in figures. A metric belongs to exactly one source, so the read path merges them without overwriting.
"""

import asyncio
import json
import logging
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import (
    AppError,
    NotFound,
    ProviderFailed,
    ProviderNotConfigured,
    ProviderTimeout,
    RateLimited,
)
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.integrations.culture.adapters.datagov import (
    BY_KEY,
    NATIONAL,
    RESOURCES,
    DataGovClient,
    Pull,
    Resource,
    Snapshot,
    parse_records,
)
from app.integrations.culture.adapters.datacommons import CADENCE_DAYS as DC_CADENCE_DAYS
from app.integrations.culture.adapters.datacommons import RESOURCE_PREFIX as DC_PREFIX
from app.integrations.culture.adapters.datacommons import DataCommonsClient, DcPull, parse_responses
from app.integrations.culture.base import CultureSourceError
from app.schemas import state_facts as v
from app.services.lens import LensContext, lens_context, region_names
from app.services.common import WRITE_ROLES, get_owned

logger = logging.getLogger(__name__)

# Every state, as the API sent it: demo campaigns read it, and the seed job loads it into the deployed database.
ALL_STATES_FILE = RECORDED_FILE = Path(__file__).resolve().parent.parent / "fixtures" / "state_facts" / "all_states.json"
DATACOMMONS_FILE = ALL_STATES_FILE.with_name("datacommons_states.json")  # Google Data Commons as `scripts/record_datacommons.py` saved it
DATACOMMONS = "datacommons"  # the key of that source in refresh summaries and `only=`
MANUAL_REFRESH_GAP = timedelta(seconds=60)  # an editor's refresh is refused when every resource was checked this recently
FAILURE_BACKOFF_SECONDS = 300.0  # after a failed pull the read path leaves that resource alone for this long
_LOCK = asyncio.Lock()  # one pull at a time per process: the reads and the scheduler never both download the same resource
_BACKOFF: dict[str, float] = {}  # resource key -> monotonic time before which the read path does not try again


# --- what is shown ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FactDef:
    key: str
    group: v.FactGroupKey
    label: str
    unit: v.FactUnit
    metric: str  # the stored metric of `value`; "" when the fact is only its parts
    parts: tuple[tuple[str, str], ...] = ()  # (label, stored metric)


GROUPS: tuple[tuple[v.FactGroupKey, str], ...] = (
    ("population", "Population"), ("connectivity", "Phones and internet"), ("economy", "Income and spending"), ("homes", "Homes"),
    ("people", "People and learning"), ("health", "Health"), ("visitors", "Visitors"))
FACTS: tuple[FactDef, ...] = (
    FactDef("women_mobile", "connectivity", "Women with a phone of their own", "percent", "women_mobile"),
    FactDef("women_internet", "connectivity", "Women who have used the internet", "percent", "women_internet"),
    FactDef("men_internet", "connectivity", "Men who have used the internet", "percent", "men_internet"),
    FactDef("teledensity", "connectivity", "Phone connections per 100 people", "per100", "teledensity"),
    FactDef("internet_per100", "connectivity", "Internet subscribers per 100 people", "per100", "internet_per100",
            (("Rural", "internet_per100_rural"), ("Urban", "internet_per100_urban"))),
    FactDef("home_no_internet", "connectivity", "Households without internet at home", "percent", "home_no_internet",
            (("Rural", "home_no_internet_rural"), ("Urban", "home_no_internet_urban"))),
    FactDef("youth_email", "connectivity", "People aged 15 to 29 who can email a file", "percent", "youth_email_attachment"),
    FactDef("nsdp", "economy", "Income per person, per year", "inr", "nsdp"),
    FactDef("mpce", "economy", "Spending per person, per month", "inr", "", (("Rural", "mpce_rural"), ("Urban", "mpce_urban"))),
    FactDef("women_bank", "economy", "Women with a bank account they use", "percent", "women_bank"),
    FactDef("health_insurance", "economy", "Households with health insurance", "percent", "health_insurance"),
    FactDef("electricity", "homes", "People in homes with electricity", "percent", "electricity"),
    FactDef("clean_fuel", "homes", "Households cooking with clean fuel", "percent", "clean_fuel"),
    FactDef("sanitation", "homes", "People in homes with improved sanitation", "percent", "sanitation"),
    FactDef("literacy", "people", "People who can read and write", "percent", "literacy"),
    FactDef("urban_share", "people", "People living in towns and cities", "percent", "urban_share"),
    FactDef("under15", "people", "People under 15", "percent", "under15"),
    FactDef("schooling", "people", "Adults (15 to 49) with ten or more years of school", "percent", "",
            (("Women", "women_school10"), ("Men", "men_school10"))),
    FactDef("population", "population", "People living here (projected)", "million", "population"),
    FactDef("sex_ratio", "population", "Women for every 1,000 men", "whole", "sex_ratio"),
    FactDef("density", "population", "People per square kilometre", "whole", "density"),
    FactDef("household_size", "population", "People per household", "decimal", "household_size"),
    FactDef("fertility", "population", "Children per woman", "decimal", "fertility"),
    FactDef("wage_monthly", "economy", "Average monthly wage of a worker", "inr", "wage_monthly"),
    FactDef("electricity_use", "economy", "Electricity available per person, per year (kWh)", "whole", "electricity_use"),
    FactDef("sdg_score", "people", "Sustainable development score, out of 100", "whole", "sdg_score"),
    FactDef("anaemia_women", "health", "Women (15 to 49, not pregnant) with anaemia", "percent", "anaemia_women"),
    FactDef("stunting", "health", "Children under 5 who are stunted", "percent", "stunting"),
    FactDef("tourist_visits_domestic", "visitors", "Domestic tourist visits in a year", "million", "tourist_visits_domestic"),
    FactDef("tourist_visits_foreign", "visitors", "Foreign tourist visits in a year", "million", "tourist_visits_foreign"),
)


def facts_from_rows(rows: Iterable[Any], region_code: str) -> list[v.StateFactGroup]:
    """Group a state's stored rows into the facts shown. Pure: rows need `region_code`, `metric`, `period` and `value`."""
    mine: dict[str, dict[str, float]] = defaultdict(dict)
    national: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        target = mine if row.region_code == region_code else national if row.region_code == NATIONAL else None
        if target is not None:
            target[row.metric][row.period] = row.value
    groups: list[v.StateFactGroup] = []
    for group_key, title in GROUPS:
        facts: list[v.StateFact] = []
        for d in (f for f in FACTS if f.group == group_key):
            periods = {p for metric in ([d.metric] if d.metric else []) + [mt for _, mt in d.parts] for p in mine.get(metric, {})}
            if not periods:
                continue
            latest = max(periods)
            parts = [v.StateFactPart(label=label, value=mine[mt][latest], national=national.get(mt, {}).get(latest), period=latest)
                     for label, mt in d.parts if latest in mine.get(mt, {})]
            own = mine.get(d.metric, {})
            if d.metric and latest not in own and not parts:
                continue
            facts.append(v.StateFact(
                key=d.key, label=d.label, unit=d.unit, value=own.get(latest), period=latest,
                national=national.get(d.metric, {}).get(latest) if d.metric else None,
                series=[v.StateFactPoint(period=p, value=own[p]) for p in sorted(own)], parts=parts))
        if facts:
            groups.append(v.StateFactGroup(key=group_key, title=title, facts=facts))
    return groups


# --- demo: the recorded snapshot ----------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def recorded() -> dict[str, Any]:
    return json.loads(RECORDED_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def recorded_datacommons() -> dict[str, Any]:
    return json.loads(DATACOMMONS_FILE.read_text(encoding="utf-8"))


def recorded_rows() -> list[Snapshot]:
    """The recorded API records of both sources, parsed by the same code a live pull uses."""
    rows: list[Snapshot] = []
    for key, saved in recorded()["resources"].items():
        rows.extend(parse_records(BY_KEY[key], saved["records"])[0])
    dc = recorded_datacommons()
    return rows + parse_responses(dc["latest"], dc["series"])[0]


def _day(recorded_on: str) -> datetime:
    return datetime.combine(date.fromisoformat(recorded_on), datetime.min.time(), tzinfo=UTC)


def recorded_at() -> datetime:
    return max(_day(recorded()["recorded_on"]), _day(recorded_datacommons()["recorded_on"]))


class RecordedClient:
    """data.gov.in as `scripts/record_state_facts.py --all` saved it: answers `probe` and `pull` from the file, so loading it
    runs the same parsing and upsert code as a live refresh. data.gov.in refuses requests from Google Cloud addresses, so the
    deployed database is filled from this recording (the seed job) instead of a live pull."""

    def __init__(self, resources: dict[str, Any]) -> None:
        self.resources = resources

    def _updated(self, resource: Resource) -> datetime | None:
        value = self.resources[resource.key]["updated_date"]
        return datetime.fromisoformat(value) if value else None

    async def probe(self, resource: Resource) -> tuple[datetime | None, int]:
        return self._updated(resource), int(self.resources[resource.key]["total"])

    async def pull(self, resource: Resource) -> Pull:
        saved = self.resources[resource.key]
        rows, unmapped = parse_records(resource, saved["records"])
        return Pull(resource.resource_id, self._updated(resource), int(saved["total"]), rows, unmapped)


class RecordedDcClient:
    """Google Data Commons as `scripts/record_datacommons.py` saved it: answers `pull` from the file, so loading it runs the same
    parsing and upsert code as a live refresh."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    async def pull(self) -> DcPull:
        raw = {"latest": self.payload["latest"], "series": self.payload["series"]}
        rows, empty = parse_responses(raw["latest"], raw["series"])
        return DcPull(rows, raw, empty)


async def load_recording(s: AsyncSession, path: Path = ALL_STATES_FILE, dc_path: Path = DATACOMMONS_FILE) -> v.StateFactsRefreshSummary:
    """Store both all-states recordings as snapshots (retrieved at their recording dates). Idempotent: a resource whose recorded
    `updated_date` is already stored, and Data Commons figures that have not changed, are skipped. The caller commits."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    gov = await refresh_state_facts(s, client=RecordedClient(payload["resources"]), now=_day(payload["recorded_on"]),  # type: ignore[arg-type]
                                    only=[r.key for r in RESOURCES])
    dc_payload = json.loads(dc_path.read_text(encoding="utf-8"))
    dc = await refresh_state_facts(s, dc_client=RecordedDcClient(dc_payload), now=_day(dc_payload["recorded_on"]), only=[DATACOMMONS])  # type: ignore[arg-type]
    return v.StateFactsRefreshSummary(resources=gov.resources + dc.resources, updated=gov.updated + dc.updated,
                                      unchanged=gov.unchanged + dc.unchanged, failed=gov.failed + dc.failed)


# --- pulling ------------------------------------------------------------------------------------------------------------


def _error_for(kind: str | None, message: str | None) -> AppError:
    """The typed API error for a failed pull. The wording names no source: the UI shows its own text, this is for API clients."""
    if kind == "not_configured":
        return ProviderNotConfigured("State statistics are not set up on this server: the data service key is missing.")
    if kind == "auth":
        return ProviderNotConfigured("The key for the state statistics service was rejected.")
    if kind == "rate_limited":
        return RateLimited("The state statistics service's request quota is used up; try again later.")
    if kind == "timeout":
        return ProviderTimeout("The state statistics service did not answer in time; try again later.")
    return ProviderFailed("The state statistics service is not answering; try again later.")


async def _refresh_one(s: AsyncSession, client: DataGovClient, resource: Resource, now: datetime) -> v.StateFactsResourceResult:
    stored, stored_at = (await s.execute(select(func.count(m.StateFactSnapshot.id), func.max(m.StateFactSnapshot.source_updated_at))
                                         .where(m.StateFactSnapshot.resource_id == resource.resource_id))).one()
    metrics = set((await s.execute(select(m.StateFactSnapshot.metric).where(
        m.StateFactSnapshot.resource_id == resource.resource_id).distinct())).scalars())
    complete = {metric.key for metric in resource.metrics} <= metrics  # a metric added to the catalogue needs one full pull
    if stored and complete:
        updated, _ = await client.probe(resource)
        if updated is not None and stored_at is not None and updated == stored_at:
            await s.execute(update(m.StateFactSnapshot).where(m.StateFactSnapshot.resource_id == resource.resource_id)
                            .values(retrieved_at=now))
            return v.StateFactsResourceResult(resource=resource.key, status="unchanged", rows=int(stored))
    pull = await client.pull(resource)
    existing = {(r.region_code, r.metric, r.period): r for r in (await s.execute(
        select(m.StateFactSnapshot).where(m.StateFactSnapshot.resource_id == resource.resource_id))).scalars()}
    for snap in pull.rows:
        row = existing.pop((snap.region_code, snap.metric, snap.period), None)
        if row is None:
            s.add(m.StateFactSnapshot(resource_id=resource.resource_id, region_code=snap.region_code, metric=snap.metric,
                                      period=snap.period, value=snap.value, unit=snap.unit, source_updated_at=pull.updated, retrieved_at=now))
        else:
            row.value, row.unit, row.source_updated_at, row.retrieved_at = snap.value, snap.unit, pull.updated, now
    for gone in existing.values():  # a row the source no longer publishes
        await s.delete(gone)
    return v.StateFactsResourceResult(resource=resource.key, status="updated", rows=len(pull.rows))


async def _refresh_datacommons(s: AsyncSession, client: DataCommonsClient, now: datetime) -> v.StateFactsResourceResult:
    """Fetch every Data Commons figure (two requests) and upsert it with its provenance. The source has no update date, so the
    figures are compared and an unchanged pull only moves `retrieved_at`. A variable that came back empty keeps what is stored (a
    changed facet must not wipe a figure); a variable that returned figures loses the rows the source no longer publishes."""
    pull = await client.pull()
    if pull.empty:
        logger.warning("state facts: datacommons returned no figure for %s", ", ".join(pull.empty))
    existing = {(r.resource_id, r.region_code, r.metric, r.period): r for r in (await s.execute(
        select(m.StateFactSnapshot).where(m.StateFactSnapshot.resource_id.startswith(DC_PREFIX)))).scalars()}
    changed = 0
    for snap in pull.rows:
        row = existing.pop((snap.resource_id, snap.region_code, snap.metric, snap.period), None)
        if row is None:
            s.add(m.StateFactSnapshot(resource_id=snap.resource_id, region_code=snap.region_code, metric=snap.metric, period=snap.period,
                                      value=snap.value, unit=snap.unit, source_updated_at=None, retrieved_at=now, provenance=snap.provenance))
            changed += 1
        else:
            changed += (row.value, row.unit, row.provenance) != (snap.value, snap.unit, snap.provenance)
            row.value, row.unit, row.provenance, row.retrieved_at = snap.value, snap.unit, snap.provenance, now
    fresh = {snap.resource_id for snap in pull.rows}
    for gone in existing.values():
        if gone.resource_id in fresh:
            await s.delete(gone)
            changed += 1
    return v.StateFactsResourceResult(resource=DATACOMMONS, status="updated" if changed else "unchanged", rows=len(pull.rows))


async def refresh_state_facts(
    s: AsyncSession, *, only: Iterable[str] | None = None, client: DataGovClient | None = None, now: datetime | None = None,
    dc_client: DataCommonsClient | None = None,
) -> v.StateFactsRefreshSummary:
    """Re-pull every configured resource and upsert its snapshots; a resource whose source `updated_date` is unchanged is
    skipped (one one-record request) and only marked as checked. A failing resource is reported and the others still run. The
    Data Commons source (key `datacommons`) runs only when it has a key or a client is given: without one it is left out, not
    reported as failed. The caller commits."""
    settings = get_settings()
    client = client or DataGovClient(settings.data_gov_in_api_key)
    dc_client = dc_client or (DataCommonsClient(settings.data_commons_api_key) if settings.data_commons_api_key else None)
    now = now or utcnow()
    wanted = set(only) if only is not None else None
    results: list[v.StateFactsResourceResult] = []
    if dc_client is not None and (wanted is None or DATACOMMONS in wanted):
        try:
            results.append(await _refresh_datacommons(s, dc_client, now))
        except CultureSourceError as exc:
            logger.warning("state facts: %s failed (%s)", DATACOMMONS, exc.kind)
            results.append(v.StateFactsResourceResult(resource=DATACOMMONS, status="failed", rows=0, error_kind=exc.kind, error=str(exc)))
    for resource in RESOURCES:
        if wanted is not None and resource.key not in wanted:
            continue
        try:
            results.append(await _refresh_one(s, client, resource, now))
        except CultureSourceError as exc:
            logger.warning("state facts: %s failed (%s)", resource.key, exc.kind)
            results.append(v.StateFactsResourceResult(resource=resource.key, status="failed", rows=0, error_kind=exc.kind, error=str(exc)))
    count = lambda status: sum(1 for r in results if r.status == status)  # noqa: E731
    return v.StateFactsRefreshSummary(resources=results, updated=count("updated"), unchanged=count("unchanged"), failed=count("failed"))


def configured_keys() -> list[str]:
    """The sources that have a key on this server: every data.gov.in resource, and `datacommons`."""
    settings = get_settings()
    return ([r.key for r in RESOURCES] if settings.data_gov_in_api_key else []) + ([DATACOMMONS] if settings.data_commons_api_key else [])


async def refresh_scheduled() -> v.StateFactsRefreshSummary | None:
    """The scheduler's entry point: refresh every source that has a key, in its own transaction. None when none has."""
    keys = configured_keys()
    if not keys:
        return None
    async with _LOCK, session() as s, s.begin():
        return await refresh_state_facts(s, only=keys)


# --- reading ------------------------------------------------------------------------------------------------------------


async def _stored(region_code: str) -> tuple[list[Any], dict[str, datetime]]:
    async with read_session() as s:
        rows = list((await s.execute(select(m.StateFactSnapshot).where(m.StateFactSnapshot.region_code.in_((region_code, NATIONAL))))).scalars())
        checked = {rid: at for rid, at in (await s.execute(
            select(m.StateFactSnapshot.resource_id, func.max(m.StateFactSnapshot.retrieved_at)).group_by(m.StateFactSnapshot.resource_id))).all()}
    return rows, checked


def _stale(checked: dict[str, datetime], now: datetime, *, gov: bool = True, dc: bool = True) -> list[str]:
    """The sources whose stored copy is missing or older than its cadence and that may be pulled now (`gov`, `dc`: the source
    is allowed, normally because it has a key). Data Commons is one source: stale when nothing of it is stored or its oldest
    figure is past the cadence."""
    mono = time.monotonic()
    stale = [r.key for r in RESOURCES
             if gov and (r.resource_id not in checked or now - checked[r.resource_id] > timedelta(days=r.cadence_days))
             and _BACKOFF.get(r.key, 0.0) <= mono]
    stored = [at for rid, at in checked.items() if rid.startswith(DC_PREFIX)]
    if dc and (not stored or now - min(stored) > timedelta(days=DC_CADENCE_DAYS)) and _BACKOFF.get(DATACOMMONS, 0.0) <= mono:
        stale.append(DATACOMMONS)
    return stale


async def _live_rows(region_code: str) -> tuple[list[Any], dict[str, datetime]]:
    settings = get_settings()

    def due(checked: dict[str, datetime]) -> list[str]:
        # A source without a key is pulled only when nothing is stored at all (so the read can say what is missing); otherwise it
        # is left alone and its stored copy (the recording) is served.
        return _stale(checked, utcnow(), gov=bool(settings.data_gov_in_api_key) or not checked,
                      dc=bool(settings.data_commons_api_key) or not checked)

    rows, checked = await _stored(region_code)
    stale = due(checked)
    if stale:
        async with _LOCK:
            rows, checked = await _stored(region_code)  # another request may have pulled while this one waited
            stale = due(checked)
            summary = None
            if stale:
                async with session() as s, s.begin():
                    summary = await refresh_state_facts(s, only=stale)
                for failed in (r for r in summary.resources if r.status == "failed"):
                    _BACKOFF[failed.resource] = time.monotonic() + FAILURE_BACKOFF_SECONDS
                rows, checked = await _stored(region_code)
        if not rows and summary and summary.failed:
            first = next(r for r in summary.resources if r.status == "failed")
            raise _error_for(first.error_kind, first.error)
    return rows, checked


async def can_write(s: AsyncSession, ctx: LensContext) -> bool:
    _, project = await get_owned(s, m.Campaign, ctx.campaign_id, ctx.user_id, "Campaign")
    return project.access_role in WRITE_ROLES and project.status != "archived"


async def get_state_facts(ctx: LensContext, region_code: str) -> v.StateFacts:
    async with read_session() as s:
        names = await region_names(s)
        writable = await can_write(s, ctx)
    if region_code not in names:
        raise NotFound(f"Region was not found: {region_code}.")
    if ctx.mode == "demo":
        rows, fetched = recorded_rows(), recorded_at()
    else:
        rows, checked = await _live_rows(region_code)
        fetched = max(checked.values()) if checked else None
    return v.StateFacts(
        campaign_id=ctx.campaign_id, region_code=region_code, region_name=names[region_code], mode=ctx.mode,  # type: ignore[arg-type]
        groups=facts_from_rows(rows, region_code), fetched_at=fetched, can_refresh=writable and ctx.mode == "live")


async def refresh_for_user(user_id: UUID, campaign_id: UUID, region_code: str) -> v.StateFacts:
    """Owner or editor: check every resource now (an unchanged one costs a single small request). Demo campaigns have nothing
    to pull."""
    ctx = await lens_context(user_id, campaign_id, writable=True)
    if ctx.mode == "live":
        _, checked = await _stored(region_code)
        keys = configured_keys() or None  # nothing configured: try everything, so the error says what is missing
        wanted = set(keys) if keys is not None else {r.key for r in RESOURCES}
        times = [checked[r.resource_id] for r in RESOURCES if r.key in wanted and r.resource_id in checked]
        dc_times = [at for rid, at in checked.items() if rid.startswith(DC_PREFIX)]
        times += [min(dc_times)] if DATACOMMONS in wanted and dc_times else []
        if checked and len(times) == len(wanted) and utcnow() - min(times) < MANUAL_REFRESH_GAP:
            raise RateLimited("State statistics were checked a moment ago; try again in a minute.")
        async with _LOCK, session() as s, s.begin():
            summary = await refresh_state_facts(s, only=keys)
        failed = [r for r in summary.resources if r.status == "failed"]
        if failed and len(failed) == len(summary.resources):
            raise _error_for(failed[0].error_kind, failed[0].error)
    return await get_state_facts(ctx, region_code)
