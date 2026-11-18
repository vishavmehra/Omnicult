"""Creative Studio, Tier 3 tables (migration 0026): Claim Guard checks and reviews, and the outputs Format Fit applied.

Script Check stores nothing: it is deterministic code over a version, recomputed on every read. A Claim Guard check is a
stored record of one run (the findings as graded then, with the model and rule versions) so a review and a report can
point at what was seen; the person's review decisions are kept apart, keyed by version and finding, so a later check of
the same version keeps them. A Format Fit output points at the asset it made and at the plan that made it.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

REVIEW_DECISIONS = "'substantiated', 'revise', 'accepted', 'not_a_claim'"


def _fk(columns: list[str], table: str, remote: list[str]) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(columns, [f"{table}.{column}" for column in remote])


class ClaimGuardCheck(Base):
    """One Claim Guard run over one version. `result` holds the findings, the policy that was read and the limitations."""

    __tablename__ = "claim_guard_checks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID]
    version_id: Mapped[UUID]
    region_code: Mapped[str | None]
    language: Mapped[str | None]
    mode: Mapped[str]  # 'rules' or 'rules_model'
    rules_version: Mapped[str]
    result: Mapped[dict]
    model: Mapped[dict | None]  # provider, model_id, prompt_version, cost and what code dropped, when the model pass ran
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        _fk(["version_id", "campaign_id"], "version_nodes", ["id", "campaign_id"]),
        CheckConstraint("mode IN ('rules', 'rules_model')", name="mode"),
        Index("ix_claim_guard_checks_version_id_created_at", "version_id", "created_at"),
    )


class ClaimGuardReview(Base):
    """A person's decision about one finding of one version. Human review is the gate; nothing here is automatic."""

    __tablename__ = "claim_guard_reviews"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID]
    version_id: Mapped[UUID]
    finding_key: Mapped[str]
    decision: Mapped[str]
    note: Mapped[str | None]
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        _fk(["version_id", "campaign_id"], "version_nodes", ["id", "campaign_id"]),
        UniqueConstraint("version_id", "finding_key"),
        CheckConstraint(f"decision IN ({REVIEW_DECISIONS})", name="decision"),
    )


class FormatFitOutput(Base):
    """A picture Format Fit made on request: the new asset, the source it came from, and the plan as it was when applied."""

    __tablename__ = "format_fit_outputs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID]
    version_id: Mapped[UUID]
    creative_id: Mapped[UUID]
    source_asset_id: Mapped[UUID]
    output_asset_id: Mapped[UUID]
    format_id: Mapped[str]
    strategy: Mapped[str]
    plan: Mapped[dict]  # the layout, the verdict, the issues and the tool version
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        _fk(["version_id", "campaign_id"], "version_nodes", ["id", "campaign_id"]),
        _fk(["creative_id", "project_id"], "creative_assets", ["id", "project_id"]),
        _fk(["source_asset_id", "project_id"], "assets", ["id", "project_id"]),
        _fk(["output_asset_id", "project_id"], "assets", ["id", "project_id"]),
        CheckConstraint("strategy IN ('crop', 'pad', 'native')", name="strategy"),
        Index("ix_format_fit_outputs_campaign_id_created_at", "campaign_id", "created_at"),
    )
