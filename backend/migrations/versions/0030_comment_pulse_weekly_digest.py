"""Comment Pulse and Weekly Digest: pulse_comments, pulse_comment_analyses and pulse_digests (additive).

`pulse_comments` is the labelled sample comments dataset (one row per comment); `pulse_comment_analyses` stores each model
reading of it (sentiment and themes, with the prompt version and model that made it); `pulse_digests` stores one weekly
digest per campaign and ISO week. The lead re-chains this revision when merging.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-18 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
CAMPAIGN_KEY = {"ondelete": "RESTRICT"}


def _campaign_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"],
        name=op.f(f"fk_{table}_campaign_id_campaigns"), **CAMPAIGN_KEY,
    )


def upgrade() -> None:
    op.create_table(
        "pulse_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("ref", sa.String(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("region_code", sa.String(), nullable=False),
        sa.Column("version_label", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("script", sa.String(), nullable=False),
        sa.Column("code_mixed", sa.Boolean(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("likes", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("dataset_version", sa.String(), nullable=False),
        sa.Column("last_updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("source_kind IN ('sample', 'test_account', 'live')", name=op.f("ck_pulse_comments_source_kind")),
        sa.CheckConstraint("likes >= 0", name=op.f("ck_pulse_comments_likes")),
        _campaign_fk("pulse_comments"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_pulse_comments_workspace_id_workspaces")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_pulse_comments_project_id_projects")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pulse_comments")),
        sa.UniqueConstraint("campaign_id", "source_kind", "ref", name=op.f("uq_pulse_comments_campaign_id_source_kind_ref")),
    )
    op.create_index(
        "ix_pulse_comments_campaign_id_source_kind_region_code_day",
        "pulse_comments", ["campaign_id", "source_kind", "region_code", "day"], unique=False,
    )
    op.create_table(
        "pulse_comment_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model_id", sa.String(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Double(), nullable=True),
        sa.Column("comment_count", sa.Integer(), nullable=False),
        sa.Column("read_count", sa.Integer(), nullable=False),
        sa.Column("dropped", JSON, nullable=False),
        sa.Column("labels", JSON, nullable=False),
        sa.Column("themes", JSON, nullable=False),
        sa.Column("notes", JSON, nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f("ck_pulse_comment_analyses_mode")),
        sa.CheckConstraint("status IN ('completed', 'partial')", name=op.f("ck_pulse_comment_analyses_status")),
        _campaign_fk("pulse_comment_analyses"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_pulse_comment_analyses_workspace_id_workspaces")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_pulse_comment_analyses_project_id_projects")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_pulse_comment_analyses_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pulse_comment_analyses")),
    )
    op.create_index(
        "ix_pulse_comment_analyses_campaign_id_created_at", "pulse_comment_analyses", ["campaign_id", "created_at"], unique=False
    )
    op.create_table(
        "pulse_digests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("iso_year", sa.Integer(), nullable=False),
        sa.Column("iso_week", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("content", JSON, nullable=False),
        sa.Column("content_sha256", sa.String(), nullable=False),
        sa.Column("narrative", JSON, nullable=True),
        sa.Column("generated_by", sa.Uuid(), nullable=True),
        sa.Column("generated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f("ck_pulse_digests_mode")),
        sa.CheckConstraint("trigger IN ('manual', 'scheduler')", name=op.f("ck_pulse_digests_trigger")),
        sa.CheckConstraint("iso_week BETWEEN 1 AND 53", name=op.f("ck_pulse_digests_iso_week")),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_pulse_digests_revision")),
        _campaign_fk("pulse_digests"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_pulse_digests_workspace_id_workspaces")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_pulse_digests_project_id_projects")),
        sa.ForeignKeyConstraint(["generated_by"], ["users.id"], name=op.f("fk_pulse_digests_generated_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pulse_digests")),
        sa.UniqueConstraint("campaign_id", "iso_year", "iso_week", name=op.f("uq_pulse_digests_campaign_id_iso_year_iso_week")),
    )
    op.create_index("ix_pulse_digests_campaign_id_week_start", "pulse_digests", ["campaign_id", "week_start"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pulse_digests_campaign_id_week_start", table_name="pulse_digests")
    op.drop_table("pulse_digests")
    op.drop_index("ix_pulse_comment_analyses_campaign_id_created_at", table_name="pulse_comment_analyses")
    op.drop_table("pulse_comment_analyses")
    op.drop_index("ix_pulse_comments_campaign_id_source_kind_region_code_day", table_name="pulse_comments")
    op.drop_table("pulse_comments")
