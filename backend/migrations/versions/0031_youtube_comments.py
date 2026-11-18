"""Comment Pulse reads public YouTube comments (additive).

`pulse_comments` gains the video id, the YouTube comment id, the time a comment was published and its reply count (all
nullable: sample rows have none), a CHECK that now allows `source_kind = 'youtube'`, and a unique key on the YouTube comment id
so a re-fetch updates a row instead of adding another. No author name, channel id or avatar column exists. `pulse_comment_analyses`
gains `source_kind` (existing readings are 'sample'). New table `pulse_youtube_sources`: which video was fetched for which
campaign version and region, how, and when (the interval between two fetches of one video is enforced from it).

Revision ID: 0031
Revises: 0026
Create Date: 2026-11-18 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.base import UTCDateTime

revision: str = "0031"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIOR_SOURCES = "'sample', 'test_account', 'live'"
SOURCES = PRIOR_SOURCES + ", 'youtube'"


def _source_kinds(values: str) -> None:
    with op.batch_alter_table("pulse_comments") as batch:
        batch.drop_constraint(op.f("ck_pulse_comments_source_kind"), type_="check")
        batch.create_check_constraint("source_kind", f"source_kind IN ({values})")


def upgrade() -> None:
    _source_kinds(SOURCES)
    with op.batch_alter_table("pulse_comments") as batch:
        batch.add_column(sa.Column("video_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("external_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("published_at", UTCDateTime(), nullable=True))
        batch.add_column(sa.Column("reply_count", sa.Integer(), nullable=True))
        batch.create_check_constraint("reply_count", "reply_count IS NULL OR reply_count >= 0")
        batch.create_unique_constraint(
            op.f("uq_pulse_comments_campaign_id_source_kind_external_id"), ["campaign_id", "source_kind", "external_id"])
    with op.batch_alter_table("pulse_comment_analyses") as batch:
        batch.add_column(sa.Column("source_kind", sa.String(), nullable=False, server_default="sample"))
        batch.create_check_constraint("source_kind", "source_kind IN ('sample', 'youtube')")
    op.create_table(
        "pulse_youtube_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("video_id", sa.String(), nullable=False),
        sa.Column("video_title", sa.String(), nullable=True),
        sa.Column("version_label", sa.String(), nullable=False),
        sa.Column("region_code", sa.String(), nullable=False),
        sa.Column("comment_order", sa.String(), nullable=False),
        sa.Column("pages_fetched", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("fetched_at", UTCDateTime(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("comment_order IN ('relevance', 'time')", name=op.f("ck_pulse_youtube_sources_comment_order")),
        sa.CheckConstraint("pages_fetched >= 1", name=op.f("ck_pulse_youtube_sources_pages_fetched")),
        sa.ForeignKeyConstraint(
            ["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"],
            name=op.f("fk_pulse_youtube_sources_campaign_id_campaigns"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_pulse_youtube_sources_workspace_id_workspaces")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_pulse_youtube_sources_project_id_projects")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_pulse_youtube_sources_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pulse_youtube_sources")),
        sa.UniqueConstraint("campaign_id", "video_id", name=op.f("uq_pulse_youtube_sources_campaign_id_video_id")),
        sa.UniqueConstraint(
            "campaign_id", "version_label", "region_code", name=op.f("uq_pulse_youtube_sources_campaign_id_version_label_region_code")),
    )
    op.create_index("ix_pulse_youtube_sources_video_id", "pulse_youtube_sources", ["video_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pulse_youtube_sources_video_id", table_name="pulse_youtube_sources")
    op.drop_table("pulse_youtube_sources")
    op.execute("DELETE FROM pulse_comment_analyses WHERE source_kind = 'youtube'")
    with op.batch_alter_table("pulse_comment_analyses") as batch:
        batch.drop_constraint(op.f("ck_pulse_comment_analyses_source_kind"), type_="check")
        batch.drop_column("source_kind")
    op.execute("DELETE FROM pulse_comments WHERE source_kind = 'youtube'")
    with op.batch_alter_table("pulse_comments") as batch:
        batch.drop_constraint(op.f("uq_pulse_comments_campaign_id_source_kind_external_id"), type_="unique")
        batch.drop_constraint(op.f("ck_pulse_comments_reply_count"), type_="check")
        batch.drop_column("reply_count")
        batch.drop_column("published_at")
        batch.drop_column("external_id")
        batch.drop_column("video_id")
    _source_kinds(PRIOR_SOURCES)
