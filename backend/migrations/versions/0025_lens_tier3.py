"""Market Lens Tier 3: lens_trend_batches and lens_trend_snapshots (Trend Radar) and lens_shelf_snapshots (Category Shelf).

Additive. Snapshots keep what a refresh retrieved so the radar can compare with earlier readings; nothing existing changes.
Chained on 0020 as CONTRACTS_PHASE4 says (the base has two heads, 0020 and 0021); the lead re-chains this revision when merging.

Revision ID: 0025
Revises: 0030
Create Date: 2026-11-18 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0025"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "lens_trend_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("category_text", sa.String(), nullable=True),
        sa.Column("pack_key", sa.String(), nullable=True),
        sa.Column("regions", JSON, nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("method_version", sa.String(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("taken_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f("ck_lens_trend_batches_mode")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_lens_trend_batches_workspace_id_workspaces")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_lens_trend_batches_project_id_projects")),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], name=op.f("fk_lens_trend_batches_campaign_id_campaigns")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_lens_trend_batches_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lens_trend_batches")),
    )
    op.create_index("ix_lens_trend_batches_workspace_id_mode_taken_at", "lens_trend_batches", ["workspace_id", "mode", "taken_at"], unique=False)
    op.create_table(
        "lens_trend_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("region_code", sa.String(), nullable=False),
        sa.Column("term", sa.String(), nullable=False),
        sa.Column("term_kind", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("festival_subject", sa.String(), nullable=True),
        sa.Column("granularity", sa.String(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("method_version", sa.String(), nullable=False),
        sa.Column("editions", JSON, nullable=False),
        sa.Column("source", JSON, nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("taken_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f("ck_lens_trend_snapshots_mode")),
        sa.CheckConstraint("term_kind IN ('festival', 'category')", name=op.f("ck_lens_trend_snapshots_term_kind")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_lens_trend_snapshots_workspace_id_workspaces")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_lens_trend_snapshots_project_id_projects")),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], name=op.f("fk_lens_trend_snapshots_campaign_id_campaigns")),
        sa.ForeignKeyConstraint(["batch_id"], ["lens_trend_batches.id"], name=op.f("fk_lens_trend_snapshots_batch_id_lens_trend_batches")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_lens_trend_snapshots_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lens_trend_snapshots")),
    )
    op.create_index(
        "ix_lens_trend_snapshots_workspace_id_mode_region_code_term", "lens_trend_snapshots",
        ["workspace_id", "mode", "region_code", "term"], unique=False)
    op.create_index("ix_lens_trend_snapshots_batch_id", "lens_trend_snapshots", ["batch_id"], unique=False)
    op.create_table(
        "lens_shelf_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("pack_key", sa.String(), nullable=False),
        sa.Column("category_text", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("discovery", JSON, nullable=False),
        sa.Column("attention", JSON, nullable=False),
        sa.Column("gaps", JSON, nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("taken_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f("ck_lens_shelf_snapshots_mode")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_lens_shelf_snapshots_workspace_id_workspaces")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_lens_shelf_snapshots_project_id_projects")),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], name=op.f("fk_lens_shelf_snapshots_campaign_id_campaigns")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_lens_shelf_snapshots_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lens_shelf_snapshots")),
        sa.UniqueConstraint(
            "workspace_id", "mode", "pack_key", "version", name=op.f("uq_lens_shelf_snapshots_workspace_id_mode_pack_key_version")
        ),
    )
    op.create_index(
        "ix_lens_shelf_snapshots_workspace_id_mode_pack_key", "lens_shelf_snapshots", ["workspace_id", "mode", "pack_key"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_lens_shelf_snapshots_workspace_id_mode_pack_key", table_name="lens_shelf_snapshots")
    op.drop_table("lens_shelf_snapshots")
    op.drop_index("ix_lens_trend_snapshots_batch_id", table_name="lens_trend_snapshots")
    op.drop_index("ix_lens_trend_snapshots_workspace_id_mode_region_code_term", table_name="lens_trend_snapshots")
    op.drop_table("lens_trend_snapshots")
    op.drop_index("ix_lens_trend_batches_workspace_id_mode_taken_at", table_name="lens_trend_batches")
    op.drop_table("lens_trend_batches")
