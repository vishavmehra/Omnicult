"""Evidence: claims, claim_sources, conflicts, conflict_resolutions (Omnicult; additive).

`claims.workspace_id` is NULL for shared reference claims. Confidence is a computed column (app.analytics.confidence).
Conflicts are per workspace and append-only history lives in conflict_resolutions.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-17 14:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
KINDS = "'observed', 'calculated', 'synthetic', 'interpretation', 'unverified'"
CATEGORIES = (
    "'language', 'script', 'festival', 'moment', 'food', 'colour', 'symbol', 'humour', 'family', 'custom', "
    "'sensitivity', 'trend', 'demographic', 'media'"
)


def upgrade() -> None:
    op.create_table(
        "claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("region_id", sa.Uuid(), nullable=True),
        sa.Column("claim_key", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("attribute", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("value", JSON, nullable=False),
        sa.Column("value_text", sa.String(), nullable=False),
        sa.Column("scope", JSON, nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("confidence", sa.String(), nullable=False),
        sa.Column("confidence_reason", sa.String(), nullable=False),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("retrieved_at", UTCDateTime(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(f"kind IN ({KINDS})", name=op.f("ck_claims_kind")),
        sa.CheckConstraint(f"category IN ({CATEGORIES})", name=op.f("ck_claims_category")),
        sa.CheckConstraint("confidence IN ('low', 'moderate', 'high')", name=op.f("ck_claims_confidence")),
        sa.CheckConstraint("status IN ('active', 'needs_review', 'rejected', 'superseded')", name=op.f("ck_claims_status")),
        sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f("ck_claims_mode")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_claims_workspace_id_workspaces")),
        sa.ForeignKeyConstraint(["region_id"], ["regions.id"], name=op.f("fk_claims_region_id_regions")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claims")),
        sa.UniqueConstraint("claim_key", name=op.f("uq_claims_claim_key")),
    )
    op.create_index("ix_claims_region_id_category", "claims", ["region_id", "category"], unique=False)
    op.create_index("ix_claims_workspace_id_region_id", "claims", ["workspace_id", "region_id"], unique=False)
    op.create_index("ix_claims_subject_attribute", "claims", ["subject", "attribute"], unique=False)
    op.create_table(
        "claim_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_identifier", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("publisher", sa.String(), nullable=True),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("retrieved_at", UTCDateTime(), nullable=False),
        sa.Column("excerpt", sa.String(), nullable=True),
        sa.Column("independence_group", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], name=op.f("fk_claim_sources_claim_id_claims")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_sources")),
        sa.UniqueConstraint("claim_id", "source_type", "source_identifier", name=op.f("uq_claim_sources_claim_id_source_type_source_identifier")),
    )
    op.create_table(
        "conflicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("region_id", sa.Uuid(), nullable=True),
        sa.Column("claim_a_id", sa.Uuid(), nullable=False),
        sa.Column("claim_b_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("current_selection", sa.String(), nullable=False),
        sa.Column("selection_reason", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("current_selection IN ('a', 'b')", name=op.f("ck_conflicts_current_selection")),
        sa.CheckConstraint("status IN ('open', 'review_requested', 'resolved')", name=op.f("ck_conflicts_status")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_conflicts_workspace_id_workspaces")),
        sa.ForeignKeyConstraint(["region_id"], ["regions.id"], name=op.f("fk_conflicts_region_id_regions")),
        sa.ForeignKeyConstraint(["claim_a_id"], ["claims.id"], name=op.f("fk_conflicts_claim_a_id_claims")),
        sa.ForeignKeyConstraint(["claim_b_id"], ["claims.id"], name=op.f("fk_conflicts_claim_b_id_claims")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conflicts")),
        sa.UniqueConstraint("workspace_id", "claim_a_id", "claim_b_id", name=op.f("uq_conflicts_workspace_id_claim_a_id_claim_b_id")),
    )
    op.create_index("ix_conflicts_workspace_id_status", "conflicts", ["workspace_id", "status"], unique=False)
    op.create_table(
        "conflict_resolutions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conflict_id", sa.Uuid(), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("selection_after", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("decided_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("decision IN ('accept', 'switch', 'request_review')", name=op.f("ck_conflict_resolutions_decision")),
        sa.CheckConstraint("selection_after IN ('a', 'b')", name=op.f("ck_conflict_resolutions_selection_after")),
        sa.ForeignKeyConstraint(["conflict_id"], ["conflicts.id"], name=op.f("fk_conflict_resolutions_conflict_id_conflicts")),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], name=op.f("fk_conflict_resolutions_decided_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conflict_resolutions")),
    )
    op.create_index("ix_conflict_resolutions_conflict_id_decided_at", "conflict_resolutions", ["conflict_id", "decided_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_conflict_resolutions_conflict_id_decided_at", table_name="conflict_resolutions")
    op.drop_table("conflict_resolutions")
    op.drop_index("ix_conflicts_workspace_id_status", table_name="conflicts")
    op.drop_table("conflicts")
    op.drop_table("claim_sources")
    op.drop_index("ix_claims_subject_attribute", table_name="claims")
    op.drop_index("ix_claims_workspace_id_region_id", table_name="claims")
    op.drop_index("ix_claims_region_id_category", table_name="claims")
    op.drop_table("claims")
