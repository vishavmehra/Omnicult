"""Live Pulse: platform_connections and metric_series (Omnicult; additive).

`platform_connections` is a read-only status list (nothing can be connected in this build; no credential columns).
`metric_series` is the long-format store behind the regional dashboard; `source_kind` separates the labelled sample
dataset from rows of a future connected account. The lead re-chains this revision when merging.

Revision ID: 0018
Revises: 0016
Create Date: 2026-11-17 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0018"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
PLATFORMS = "'google_ads', 'youtube', 'meta', 'ga4'"


def upgrade() -> None:
    op.create_table(
        "platform_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("last_sync_at", UTCDateTime(), nullable=True),
        sa.Column("scopes", JSON, nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(f"platform IN ({PLATFORMS})", name=op.f("ck_platform_connections_platform")),
        sa.CheckConstraint(
            "status IN ('not_connected', 'test_account', 'connected')", name=op.f("ck_platform_connections_status")
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_platform_connections_workspace_id_workspaces")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_connections")),
        sa.UniqueConstraint("workspace_id", "platform", name=op.f("uq_platform_connections_workspace_id_platform")),
    )
    op.create_table(
        "metric_series",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("version_label", sa.String(), nullable=False),
        sa.Column("region_code", sa.String(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column("provisional", sa.Boolean(), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("dataset_version", sa.String(), nullable=False),
        sa.Column("last_updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(f"platform IN ({PLATFORMS})", name=op.f("ck_metric_series_platform")),
        sa.CheckConstraint("source_kind IN ('sample', 'test_account', 'live')", name=op.f("ck_metric_series_source_kind")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_metric_series_workspace_id_workspaces")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_metric_series_project_id_projects")),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], name=op.f("fk_metric_series_campaign_id_campaigns")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metric_series")),
        sa.UniqueConstraint(
            "campaign_id", "source_kind", "day", "platform", "channel", "version_label", "region_code", "metric",
            name="uq_metric_series_slice",
        ),
    )
    op.create_index(
        "ix_metric_series_campaign_id_source_kind_region_code_day",
        "metric_series", ["campaign_id", "source_kind", "region_code", "day"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_metric_series_campaign_id_source_kind_region_code_day", table_name="metric_series")
    op.drop_table("metric_series")
    op.drop_table("platform_connections")
