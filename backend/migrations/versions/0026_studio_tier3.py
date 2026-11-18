"""Creative Studio, Tier 3: claim_guard_checks, claim_guard_reviews and format_fit_outputs.

Additive. Script Check stores nothing. Every row is campaign-scoped by composite foreign keys, like the version tree it
points at. The lead re-chains this revision when merging.

Revision ID: 0026
Revises: 0027
Create Date: 2026-11-18 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0026"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
DECISIONS = "'substantiated', 'revise', 'accepted', 'not_a_claim'"


def _campaign_key(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"], name=op.f(f"fk_{table}_campaign_id_campaigns"))


def _version_key(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["version_id", "campaign_id"], ["version_nodes.id", "version_nodes.campaign_id"], name=op.f(f"fk_{table}_version_id_version_nodes"))


def upgrade() -> None:
    op.create_table(
        "claim_guard_checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("region_code", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("rules_version", sa.String(), nullable=False),
        sa.Column("result", JSON, nullable=False),
        sa.Column("model", JSON, nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("mode IN ('rules', 'rules_model')", name=op.f("ck_claim_guard_checks_mode")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_claim_guard_checks_project_id_projects")),
        _campaign_key("claim_guard_checks"),
        _version_key("claim_guard_checks"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_claim_guard_checks_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_guard_checks")),
    )
    op.create_index("ix_claim_guard_checks_version_id_created_at", "claim_guard_checks", ["version_id", "created_at"], unique=False)

    op.create_table(
        "claim_guard_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("finding_key", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(f"decision IN ({DECISIONS})", name=op.f("ck_claim_guard_reviews_decision")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_claim_guard_reviews_project_id_projects")),
        _campaign_key("claim_guard_reviews"),
        _version_key("claim_guard_reviews"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name=op.f("fk_claim_guard_reviews_reviewed_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_guard_reviews")),
        sa.UniqueConstraint("version_id", "finding_key", name=op.f("uq_claim_guard_reviews_version_id_finding_key")),
    )

    op.create_table(
        "format_fit_outputs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("creative_id", sa.Uuid(), nullable=False),
        sa.Column("source_asset_id", sa.Uuid(), nullable=False),
        sa.Column("output_asset_id", sa.Uuid(), nullable=False),
        sa.Column("format_id", sa.String(), nullable=False),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column("plan", JSON, nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("strategy IN ('crop', 'pad', 'native')", name=op.f("ck_format_fit_outputs_strategy")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_format_fit_outputs_project_id_projects")),
        _campaign_key("format_fit_outputs"),
        _version_key("format_fit_outputs"),
        sa.ForeignKeyConstraint(
            ["creative_id", "project_id"], ["creative_assets.id", "creative_assets.project_id"],
            name=op.f("fk_format_fit_outputs_creative_id_creative_assets"),
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id", "project_id"], ["assets.id", "assets.project_id"], name=op.f("fk_format_fit_outputs_source_asset_id_assets")
        ),
        sa.ForeignKeyConstraint(
            ["output_asset_id", "project_id"], ["assets.id", "assets.project_id"], name=op.f("fk_format_fit_outputs_output_asset_id_assets")
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_format_fit_outputs_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_format_fit_outputs")),
    )
    op.create_index("ix_format_fit_outputs_campaign_id_created_at", "format_fit_outputs", ["campaign_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_format_fit_outputs_campaign_id_created_at", table_name="format_fit_outputs")
    op.drop_table("format_fit_outputs")
    op.drop_table("claim_guard_reviews")
    op.drop_index("ix_claim_guard_checks_version_id_created_at", table_name="claim_guard_checks")
    op.drop_table("claim_guard_checks")
