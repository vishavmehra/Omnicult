"""Launch Room: readiness_verdicts and approvals (Omnicult; additive).

Both tables are append-only history. `version_id` carries no foreign key on purpose: the version may be a campaign content
version or a Creative Studio version node, and the integration step adds the constraint once both exist.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-17 23:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
VERDICTS = "'go', 'fix', 'rethink'"


def upgrade() -> None:
    op.create_table(
        "readiness_verdicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("region_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("main_reason", sa.String(), nullable=False),
        sa.Column("rule_version", sa.String(), nullable=False),
        sa.Column("scoring_version", sa.String(), nullable=False),
        sa.Column("overall_score", sa.Double(), nullable=True),
        sa.Column("input_fingerprint", sa.String(), nullable=False),
        sa.Column("inputs", JSON, nullable=False),
        sa.Column("result", JSON, nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("computed_by", sa.Uuid(), nullable=False),
        sa.Column("computed_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(f"verdict IN ({VERDICTS})", name=op.f("ck_readiness_verdicts_verdict")),
        sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f("ck_readiness_verdicts_mode")),
        sa.ForeignKeyConstraint(
            ["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"],
            name=op.f("fk_readiness_verdicts_campaign_id_campaigns"),
        ),
        sa.ForeignKeyConstraint(["region_id"], ["regions.id"], name=op.f("fk_readiness_verdicts_region_id_regions")),
        sa.ForeignKeyConstraint(["computed_by"], ["users.id"], name=op.f("fk_readiness_verdicts_computed_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_readiness_verdicts")),
    )
    op.create_index(
        "ix_readiness_verdicts_campaign_region_version_at", "readiness_verdicts",
        ["campaign_id", "region_id", "version_id", "computed_at"], unique=False,
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("region_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("readiness_verdict_id", sa.Uuid(), nullable=True),
        sa.Column("verdict_at_decision", sa.String(), nullable=True),
        sa.Column("overrides_recommendation", sa.Boolean(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=False),
        sa.Column("decided_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("decision IN ('approve', 'reject', 'request_changes')", name=op.f("ck_approvals_decision")),
        sa.CheckConstraint(
            f"verdict_at_decision IS NULL OR verdict_at_decision IN ({VERDICTS})", name=op.f("ck_approvals_verdict_at_decision")
        ),
        sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f("ck_approvals_mode")),
        sa.ForeignKeyConstraint(
            ["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"],
            name=op.f("fk_approvals_campaign_id_campaigns"),
        ),
        sa.ForeignKeyConstraint(["region_id"], ["regions.id"], name=op.f("fk_approvals_region_id_regions")),
        sa.ForeignKeyConstraint(
            ["readiness_verdict_id"], ["readiness_verdicts.id"], name=op.f("fk_approvals_readiness_verdict_id_readiness_verdicts")
        ),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], name=op.f("fk_approvals_decided_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
    )
    op.create_index(
        "ix_approvals_campaign_region_version_at", "approvals",
        ["campaign_id", "region_id", "version_id", "decided_at"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_approvals_campaign_region_version_at", table_name="approvals")
    op.drop_table("approvals")
    op.drop_index("ix_readiness_verdicts_campaign_region_version_at", table_name="readiness_verdicts")
    op.drop_table("readiness_verdicts")
