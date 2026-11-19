"""Market Lens auto-build: every state of a live campaign (its origin and targets) is built in the background.

It starts when a campaign names its states (a saved brief, a created campaign) and whenever Lens is opened while one of those
states has no completed build. Builds go through the existing pipeline (`lens.build_regions`): the same sources, cool-downs,
provenance and computed confidence as a build started by hand.

Bounded and polite. One worker per process builds one state at a time, at most `lens_auto_build_max_regions` states per
campaign, with `lens_auto_build_pause_seconds` between two builds. A state whose latest build stored claims (completed or
partial) is never queued again; a failed state is retried only after `lens_live_build_min_interval_seconds`. When a campaign's
queue is done, Trend Radar is refreshed once for the newly built states it has not read yet (at most
`lens_trend_max_regions_live` per call), so it covers the campaign too.

Progress lives in this process: the API runs one instance. A restart loses only the queue, and the next Lens visit queues the
missing states again. Demo campaigns are never auto-built: their states are seeded with the demo.
"""

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import AppError
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session
from app.schemas import lens as v
from app.services import lens, lens_data
from app.services.common import WRITE_ROLES, get_owned

logger = logging.getLogger(__name__)


@dataclass
class Job:
    region_code: str
    state: str  # queued | building | failed
    user_id: UUID
    campaign_id: UUID
    message: str | None = None
    updated_at: datetime = field(default_factory=utcnow)


class _Worker:
    """The queue and its single task. Rebinds when the event loop changes (tests)."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.pending: deque[tuple[UUID, str, str]] = deque()  # (workspace, mode, region)
        self.jobs: dict[tuple[UUID, str], dict[str, Job]] = {}
        self.built: dict[UUID, list[str]] = {}  # campaign -> states this worker built, for the Trend Radar follow-up
        self.task: asyncio.Task[None] | None = None

    def bind(self) -> "_Worker":
        loop = asyncio.get_running_loop()
        if loop is not self.loop:
            self.loop, self.pending, self.jobs, self.built, self.task = loop, deque(), {}, {}, None
        return self

    def submit(self, ctx: lens.LensContext, code: str) -> None:
        self.jobs.setdefault((ctx.workspace_id, ctx.mode), {})[code] = Job(code, "queued", ctx.user_id, ctx.campaign_id)
        self.pending.append((ctx.workspace_id, ctx.mode, code))
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run(), name="lens-auto-build")

    async def _run(self) -> None:
        settings = get_settings()
        first = True
        while self.pending:
            workspace_id, mode, code = self.pending.popleft()
            job = self.jobs.get((workspace_id, mode), {}).get(code)
            if job is None or job.state != "queued":
                continue
            if not first:
                await asyncio.sleep(settings.lens_auto_build_pause_seconds)  # a polite gap between two builds
            first = False
            job.state, job.updated_at = "building", utcnow()
            try:
                batch = await lens.build_regions(job.user_id, job.campaign_id, v.LensBuildRequest(region_codes=[code], include_trends=True))
                build = batch.builds[0]
                if build.status == "failed":
                    job.state, job.message, job.updated_at = "failed", build.error, utcnow()
                else:
                    self.jobs[(workspace_id, mode)].pop(code, None)  # the stored build is the record now
                    self.built.setdefault(job.campaign_id, []).append(code)
            except AppError as error:  # rate limited, a build already running, the campaign gone: reported, never raised
                job.state, job.message, job.updated_at = "failed", str(error), utcnow()
            except Exception:  # noqa: BLE001 - a bug in one build must not stop the queue; it is logged
                logger.exception("lens auto-build of %s failed", code)
                job.state, job.message, job.updated_at = "failed", "The build stopped on an unexpected error.", utcnow()
            if not any(p[:2] == (workspace_id, mode) for p in self.pending):
                await self._follow_up(job.user_id, job.campaign_id)

    async def _follow_up(self, user_id: UUID, campaign_id: UUID) -> None:
        """Trend Radar reads the festivals the new builds stored, for the states it has not read yet."""
        codes = self.built.pop(campaign_id, [])
        if not codes:
            return
        from app.schemas.lens_t3 import LensTrendRefreshRequest  # noqa: PLC0415 - lens_t3 schemas import this package's schemas
        from app.services import lens_trends  # noqa: PLC0415 - lens_trends imports lens_views, which imports lens_data

        try:
            radar = await lens_trends.get_radar(await lens.lens_context(user_id, campaign_id), codes)
            unread = [r.region_code for r in radar.regions if r.supported and r.refreshed_at is None]
            size = max(1, get_settings().lens_trend_max_regions_live)
            for i in range(0, len(unread), size):
                await lens_trends.refresh_radar(user_id, campaign_id, LensTrendRefreshRequest(region_codes=unread[i:i + size]))
        except AppError as error:
            logger.info("lens auto-build: Trend Radar follow-up skipped (%s)", error)
        except Exception:  # noqa: BLE001
            logger.exception("lens auto-build: Trend Radar follow-up failed")

    async def settle(self, timeout: float = 30.0) -> None:
        """Wait for the queue to finish (tests and shutdown)."""
        if self.task is not None and not self.task.done():
            async with asyncio.timeout(timeout):
                await asyncio.shield(self.task)


worker = _Worker()


# --- what is shown ------------------------------------------------------------------------------------------------


async def _writable(ctx: lens.LensContext) -> bool:
    async with read_session() as s:
        _, project = await get_owned(s, m.Campaign, ctx.campaign_id, ctx.user_id, "Campaign")
        return project.access_role in WRITE_ROLES and project.status != "archived"


async def _status(ctx: lens.LensContext, enabled: bool) -> v.LensAutoBuild:
    work = worker.bind()
    jobs = work.jobs.get((ctx.workspace_id, ctx.mode), {})
    async with read_session() as s:
        roles = await lens_data.campaign_roles(s, ctx.campaign_id)
        latest = await lens.latest_builds(s, ctx.workspace_id, ctx.mode)
        names = await lens.region_names(s)
        with_claims = set((await s.execute(
            select(m.Region.code).join(m.Claim, m.Claim.region_id == m.Region.id).where(
                (m.Claim.workspace_id == ctx.workspace_id) | m.Claim.workspace_id.is_(None), m.Claim.mode == ctx.mode,
                m.Region.code.in_(list(roles))).distinct())).scalars())
    regions = []
    for code, role in roles.items():
        job, row = jobs.get(code), latest.get(code)
        last = lens.build_view(row, names.get(code, code)) if row else None
        if job is not None and job.state in ("queued", "building"):
            state, message, at = job.state, None, job.updated_at
        elif row is not None and row.status != "failed":
            state, message, at = "built", None, row.finished_at
        elif code in with_claims:
            state, message, at = "built", None, None
        elif job is not None or (row is not None and row.status == "failed"):
            state, message, at = "failed", job.message if job else row.error, job.updated_at if job else row.finished_at  # type: ignore[union-attr]
        else:
            state, message, at = "waiting", None, None
        regions.append(v.LensAutoBuildRegion(region_code=code, region_name=names.get(code, code), role=role, state=state,  # type: ignore[arg-type]
                                             message=message, last_build=last, updated_at=at))
    return v.LensAutoBuild(campaign_id=ctx.campaign_id, mode=ctx.mode, enabled=enabled,  # type: ignore[arg-type]
                           running=any(r.state in ("queued", "building") for r in regions), regions=regions)


async def status(user_id: UUID, campaign_id: UUID) -> v.LensAutoBuild:
    ctx = await lens.lens_context(user_id, campaign_id)
    return await _status(ctx, ctx.mode == "live" and await _writable(ctx))


async def ensure(user_id: UUID, campaign_id: UUID) -> v.LensAutoBuild:
    """Queue every campaign state that lacks a completed build (live campaigns, owner or editor). Idempotent: a queued,
    running or built state is left alone, and a failed one waits out the live build interval before it is tried again."""
    ctx = await lens.lens_context(user_id, campaign_id)
    enabled = ctx.mode == "live" and await _writable(ctx)
    if enabled:
        settings = get_settings()
        work = worker.bind()
        jobs = work.jobs.setdefault((ctx.workspace_id, ctx.mode), {})
        async with read_session() as s:
            roles = await lens_data.campaign_roles(s, ctx.campaign_id)
            latest = await lens.latest_builds(s, ctx.workspace_id, ctx.mode)
        now = utcnow()
        for code in list(roles)[: settings.lens_auto_build_max_regions]:
            job, row = jobs.get(code), latest.get(code)
            if job is not None and (job.state in ("queued", "building")
                                    or (now - job.updated_at).total_seconds() < settings.lens_live_build_min_interval_seconds):
                continue
            if row is not None and (row.status != "failed"
                                    or (now - row.finished_at).total_seconds() < settings.lens_live_build_min_interval_seconds):
                continue
            if (ctx.workspace_id, code, ctx.mode) in lens._RUNNING:  # a build started by hand is already running
                continue
            work.submit(ctx, code)
    return await _status(ctx, enabled)


def schedule(user_id: UUID, campaign_id: UUID) -> None:
    """Fire and forget, for the places that name a campaign's states (campaign created, brief saved). Never raises. Off under
    APP_ENV=test so other suites never start builds; the Lens tests call `ensure` directly."""
    if get_settings().app_env == "test":
        return

    async def run() -> None:
        try:
            await ensure(user_id, campaign_id)
        except Exception:  # noqa: BLE001 - a background start must never surface in the request that triggered it
            logger.warning("lens auto-build could not start for campaign %s", campaign_id, exc_info=True)

    try:
        task = asyncio.get_running_loop().create_task(run(), name=f"lens-auto-build-start-{campaign_id}")
    except RuntimeError:  # no running loop (a sync caller): nothing to schedule on
        logger.warning("lens auto-build: no event loop to schedule on")
        return
    _STARTS.add(task)  # keep a reference until it finishes, so it is not garbage collected mid-run
    task.add_done_callback(_STARTS.discard)


_STARTS: set[asyncio.Task[None]] = set()
