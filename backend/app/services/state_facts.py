"""State facts: official state-wise statistics (data.gov.in) shown beside a state's profile in Market Lens.

Why not Lens claims: claims are cultural evidence that feeds the Evidence Meter, confidence and conflicts; these are plain
published statistics with a year, compared with the all-India figure, so they are their own typed panel and the meter is
untouched. They are public and the same for every workspace, so they are stored once (`state_fact_snapshots`).

Reads never wait for a schedule: the read path serves the latest snapshot and pulls a resource itself only when none exists or
the stored copy is older than that resource's cadence (the scheduler normally keeps them fresh). A resource whose own
`updated_date` has not changed is not downloaded again. Demo campaigns read the recorded fixture and never touch the network
or the table.
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
from app.integrations.culture.base import CultureSourceError
from app.schemas import state_facts as v
from app.services.lens import LensContext, lens_context, region_names
from app.services.common import WRITE_ROLES, get_owned

logger = logging.getLogger(__name__)

# Every state, as the API sent it: demo campaigns read it, and the seed job loads it into the deployed database.
ALL_STATES_FILE = RECORDED_FILE = Path(__file__).resolve().parent.parent / "fixtures" / "state_facts" / "all_states.json"
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
    ("connectivity", "Phones and internet"), ("economy", "Income and spending"), ("homes", "Homes"), ("people", "People and learning"),
    ("visitors", "Visitors"))
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


def recorded_rows() -> list[Snapshot]:
    """The recorded API records, parsed by the same code a live pull uses."""
    rows: list[Snapshot] = []
    for key, saved in recorded()["resources"].items():
        rows.extend(parse_records(BY_KEY[key], saved["records"])[0])
    return rows


def recorded_at() -> datetime:
    return datetime.combine(date.fromisoformat(recorded()["recorded_on"]), datetime.min.time(), tzinfo=UTC)


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


async def load_recording(s: AsyncSession, path: Path = ALL_STATES_FILE) -> v.StateFactsRefreshSummary:
    """Store the all-states recording as snapshots (retrieved at its recording date). Idempotent: a resource whose recorded
    `updated_date` is already stored is skipped. The caller commits."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    when = datetime.combine(date.fromisoformat(payload["recorded_on"]), datetime.min.time(), tzinfo=UTC)
    return await refresh_state_facts(s, client=RecordedClient(payload["resources"]), now=when)  # type: ignore[arg-type]


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


async def refresh_state_facts(
    s: AsyncSession, *, only: Iterable[str] | None = None, client: DataGovClient | None = None, now: datetime | None = None,
) -> v.StateFactsRefreshSummary:
    """Re-pull every configured resource and upsert its snapshots; a resource whose source `updated_date` is unchanged is
    skipped (one one-record request) and only marked as checked. A failing resource is reported and the others still run. The
    caller commits."""
    client = client or DataGovClient(get_settings().data_gov_in_api_key)
    now = now or utcnow()
    wanted = set(only) if only is not None else None
    results: list[v.StateFactsResourceResult] = []
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


async def refresh_scheduled() -> v.StateFactsRefreshSummary:
    """The scheduler's entry point: refresh everything in its own transaction."""
    async with _LOCK, session() as s, s.begin():
        return await refresh_state_facts(s)


# --- reading ------------------------------------------------------------------------------------------------------------


async def _stored(region_code: str) -> tuple[list[Any], dict[str, datetime]]:
    async with read_session() as s:
        rows = list((await s.execute(select(m.StateFactSnapshot).where(m.StateFactSnapshot.region_code.in_((region_code, NATIONAL))))).scalars())
        checked = {rid: at for rid, at in (await s.execute(
            select(m.StateFactSnapshot.resource_id, func.max(m.StateFactSnapshot.retrieved_at)).group_by(m.StateFactSnapshot.resource_id))).all()}
    return rows, checked


def _stale(checked: dict[str, datetime], now: datetime) -> list[str]:
    mono = time.monotonic()
    return [r.key for r in RESOURCES
            if (r.resource_id not in checked or now - checked[r.resource_id] > timedelta(days=r.cadence_days))
            and _BACKOFF.get(r.key, 0.0) <= mono]


async def _live_rows(region_code: str) -> tuple[list[Any], dict[str, datetime]]:
    rows, checked = await _stored(region_code)
    stale = _stale(checked, utcnow())
    if stale and (get_settings().data_gov_in_api_key or not checked):
        async with _LOCK:
            rows, checked = await _stored(region_code)  # another request may have pulled while this one waited
            stale = _stale(checked, utcnow())
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
        if checked and len(checked) == len(RESOURCES) and utcnow() - min(checked.values()) < MANUAL_REFRESH_GAP:
            raise RateLimited("State statistics were checked a moment ago; try again in a minute.")
        async with _LOCK, session() as s, s.begin():
            summary = await refresh_state_facts(s)
        failed = [r for r in summary.resources if r.status == "failed"]
        if failed and len(failed) == len(summary.resources):
            raise _error_for(failed[0].error_kind, failed[0].error)
    return await get_state_facts(ctx, region_code)
