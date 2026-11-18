"""Campaign Desk tables (migration 0019): the versioned Campaign Brief and the Brand Kit design.

`campaign_briefs` is append-only like `campaign_versions`: one immutable row per version, the current brief is the highest
number. `content` is validated by `app.schemas.desk.BriefContent` before it is written. `brand_kit_designs` holds the
design half of the Brand Kit (one row per brand, `revision` counts saves); the brand record itself stays in `brand_kits`.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class CampaignBriefRow(Base):
    __tablename__ = "campaign_briefs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID]
    project_id: Mapped[UUID]
    version_number: Mapped[int]
    content: Mapped[dict]
    change_note: Mapped[str | None]
    provenance: Mapped[dict] = mapped_column(default=dict)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"]),
        UniqueConstraint("campaign_id", "version_number"),
        CheckConstraint("version_number >= 1", name="version_number"),
        Index("ix_campaign_briefs_project_id_created_at", "project_id", "created_at"),
    )


class BrandKitDesignRow(Base):
    __tablename__ = "brand_kit_designs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), unique=True)
    revision: Mapped[int]
    design: Mapped[dict]
    provenance: Mapped[dict] = mapped_column(default=dict)
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (CheckConstraint("revision >= 1", name="revision"),)
