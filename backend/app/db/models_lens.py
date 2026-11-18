"""Market Lens tables (migration 0020): profile builds and the culture call log.

A `LensBuild` is one saved, versioned run of the culture layer for a region in one workspace and mode: how many claims it
stored, which sources answered, what was missing. The claims themselves live in `claims` (a re-retrieved statement keeps
its identity and gains sources), so a build is a record of what was gathered when, not a copy of the claims.
`CultureCall` is the log Data Health reads: one row per source call, with its status and error type. Calls made by the
demo fixture source are stored with mode `demo` and never counted as live attempts.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

BUILD_STATUSES = ("completed", "partial", "failed")


class LensBuild(Base):
    __tablename__ = "lens_builds"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("campaigns.id"))
    region_code: Mapped[str]
    mode: Mapped[str]  # live | demo
    version: Mapped[int]  # 1, 2, ... per workspace, region and mode
    status: Mapped[str]
    years: Mapped[list]
    options: Mapped[dict]  # include_trends, include_grounding
    claim_count: Mapped[int] = mapped_column(default=0)
    created_claims: Mapped[int] = mapped_column(default=0)
    updated_claims: Mapped[int] = mapped_column(default=0)
    conflicts_opened: Mapped[int] = mapped_column(default=0)
    rejected_claims: Mapped[int] = mapped_column(default=0)
    categories: Mapped[dict]  # category -> claim count of this build
    gaps: Mapped[list]
    sources_skipped: Mapped[list]
    error: Mapped[str | None]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("workspace_id", "region_code", "mode", "version"),
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        CheckConstraint("status IN ('completed', 'partial', 'failed')", name="status"),
        Index("ix_lens_builds_workspace_id_region_code_mode", "workspace_id", "region_code", "mode"),
    )


class CultureCall(Base):
    __tablename__ = "culture_calls"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    build_id: Mapped[UUID | None] = mapped_column(ForeignKey("lens_builds.id"))
    mode: Mapped[str]
    source: Mapped[str]  # the adapter name, e.g. wikidata
    operation: Mapped[str]
    request_hash: Mapped[str]
    status: Mapped[str]  # ok | empty | error
    cached: Mapped[bool] = mapped_column(default=False)
    result_count: Mapped[int] = mapped_column(default=0)
    duration_ms: Mapped[int] = mapped_column(default=0)
    error_type: Mapped[str | None]
    error: Mapped[str | None]
    retrieved_at: Mapped[datetime]

    __table_args__ = (
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        CheckConstraint("status IN ('ok', 'empty', 'error')", name="status"),
        Index("ix_culture_calls_workspace_id_source", "workspace_id", "source"),
        Index("ix_culture_calls_build_id", "build_id"),
    )
