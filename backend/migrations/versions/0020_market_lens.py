"""Market Lens: lens_builds (versioned profile snapshots) and culture_calls (the culture call log for Data Health).

Additive. Claims keep living in `claims`; a build records what a run of the culture layer gathered and what was missing.
The lead re-chains this revision when merging.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-18 03:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "lens_builds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("region_code", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("years", JSON, nullable=False),
        sa.Column("options", JSON, nullable=False),
        sa.Column("claim_count", sa.Integer(), nullable=False),
        sa.Column("created_claims", sa.Integer(), nullable=False),
        sa.Column("updated_claims", sa.Integer(), nullable=False),
        sa.Column("conflicts_opened", sa.Integer(), nullable=False),
        sa.Column("rejected_claims", sa.Integer(), nullable=False),
        sa.Column("categories", JSON, nullable=False),
        sa.Column("gaps", JSON, nullable=False),
        sa.Column("sources_skipped", JSON, nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("started_at", UTCDateTime(), nullable=False),
        sa.Column("finished_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f("ck_lens_builds_mode")),
        sa.CheckConstraint("status IN ('completed', 'partial', 'failed')", name=op.f("ck_lens_builds_status")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_lens_builds_workspace_id_workspaces")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_lens_builds_project_id_projects")),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], name=op.f("fk_lens_builds_campaign_id_campaigns")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_lens_builds_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lens_builds")),
        sa.UniqueConstraint(
            "workspace_id", "region_code", "mode", "version", name=op.f("uq_lens_builds_workspace_id_region_code_mode_version")
        ),
    )
    op.create_index(
        "ix_lens_builds_workspace_id_region_code_mode", "lens_builds", ["workspace_id", "region_code", "mode"], unique=False
    )
    op.create_table(
        "culture_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("build_id", sa.Uuid(), nullable=True),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("cached", sa.Boolean(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("retrieved_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f("ck_culture_calls_mode")),
        sa.CheckConstraint("status IN ('ok', 'empty', 'error')", name=op.f("ck_culture_calls_status")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_culture_calls_workspace_id_workspaces")),
        sa.ForeignKeyConstraint(["build_id"], ["lens_builds.id"], name=op.f("fk_culture_calls_build_id_lens_builds")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_culture_calls")),
    )
    op.create_index("ix_culture_calls_workspace_id_source", "culture_calls", ["workspace_id", "source"], unique=False)
    op.create_index("ix_culture_calls_build_id", "culture_calls", ["build_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_culture_calls_build_id", table_name="culture_calls")
    op.drop_index("ix_culture_calls_workspace_id_source", table_name="culture_calls")
    op.drop_table("culture_calls")
    op.drop_index("ix_lens_builds_workspace_id_region_code_mode", table_name="lens_builds")
    op.drop_table("lens_builds")
