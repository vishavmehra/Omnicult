"""AI usage metering: one row per model or capability call, and the spend queries a budget guard needs.

The model gateway records every call here (provider, model, prompt version, tokens, estimated cost, latency, status).
Costs are estimates from the registry price table, never provider invoices; label them as estimates wherever shown.
"""

import logging
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.llm.budget import UsageEvent

log = logging.getLogger(__name__)


class AiUsage(BaseModel):
    capability: str  # chat, embeddings, vision, transcribe, image_generation, tts, grounded_research, ...
    provider: str
    model: str
    prompt_version: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    thinking_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    status: str = "ok"  # ok, error, blocked, ...
    error_code: str | None = None
    workspace_id: UUID | None = None
    project_id: UUID | None = None
    campaign_id: UUID | None = None
    run_id: UUID | None = None
    user_id: UUID | None = None


async def record_ai_usage(usage: AiUsage, *, s: AsyncSession | None = None) -> UUID:
    """Store one usage event. Pass the caller's session to join its transaction; otherwise it commits on its own."""
    row = m.AiUsageEvent(id=uuid4(), created_at=utcnow(), **usage.model_dump())
    if s is not None:
        s.add(row)
        await s.flush()
    else:
        async with session() as own, own.begin():
            own.add(row)
    return row.id


async def spend_usd(
    *, run_id: UUID | None = None, workspace_id: UUID | None = None, user_id: UUID | None = None,
    since: datetime | None = None,
) -> float:
    """Estimated spend over the matching events (all of them when no filter is given)."""
    stmt = select(func.coalesce(func.sum(m.AiUsageEvent.estimated_cost_usd), 0.0))
    if run_id is not None:
        stmt = stmt.where(m.AiUsageEvent.run_id == run_id)
    if workspace_id is not None:
        stmt = stmt.where(m.AiUsageEvent.workspace_id == workspace_id)
    if user_id is not None:
        stmt = stmt.where(m.AiUsageEvent.user_id == user_id)
    if since is not None:
        stmt = stmt.where(m.AiUsageEvent.created_at >= since)
    async with read_session() as s:
        return float(await s.scalar(stmt) or 0.0)


def _uuid(value: str | None) -> UUID | None:
    try:
        return UUID(value) if value else None
    except ValueError:  # a run scope named by a test or a script, not by an agent_runs row
        return None


class DbUsageSink:
    """The running app's default usage sink (installed at startup, `app.main.lifespan`): every gateway request, failed
    attempts included, becomes one `ai_usage_events` row, and the budget guard reads its spend back from the same table.

    The table has no grounded-request, image or audio column, so those counts are not stored; the cost already includes
    them (a `grounded_research` row bills the search fee). Metering never fails the call it measures: a database error
    is logged, and a spend query that fails reads as 0 (the budget check then does not stop the call)."""

    async def record(self, event: UsageEvent) -> None:
        await record_ai_usage(AiUsage(
            capability=event.capability, provider=event.provider, model=event.model, prompt_version=event.prompt_version,
            input_tokens=event.input_tokens or 0, output_tokens=event.output_tokens or 0,
            thinking_tokens=event.thinking_tokens or 0, estimated_cost_usd=event.estimated_cost_usd or 0.0,
            latency_ms=event.latency_ms, status=event.status, error_code=event.error_code, workspace_id=event.workspace_id,
            project_id=event.project_id, campaign_id=event.campaign_id, user_id=event.user_id, run_id=_uuid(event.run_id),
        ))

    async def spent_usd(self, *, run_id: str | None = None, day: date | None = None) -> float:
        try:
            if run_id is not None:
                known = _uuid(run_id)
                return await spend_usd(run_id=known) if known else 0.0
            start = datetime.combine(day or datetime.now(UTC).date(), datetime.min.time(), tzinfo=UTC)
            stmt = select(func.coalesce(func.sum(m.AiUsageEvent.estimated_cost_usd), 0.0)).where(
                m.AiUsageEvent.created_at >= start, m.AiUsageEvent.created_at < start + timedelta(days=1)
            )
            async with read_session() as s:
                return float(await s.scalar(stmt) or 0.0)
        except Exception:
            log.warning("usage spend query failed", exc_info=True)
            return 0.0
