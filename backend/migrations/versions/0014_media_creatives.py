"""Media stream: video and audio assets, derived files, creative_assets, creative_scenes, creative_xray runs.

`assets` gains upload and processing status, the rights confirmation, probe facts (duration, size), the link from a
derived file (keyframe, thumbnail, audio track) to its parent asset, and `media_info` (sanitized probe facts and the
redacted text sidecar). The kind CHECK widens to video, and the agent_runs run_type CHECK gains `creative_xray`.
Existing rows keep working: they read as stored images that need no processing.

Revision ID: 0014
Revises: 0018
Create Date: 2026-11-17 21:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0014"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
PRIOR_RUN_TYPES = (
    "'market_discovery', 'campaign_rehearsal', 'campaign_adaptation', 'campaign_evaluation', "
    "'cultural_profile', 'campaign_arena', 'risk_scan', 'market_comparison', 'population_study', 'social_simulation', "
    "'transcreate'"
)
RUN_TYPES = PRIOR_RUN_TYPES + ", 'creative_xray'"
PROCESSING = "'not_required', 'pending', 'processing', 'ready', 'failed'"
NEW_COLUMNS = (
    "upload_status", "processing_status", "processing_error", "rights_confirmed", "rights_confirmed_at", "duration_ms",
    "width", "height", "parent_asset_id", "derived_role", "derived_at_ms", "media_info",
)


def _run_types(values: str) -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint(op.f("ck_agent_runs_run_type"), type_="check")
        batch.create_check_constraint("run_type", f"run_type IN ({values})")


def upgrade() -> None:
    with op.batch_alter_table("assets") as batch:
        batch.add_column(sa.Column("upload_status", sa.String(), nullable=False, server_default="stored"))
        batch.add_column(sa.Column("processing_status", sa.String(), nullable=False, server_default="not_required"))
        batch.add_column(sa.Column("processing_error", sa.String(), nullable=True))
        batch.add_column(sa.Column("rights_confirmed", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("rights_confirmed_at", UTCDateTime(), nullable=True))
        batch.add_column(sa.Column("duration_ms", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("width", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("height", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("parent_asset_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("derived_role", sa.String(), nullable=True))
        batch.add_column(sa.Column("derived_at_ms", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("media_info", JSON, nullable=True))
        batch.drop_constraint(op.f("ck_assets_kind"), type_="check")
        batch.create_check_constraint("kind", "kind IN ('image', 'audio', 'video')")
        batch.create_check_constraint("upload_status", "upload_status IN ('stored', 'failed')")
        batch.create_check_constraint("processing_status", f"processing_status IN ({PROCESSING})")
        batch.create_check_constraint("derived_role", "derived_role IN ('keyframe', 'thumbnail', 'audio_track')")
        batch.create_foreign_key(
            op.f("fk_assets_parent_asset_id_assets"), "assets", ["parent_asset_id", "project_id"], ["id", "project_id"]
        )
        batch.create_index("ix_assets_parent_asset_id", ["parent_asset_id"], unique=False)
    _run_types(RUN_TYPES)

    op.create_table(
        "creative_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("region_code", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("latest_run_id", sa.Uuid(), nullable=True),
        sa.Column("current_run_id", sa.Uuid(), nullable=True),
        sa.Column("analysis", JSON, nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('image', 'video', 'audio')", name=op.f("ck_creative_assets_kind")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_creative_assets_project_id_projects")),
        sa.ForeignKeyConstraint(
            ["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"],
            name=op.f("fk_creative_assets_campaign_id_campaigns"),
        ),
        sa.ForeignKeyConstraint(
            ["asset_id", "project_id"], ["assets.id", "assets.project_id"], name=op.f("fk_creative_assets_asset_id_assets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_creative_assets")),
        sa.UniqueConstraint("id", "project_id", name=op.f("uq_creative_assets_id_project_id")),
        sa.UniqueConstraint("campaign_id", "asset_id", name=op.f("uq_creative_assets_campaign_id_asset_id")),
    )
    op.create_index(
        "ix_creative_assets_campaign_id_created_at", "creative_assets", ["campaign_id", "created_at"], unique=False
    )
    op.create_table(
        "creative_scenes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("creative_asset_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=True),
        sa.Column("keyframe_asset_id", sa.Uuid(), nullable=True),
        sa.Column("payload", JSON, nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_creative_scenes_project_id_projects")),
        sa.ForeignKeyConstraint(
            ["creative_asset_id", "project_id"], ["creative_assets.id", "creative_assets.project_id"],
            name=op.f("fk_creative_scenes_creative_asset_id_creative_assets"),
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"],
            name=op.f("fk_creative_scenes_campaign_id_campaigns"),
        ),
        sa.ForeignKeyConstraint(
            ["asset_id", "project_id"], ["assets.id", "assets.project_id"], name=op.f("fk_creative_scenes_asset_id_assets")
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id"], ["agent_runs.id", "agent_runs.project_id"],
            name=op.f("fk_creative_scenes_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["keyframe_asset_id", "project_id"], ["assets.id", "assets.project_id"],
            name=op.f("fk_creative_scenes_keyframe_asset_id_assets"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_creative_scenes")),
        sa.UniqueConstraint("id", "project_id", name=op.f("uq_creative_scenes_id_project_id")),
    )
    op.create_index(
        "ix_creative_scenes_creative_asset_id_run_id_position", "creative_scenes",
        ["creative_asset_id", "run_id", "position"], unique=False,
    )


def downgrade() -> None:
    op.drop_table("creative_scenes")
    op.drop_table("creative_assets")
    # Derived files and video uploads cannot exist in the old schema; their bytes go with the rows (children first).
    gone = "SELECT id FROM assets WHERE parent_asset_id IS NOT NULL OR kind = 'video'"
    op.execute(f"DELETE FROM asset_blobs WHERE asset_id IN ({gone})")
    op.execute("DELETE FROM assets WHERE parent_asset_id IS NOT NULL")
    op.execute("DELETE FROM assets WHERE kind = 'video'")
    op.execute("DELETE FROM agent_runs WHERE run_type = 'creative_xray'")
    _run_types(PRIOR_RUN_TYPES)
    with op.batch_alter_table("assets") as batch:
        batch.drop_index("ix_assets_parent_asset_id")
        batch.drop_constraint(op.f("fk_assets_parent_asset_id_assets"), type_="foreignkey")
        batch.drop_constraint(op.f("ck_assets_derived_role"), type_="check")
        batch.drop_constraint(op.f("ck_assets_processing_status"), type_="check")
        batch.drop_constraint(op.f("ck_assets_upload_status"), type_="check")
        batch.drop_constraint(op.f("ck_assets_kind"), type_="check")
        batch.create_check_constraint("kind", "kind IN ('image', 'audio')")
        for column in NEW_COLUMNS:
            batch.drop_column(column)
