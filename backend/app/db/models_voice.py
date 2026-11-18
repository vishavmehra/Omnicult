"""Voice Director table (migration 0024): the plans a typed or spoken instruction produced.

A plan is stored exactly as the server validated it, step by step. Confirming steps can only apply what is stored here, and
each step keeps its outcome, so the instruction, the model that read it, what code refused and what was applied can all be
read back later. The version tree and the operations table hold the changes themselves.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class VoicePlan(Base):
    __tablename__ = "voice_plans"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID]
    version_id: Mapped[UUID]  # the version the plan starts from
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_runs.id"))  # the voice_direct run that recorded the planning call
    mode: Mapped[str]  # live | demo
    source: Mapped[str]  # typed | voice
    instruction: Mapped[str]
    transcript: Mapped[str | None]  # voice only: what the model heard, before the person corrected it
    supported: Mapped[bool]
    summary: Mapped[str | None]
    refusal: Mapped[str | None]
    steps: Mapped[list]  # DirectStep dicts, with each step's status and result
    notes: Mapped[list]
    provider: Mapped[str | None]
    model_id: Mapped[str | None]
    prompt_version: Mapped[str | None]
    estimated_cost_usd: Mapped[float | None]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"]),
        ForeignKeyConstraint(["version_id", "campaign_id"], ["version_nodes.id", "version_nodes.campaign_id"]),
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        CheckConstraint("source IN ('typed', 'voice')", name="source"),
        Index("ix_voice_plans_campaign_id_created_at", "campaign_id", "created_at"),
    )
