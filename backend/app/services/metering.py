"""AI usage metering: one row per model or capability call, and the spend queries a budget guard needs.

The model gateway records every call here (provider, model, prompt version, tokens, estimated cost, latency, status).
Costs are estimates from the registry price table, never provider invoices; label them as estimates wherever shown.
"""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session


class AiUsage(BaseModel):
    capability: str  # text, embeddings, vision, image_generation, tts, grounded_research, ...
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
