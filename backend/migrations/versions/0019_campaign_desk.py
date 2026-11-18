"""Campaign Desk: versioned campaign_briefs and brand_kit_designs (Omnicult; additive).

`campaign_briefs` holds one immutable row per brief version (the highest number is current); `brand_kit_designs` holds the
design half of the Brand Kit, one row per brand. The lead re-chains this revision when merging.

Revision ID: 0019
Revises: 0021
Create Date: 2026-11-18 03:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0019"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "campaign_briefs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content", JSON, nullable=False),
        sa.Column("change_note", sa.String(), nullable=True),
        sa.Column("provenance", JSON, nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("version_number >= 1", name=op.f("ck_campaign_briefs_version_number")),
        sa.ForeignKeyConstraint(
            ["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"],
            name=op.f("fk_campaign_briefs_campaign_id_campaigns"),
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_campaign_briefs_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaign_briefs")),
        sa.UniqueConstraint("campaign_id", "version_number", name=op.f("uq_campaign_briefs_campaign_id_version_number")),
    )
    op.create_index("ix_campaign_briefs_project_id_created_at", "campaign_briefs", ["project_id", "created_at"], unique=False)
    op.create_table(
        "brand_kit_designs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("design", JSON, nullable=False),
        sa.Column("provenance", JSON, nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_brand_kit_designs_revision")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_brand_kit_designs_project_id_projects")),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name=op.f("fk_brand_kit_designs_updated_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brand_kit_designs")),
        sa.UniqueConstraint("project_id", name=op.f("uq_brand_kit_designs_project_id")),
    )


def downgrade() -> None:
    op.drop_table("brand_kit_designs")
    op.drop_index("ix_campaign_briefs_project_id_created_at", table_name="campaign_briefs")
    op.drop_table("campaign_briefs")
