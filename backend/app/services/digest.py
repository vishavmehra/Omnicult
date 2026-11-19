"""Weekly Digest (feature 48): generate, store, list, summarise and export one digest per campaign and ISO week.

Access follows the campaign (another workspace's campaign is a 404; generating needs an owner or editor). A digest is built
by code from stored records (`digest_build`) and stored once per (campaign, ISO week): asking again returns the stored one,
`regenerate` replaces it and bumps `revision`. The optional model summary is a separate, explicit action, live projects only.

`generate_weekly` is what Cloud Scheduler calls (POST /internal/digest/generate-weekly, Google OIDC): one digest per active
campaign for the last completed ISO week, idempotent per week, numbers only (no model is called without a person asking).
Nothing is ever sent outbound.
"""

import hashlib
import json
import logging
from datetime import date, datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agents import digest_summary as agent
from app.core.errors import Conflict, ProviderFailed, ValidationFailed
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.llm.gateway import LLMError
from app.schemas import digest as v
from app.schemas.common import ErrorDetail
from app.services import studio_context as ctx
from app.services.ai_guard import guarded_ai_call
from app.services.audit import record_audit
from app.services.common import get_owned, not_found, require_writable
from app.services.digest_build import (
    build_content,
    current_week,
    facts_of,
    last_completed_week,
    subject_of,
    week_of,
)
from app.services.digest_render import Exported, export_digest

log = logging.getLogger("omnicult.digest")
Outcome = Literal["created", "existing", "empty"]
DEMO_NARRATIVE = "The written summary is available in live projects only."
MAX_CAMPAIGNS_PER_CALL = 1000  # ponytail: one request walks every active campaign; page it or fan out per campaign past this


def to_digest(row: m.PulseDigest) -> v.Digest:
    return v.Digest(
        id=row.id, campaign_id=row.campaign_id, revision=row.revision, mode=row.mode, trigger=row.trigger,  # type: ignore[arg-type]
        content=v.DigestContent.model_validate(row.content), content_sha256=row.content_sha256,
        narrative=v.DigestNarrative.model_validate(row.narrative) if row.narrative else None, generated_at=row.generated_at)


def _summary(row: m.PulseDigest) -> v.DigestSummary:
    c = v.DigestContent.model_validate(row.content)
    ch = c.what_changed.counts
    return v.DigestSummary(
        id=row.id, week=c.week, revision=row.revision, trigger=row.trigger, generated_at=row.generated_at,  # type: ignore[arg-type]
        has_narrative=bool(row.narrative),
        counts=v.DigestCounts(
            changes=ch.creative_versions + ch.content_versions + ch.verdicts + ch.approvals + ch.agent_runs + ch.audience_runs
            + ch.conflicts_opened + ch.conflicts_resolved + ch.risk_findings,
            alerts=len(c.pulse.alerts),
            open_items=c.open_items.conflicts_total + c.open_items.risk_findings_total + len(c.open_items.not_ready),
            actions=len(c.next_actions)))


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def is_empty(c: v.DigestContent) -> bool:
    """Nothing to report: no Pulse data, no comments, nothing recorded this week and nothing open."""
    ch = c.what_changed.counts
    recorded = sum(ch.model_dump().values())
    oi = c.open_items
    return not (c.pulse.available or c.comments.available or recorded or oi.conflicts_total or oi.risk_findings_total or oi.not_ready)


def _week_for(day: date | None, now: datetime) -> v.DigestWeek:
    week = week_of(day) if day is not None else current_week(now)
    if week.start > current_week(now).start:
        raise ValidationFailed("The supplied request is invalid.", details=[ErrorDetail(
            field="week_of", message="That week has not started yet. Pick the week in progress or an earlier one.")])
    return week


async def _store(
    project: m.Project, campaign: m.Campaign, week: v.DigestWeek, *, now: datetime, user_id: UUID | None, trigger: str,
    regenerate: bool, skip_empty: bool,
) -> tuple[m.PulseDigest | None, Outcome]:
    for attempt in range(2):
        try:
            async with session() as s, s.begin():
                found = await s.execute(select(m.PulseDigest).where(
                    m.PulseDigest.campaign_id == campaign.id, m.PulseDigest.iso_year == week.iso_year, m.PulseDigest.iso_week == week.iso_week))
                row = found.scalar_one_or_none()
                if row is not None and not regenerate:
                    return row, "existing"
                content = await build_content(s, await subject_of(s, project, campaign), week, now)
                if skip_empty and is_empty(content):
                    return None, "empty"
                payload = content.model_dump(mode="json")
                if row is None:
                    row = m.PulseDigest(
                        id=uuid4(), workspace_id=project.workspace_id, project_id=project.id, campaign_id=campaign.id,
                        iso_year=week.iso_year, iso_week=week.iso_week, week_start=week.start, week_end=week.end, revision=1)
                    s.add(row)
                else:
                    row.revision += 1
                row.mode, row.trigger, row.generated_by, row.generated_at = project.mode, trigger, user_id, now
                row.content, row.content_sha256, row.narrative = payload, _hash(payload), None  # a regenerated week drops its old summary
                await record_audit(
                    s, action="pulse.digest.generate", target_type="campaign", target_id=str(campaign.id),
                    workspace_id=project.workspace_id, actor_user_id=user_id,
                    detail={"week": week.label, "revision": row.revision, "trigger": trigger})
            return row, "created"
        except IntegrityError:  # a concurrent request stored the same week first: return theirs on the retry
            if attempt:
                raise
    raise AssertionError("unreachable")


async def _campaign_for(user_id: UUID, campaign_id: UUID, *, writable: bool) -> tuple[m.Campaign, m.Project]:
    async with read_session() as s:
        campaign, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        if writable:
            require_writable(project)
    return campaign, project


async def create_digest(user_id: UUID, campaign_id: UUID, body: v.DigestCreate, *, now: datetime | None = None) -> v.DigestCreated:
    now = now or utcnow()
    campaign, project = await _campaign_for(user_id, campaign_id, writable=True)
    week = _week_for(body.week_of, now)
    row, outcome = await _store(
        project, campaign, week, now=now, user_id=user_id, trigger="manual", regenerate=body.regenerate, skip_empty=False)
    assert row is not None
    return v.DigestCreated(created=outcome == "created", digest=to_digest(row))


async def list_digests(user_id: UUID, campaign_id: UUID, *, now: datetime | None = None) -> v.DigestList:
    async with read_session() as s:
        _, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        rows = list((await s.execute(
            select(m.PulseDigest).where(m.PulseDigest.campaign_id == campaign_id)
            .order_by(m.PulseDigest.week_start.desc(), m.PulseDigest.id))).scalars())
    return v.DigestList(
        items=[_summary(r) for r in rows], current_week=current_week(now or utcnow()), narrative_available=project.mode == "live")


async def _row(user_id: UUID, campaign_id: UUID, digest_id: UUID) -> m.PulseDigest:
    async with read_session() as s:
        await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        row = await s.get(m.PulseDigest, digest_id)
    if row is None or row.campaign_id != campaign_id:
        raise not_found("Digest")
    return row


async def get_digest(user_id: UUID, campaign_id: UUID, digest_id: UUID) -> v.Digest:
    return to_digest(await _row(user_id, campaign_id, digest_id))


async def export(user_id: UUID, campaign_id: UUID, digest_id: UUID, fmt: str) -> Exported:
    return export_digest(to_digest(await _row(user_id, campaign_id, digest_id)), fmt)


async def add_narrative(user_id: UUID, campaign_id: UUID, digest_id: UUID, *, now: datetime | None = None) -> v.Digest:
    """A short model-written summary of the stored digest (live projects only), checked by code before it is kept."""
    campaign, project = await _campaign_for(user_id, campaign_id, writable=True)
    row = await _row(user_id, campaign_id, digest_id)
    if project.mode == "demo":
        raise Conflict(DEMO_NARRATIVE)
    content = v.DigestContent.model_validate(row.content)
    facts = facts_of(content)
    try:
        async with guarded_ai_call(user_id, project, campaign.id):  # 429 over the per-user or per-workspace limit
            result = await agent.summarise(ctx.gateway_for(project.mode), stage="writing_summary", week_label=content.week.label, facts=facts)
    except LLMError as exc:
        raise ctx.llm_failure(exc) from exc
    stray = agent.stray_numbers(result.value.summary, facts)
    if stray:
        raise ProviderFailed(
            f"The model's summary used numbers the digest does not hold ({', '.join(stray[:5])}), so it was discarded. "
            "Nothing was stored; try again.")
    trace = result.trace
    narrative = v.DigestNarrative(
        text=result.value.summary.strip(), provider=trace.provider or "unknown", model_id=trace.model_id,
        prompt_version=trace.prompt_version or agent.PROMPT_VERSION,
        estimated_cost_usd=trace.usage.estimated_cost_usd if trace.usage else None, created_at=now or utcnow())
    async with session() as s, s.begin():
        _, project = await get_owned(s, m.Campaign, campaign_id, user_id, "Campaign")
        require_writable(project)
        stored = await s.get(m.PulseDigest, digest_id)
        if stored is None or stored.campaign_id != campaign_id:
            raise not_found("Digest")
        if stored.content_sha256 != row.content_sha256:  # regenerated while the model was writing: its facts are out of date
            raise Conflict("The digest changed while the summary was being written. Open it again and request the summary again.")
        stored.narrative = narrative.model_dump(mode="json")
        await record_audit(
            s, action="pulse.digest.narrative", target_type="campaign", target_id=str(campaign_id),
            workspace_id=project.workspace_id, actor_user_id=user_id,
            detail={"digest_id": str(digest_id), "provider": narrative.provider, "model_id": narrative.model_id})
    return to_digest(stored)


# --- Cloud Scheduler ----------------------------------------------------------------------------------------------


async def generate_weekly(*, now: datetime | None = None, week_day: date | None = None) -> v.SchedulerRun:
    """One digest per active campaign for the last completed ISO week (or the week of `week_day`). Idempotent per week:
    a campaign that already has a digest for it is left alone, one with nothing to report is skipped, and a campaign
    that fails does not stop the others (the call is safe to repeat)."""
    now = now or utcnow()
    week = _week_for(week_day, now) if week_day is not None else last_completed_week(now)
    async with read_session() as s:
        pairs = (await s.execute(
            select(m.Campaign, m.Project).join(m.Project, m.Project.id == m.Campaign.project_id)
            .where(m.Project.status == "active").order_by(m.Campaign.created_at, m.Campaign.id).limit(MAX_CAMPAIGNS_PER_CALL))).all()
    counts = {"created": 0, "existing": 0, "empty": 0}
    failures: list[v.SchedulerFailure] = []
    for campaign, project in pairs:
        try:
            _, outcome = await _store(
                project, campaign, week, now=now, user_id=None, trigger="scheduler", regenerate=False, skip_empty=True)
            counts[outcome] += 1
        except Exception as exc:  # one campaign's failure must not stop the rest
            log.exception("weekly digest failed", extra={"campaign_id": str(campaign.id)})
            failures.append(v.SchedulerFailure(campaign_id=campaign.id, error=type(exc).__name__))
    return v.SchedulerRun(
        week=week, campaigns=len(pairs), generated=counts["created"], already_existed=counts["existing"],
        skipped_no_data=counts["empty"], failed=len(failures), failures=failures)
