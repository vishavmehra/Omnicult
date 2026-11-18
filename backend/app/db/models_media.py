"""Media stream tables (migration 0014): the creatives Creative X-Ray analyses and the scenes it finds.

Re-exported by `app.db.models` (one import line at its end), so `m.CreativeAsset` and `m.CreativeScene` work.
Both are project-scoped like every child row, so the workspace-membership check in `services.common.get_owned`
covers them. A scene's fields beyond time and keyframe live in `payload` (validated by `schemas.xray`).
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


def _fk(columns: list[str], table: str, remote: list[str]) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(columns, [f"{table}.{column}" for column in remote])


class CreativeAsset(Base):
    """An uploaded asset registered as a campaign creative. One row per (campaign, asset); every X-Ray run of it adds
    scenes. `latest_run_id` is the newest run (possibly still running); `current_run_id` is the newest run that
    produced usable scenes, and the scenes of that run are what the list endpoints show by default."""

    __tablename__ = "creative_assets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID]
    asset_id: Mapped[UUID]
    kind: Mapped[str]
    label: Mapped[str]
    region_code: Mapped[str | None]  # the market the creative is read for (ISO 3166-2:IN), optional
    language: Mapped[str | None]  # declared spoken language (ISO 639-1), optional
    latest_run_id: Mapped[UUID | None]
    current_run_id: Mapped[UUID | None]
    analysis: Mapped[dict | None]  # probe facts, frame observations, transcript, statuses and limitations of the current run
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        _fk(["asset_id", "project_id"], "assets", ["id", "project_id"]),
        ForeignKeyConstraint(["latest_run_id", "project_id"], ["agent_runs.id", "agent_runs.project_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["current_run_id", "project_id"], ["agent_runs.id", "agent_runs.project_id"], ondelete="RESTRICT"),
        UniqueConstraint("id", "project_id"),
        UniqueConstraint("campaign_id", "asset_id"),
        CheckConstraint("kind IN ('image', 'video', 'audio')", name="kind"),
        Index("ix_creative_assets_campaign_id_created_at", "campaign_id", "created_at"),
    )


class CreativeScene(Base):
    """One scene of a creative (an image is one scene). Linked to the asset and the campaign directly, so a later
    stage can anchor findings with {scene_id, start_ms, end_ms}."""

    __tablename__ = "creative_scenes"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    creative_asset_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    asset_id: Mapped[UUID]
    run_id: Mapped[UUID]
    position: Mapped[int]
    start_ms: Mapped[int]
    end_ms: Mapped[int | None]
    keyframe_asset_id: Mapped[UUID | None]
    payload: Mapped[dict]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["creative_asset_id", "project_id"], "creative_assets", ["id", "project_id"]),
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        _fk(["asset_id", "project_id"], "assets", ["id", "project_id"]),
        _fk(["run_id", "project_id"], "agent_runs", ["id", "project_id"]),
        _fk(["keyframe_asset_id", "project_id"], "assets", ["id", "project_id"]),
        UniqueConstraint("id", "project_id"),
        Index("ix_creative_scenes_creative_asset_id_run_id_position", "creative_asset_id", "run_id", "position"),
    )
