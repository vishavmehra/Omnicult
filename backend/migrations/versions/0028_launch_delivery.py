"""Launch Room delivery: review_links, review_responses and asset_packs (Omnicult; additive).

A review link stores only the hash of its token. Reviewer decisions are append-only and sit beside, never inside, the
`approvals` table. An asset pack row keeps the ZIP bytes only when ASSET_STORAGE_BACKEND=database; every other backend
holds them in the blob store. The (version_id, campaign_id) keys point at version_nodes, so a link, a response or a pack can
only name a version of its own campaign.

Revision ID: 0028
Revises: 0024
Create Date: 2026-11-18 14:00:00

The lead re-chains this revision when merging (the Phase 4 contract gives every stream its own `down_revision`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0028"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
DECISIONS = "'approve', 'request_changes', 'reject', 'comment'"


def _campaign_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"], name=op.f(f"fk_{table}_campaign_id_campaigns")
    )


def _version_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["version_id", "campaign_id"], ["version_nodes.id", "version_nodes.campaign_id"], ondelete="RESTRICT",
        name=op.f(f"fk_{table}_version_id_version_nodes"),
    )


def upgrade() -> None:
    op.create_table(
        "review_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("items", JSON, nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("token_hint", sa.String(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("revoked_at", UTCDateTime(), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f("ck_review_links_mode")),
        _campaign_fk("review_links"),
        sa.ForeignKeyConstraint(["revoked_by"], ["users.id"], name=op.f("fk_review_links_revoked_by_users")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_review_links_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_links")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_review_links_token_hash")),
    )
    op.create_index("ix_review_links_campaign_id_created_at", "review_links", ["campaign_id", "created_at"], unique=False)
    op.create_table(
        "review_responses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("link_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("region_code", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("comment", sa.String(), nullable=True),
        sa.Column("reviewer_name", sa.String(), nullable=True),
        sa.Column("reviewer_kind", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(f"decision IN ({DECISIONS})", name=op.f("ck_review_responses_decision")),
        sa.CheckConstraint("reviewer_kind IN ('named', 'anonymous')", name=op.f("ck_review_responses_reviewer_kind")),
        sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f("ck_review_responses_mode")),
        _campaign_fk("review_responses"),
        _version_fk("review_responses"),
        sa.ForeignKeyConstraint(["link_id"], ["review_links.id"], name=op.f("fk_review_responses_link_id_review_links")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_responses")),
    )
    op.create_index("ix_review_responses_link_id_created_at", "review_responses", ["link_id", "created_at"], unique=False)
    op.create_index("ix_review_responses_campaign_id_version_id", "review_responses", ["campaign_id", "version_id"], unique=False)
    op.create_table(
        "asset_packs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("region_code", sa.String(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=True),
        sa.Column("manifest", JSON, nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f("ck_asset_packs_mode")),
        _campaign_fk("asset_packs"),
        _version_fk("asset_packs"),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"], name=op.f("fk_asset_packs_approval_id_approvals")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_asset_packs_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_packs")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_asset_packs_token_hash")),
    )
    op.create_index("ix_asset_packs_campaign_id_created_at", "asset_packs", ["campaign_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_asset_packs_campaign_id_created_at", table_name="asset_packs")
    op.drop_table("asset_packs")
    op.drop_index("ix_review_responses_campaign_id_version_id", table_name="review_responses")
    op.drop_index("ix_review_responses_link_id_created_at", table_name="review_responses")
    op.drop_table("review_responses")
    op.drop_index("ix_review_links_campaign_id_created_at", table_name="review_links")
    op.drop_table("review_links")
