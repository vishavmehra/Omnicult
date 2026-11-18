"""Launch Room tables (migration 0016): readiness verdicts and human approvals. Both are append-only.

`version_id` is a Creative Studio version node of the same campaign: the composite key (version_id, campaign_id) ->
version_nodes (migration 0021, ON DELETE RESTRICT) makes any other id, or a version of another campaign, impossible.
Everything else is scoped through `(campaign_id, project_id)`, which makes a cross-project reference impossible at the
database level.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

VERDICTS = "'go', 'fix', 'rethink'"
APPROVAL_DECISIONS = "'approve', 'reject', 'request_changes'"


class ReadinessVerdict(Base):
    """A computed readiness verdict for one creative version in one region. Never updated; recomputing adds a row
    unless the inputs and rule version are identical to the newest verdict (then that row is returned)."""

    __tablename__ = "readiness_verdicts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    region_id: Mapped[UUID] = mapped_column(ForeignKey("regions.id"))
    version_id: Mapped[UUID]
    verdict: Mapped[str]
    main_reason: Mapped[str]
    rule_version: Mapped[str]
    scoring_version: Mapped[str]
    overall_score: Mapped[float | None]
    input_fingerprint: Mapped[str]
    inputs: Mapped[dict]  # the VersionObservations the rules read
    result: Mapped[dict]  # the ReadinessAssessment the rules produced
    mode: Mapped[str]
    computed_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    computed_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"]),
        ForeignKeyConstraint(["version_id", "campaign_id"], ["version_nodes.id", "version_nodes.campaign_id"], ondelete="RESTRICT"),
        CheckConstraint(f"verdict IN ({VERDICTS})", name="verdict"),
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        Index("ix_readiness_verdicts_campaign_region_version_at", "campaign_id", "region_id", "version_id", "computed_at"),
    )


class Approval(Base):
    """A person's decision on a version for a region. Only a signed-in user can create one; a verdict never does."""

    __tablename__ = "approvals"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    region_id: Mapped[UUID] = mapped_column(ForeignKey("regions.id"))
    version_id: Mapped[UUID]
    decision: Mapped[str]
    reason: Mapped[str]
    readiness_verdict_id: Mapped[UUID | None] = mapped_column(ForeignKey("readiness_verdicts.id"))
    verdict_at_decision: Mapped[str | None]
    overrides_recommendation: Mapped[bool]
    mode: Mapped[str]
    decided_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"]),
        ForeignKeyConstraint(["version_id", "campaign_id"], ["version_nodes.id", "version_nodes.campaign_id"], ondelete="RESTRICT"),
        CheckConstraint(f"decision IN ({APPROVAL_DECISIONS})", name="decision"),
        CheckConstraint(f"verdict_at_decision IS NULL OR verdict_at_decision IN ({VERDICTS})", name="verdict_at_decision"),
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        Index("ix_approvals_campaign_region_version_at", "campaign_id", "region_id", "version_id", "decided_at"),
    )
