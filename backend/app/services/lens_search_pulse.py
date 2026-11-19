"""Search pulse: what people in a state search for, from Google's public Trends dataset in BigQuery.

One BigQuery query a day covers every state (`app.integrations.google_trends`), stored in `lens_search_pulse`. Demo campaigns
read a recorded snapshot of the four demo states and never reach BigQuery. Live reads serve the stored rows; only when no row
is newer than SEARCH_PULSE_MAX_AGE (24 h) do they run a live query, and a failing query is not retried for ten minutes.
`refresh_search_pulse` is the one function that queries; the scheduler endpoint, the owner/editor refresh and that fallback
all call it. Values are the dataset's own; nothing is estimated or filled in.
"""

import asyncio
import json
import logging
import time
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import search_pulse as logic
from app.core.config import Settings, get_settings
from app.core.errors import AppError, NotFound, ProviderFailed, ProviderNotConfigured, RateLimited, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.integrations import google_trends as trends
from app.schemas import lens_t3 as v
from app.schemas.common import ErrorDetail
from app.services.audit import record_audit
from app.services.lens import LensContext, lens_context, region_names
from app.services.lens_trends import can_write

logger = logging.getLogger(__name__)

RECORDED_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "lens_t3" / "search_pulse.json"
MAX_AGE = timedelta(hours=24)
CHECK_AFTER_OK = 3600.0  # seconds before a live read looks for a newer partition again
CHECK_AFTER_FAILED = 600.0
_LOCK = asyncio.Lock()  # one query at a time in this process
_state: dict[str, Any] = {"until": 0.0, "error": None}  # live reads do not query again before `until`; `error` is the last failure


# --- the refresh ------------------------------------------------------------------------------------------------------


def typed(error: trends.TrendsError) -> AppError:
    """The API error for a failure: quota 429, permission 502, not configured 503, anything else 502. `reason` names which."""
    details = [ErrorDetail(field="reason", message=error.reason)]
    if isinstance(error, trends.TrendsQuota):
        return RateLimited(str(error), details=details)
    if isinstance(error, trends.TrendsNotConfigured):
        return ProviderNotConfigured(str(error), details=details)
    return ProviderFailed(str(error), details=details)


async def refresh_search_pulse(s: AsyncSession, *, settings: Settings | None = None, client: Any | None = None) -> v.SearchPulseRefresh:
    """Read the newest India partition of the Trends dataset and replace the stored rows of every state with it.

    Looks for the newest partition with free dry runs first; if it is the one already stored, nothing is queried. Otherwise
    one query (about 0.9 GB, hard-capped by SEARCH_PULSE_MAX_BYTES) reads it. Does not commit: the caller owns the
    transaction. Raises `trends.TrendsError` (quota, permission, not configured or failed); callers map it with `typed`."""
    settings = settings or get_settings()
    async with _LOCK:  # a second caller waits, then finds the partition stored and skips
        stored = await s.scalar(select(func.max(m.LensSearchPulse.refresh_date)))
        try:
            fetched = await asyncio.to_thread(trends.fetch_india, settings, client=client, skip_refresh_date=stored)
        except trends.TrendsError as error:
            _state.update(until=time.monotonic() + CHECK_AFTER_FAILED, error=error)
            raise
        _state.update(until=time.monotonic() + CHECK_AFTER_OK, error=None)
        if fetched is None:
            return v.SearchPulseRefresh(refresh_date=stored, skipped=True, states=0, rows=0, job_id=None, bytes_processed=None)
        rows = logic.shape(fetched.rows, weeks=settings.search_pulse_weeks, code_for=trends.omnicult_region)
        states = sorted({r["region_code"] for r in rows})
        stamp = utcnow()
        await s.execute(delete(m.LensSearchPulse).where(m.LensSearchPulse.region_code.in_(states)))  # replace, never mix partitions
        if rows:
            await s.execute(insert(m.LensSearchPulse), [
                {**r, "refresh_date": fetched.refresh_date, "retrieved_at": stamp, "job_id": fetched.job_id,
                 "bytes_processed": fetched.bytes_processed} for r in rows])
        await record_audit(s, action="lens.search_pulse_refresh", target_type="lens_search_pulse", detail={
            "refresh_date": fetched.refresh_date.isoformat(), "states": len(states), "rows": len(rows),
            "job_id": fetched.job_id, "bytes_processed": fetched.bytes_processed, "bytes_billed": fetched.bytes_billed})
        return v.SearchPulseRefresh(
            refresh_date=fetched.refresh_date, skipped=False, states=len(states), rows=len(rows), job_id=fetched.job_id,
            bytes_processed=fetched.bytes_processed)


async def refresh_scheduled() -> v.SearchPulseRefresh:
    """What the scheduler endpoint runs: its own transaction, failures as typed API errors (so the scheduler retries)."""
    try:
        async with session() as s, s.begin():
            return await refresh_search_pulse(s)
    except trends.TrendsError as error:
        raise typed(error) from error


# --- reading ----------------------------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def recorded() -> dict[str, Any]:
    return json.loads(RECORDED_FILE.read_text(encoding="utf-8"))


def _recorded_rows(code: str) -> list[dict[str, Any]]:
    data = recorded()
    columns = data["columns"]
    return [{**dict(zip(columns, r, strict=True)), "week": date.fromisoformat(r[columns.index("week")])}
            for r in data["rows"] if r[columns.index("region_code")] == code]


async def _stored_rows(code: str) -> list[m.LensSearchPulse]:
    async with read_session() as s:
        return list((await s.execute(select(m.LensSearchPulse).where(m.LensSearchPulse.region_code == code))).scalars())


def _stale(rows: list[m.LensSearchPulse]) -> bool:
    return not rows or utcnow() - max(r.retrieved_at for r in rows) > MAX_AGE


async def _live_rows(code: str) -> list[m.LensSearchPulse]:
    """The stored rows; a live query only when none is newer than 24 h, and not again soon after one failed or found
    nothing newer. A stale snapshot is served rather than an error."""
    rows = await _stored_rows(code)
    if not _stale(rows):
        return rows
    if time.monotonic() < _state["until"]:
        if rows or _state["error"] is None:
            return rows
        raise typed(_state["error"])
    try:
        async with session() as s, s.begin():
            await refresh_search_pulse(s)
    except trends.TrendsError as error:
        logger.warning("search pulse live query failed: %s", error)
        if not rows:
            raise typed(error) from error
        return rows
    return await _stored_rows(code)


def _terms(items: list[dict[str, Any]]) -> list[v.SearchPulseTerm]:
    return [v.SearchPulseTerm.model_validate(i) for i in items]


async def get_pulse(ctx: LensContext, code: str) -> v.LensSearchPulse:
    async with read_session() as s:
        names = await region_names(s)
        writable = await can_write(s, ctx)
    if code not in names:
        raise NotFound(f"Region was not found: {code}.")
    supported = trends.dataset_region(code) is not None
    stamp: datetime | None = None
    refresh_date: date | None = None
    gaps: list[str] = []
    if not supported:
        rows: list[Any] = []
        gaps.append(f"Google's search data has no region for {names[code]}.")
    elif ctx.mode == "demo":
        rows = _recorded_rows(code)
        refresh_date = date.fromisoformat(recorded()["refresh_date"])
        stamp = datetime.combine(date.fromisoformat(recorded()["recorded_on"]), datetime.min.time(), tzinfo=UTC)
        if not rows:
            gaps.append(f"No search data is recorded for {names[code]}.")
    else:
        stored = await _live_rows(code)
        rows = [{k: getattr(r, k) for k in logic.KEYS} for r in stored]
        if stored:
            refresh_date, stamp = stored[0].refresh_date, max(r.retrieved_at for r in stored)
        else:
            gaps.append(f"No search data is stored for {names[code]} yet.")
    shown = logic.view(rows)
    return v.LensSearchPulse(
        campaign_id=ctx.campaign_id, mode=ctx.mode, region_code=code, region_name=names[code], supported=supported,  # type: ignore[arg-type]
        week=shown["week"], weeks=shown["weeks"], refresh_date=refresh_date, retrieved_at=stamp,
        top=_terms(shown["top"]), rising=_terms(shown["rising"]), gaps=gaps,
        can_refresh=writable and supported and ctx.mode == "live")


async def refresh_pulse(user_id: UUID, campaign_id: UUID, code: str) -> v.LensSearchPulse:
    """Owner or editor: read the newest partition now (nothing is queried when it is already stored). Demo campaigns read the
    recording and make no call."""
    ctx = await lens_context(user_id, campaign_id, writable=True)
    async with read_session() as s:
        if code not in await region_names(s):
            raise NotFound(f"Region was not found: {code}.")
    if ctx.mode == "live" and trends.dataset_region(code) is None:
        raise ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(field="code", message=f"Google's search data has no region for {code}.")])
    if ctx.mode == "live":
        try:
            async with session() as s, s.begin():
                await refresh_search_pulse(s)
        except trends.TrendsError as error:
            raise typed(error) from error
    return await get_pulse(ctx, code)
