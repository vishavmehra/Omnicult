"""Settings: workspace_invites and workspace_settings (Omnicult; additive).

`workspace_invites` is a stored record only (no email is sent); only a hash of the invite code is kept.
`workspace_settings` holds the default regions of a workspace. The lead re-chains this revision when merging.

Revision ID: 0022
Revises: 0020
Create Date: 2026-11-18 03:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0022"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "workspace_invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("accepted_by", sa.Uuid(), nullable=True),
        sa.Column("accepted_at", UTCDateTime(), nullable=True),
        sa.Column("revoked_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint("role IN ('owner', 'editor', 'reviewer', 'viewer')", name=op.f("ck_workspace_invites_role")),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')", name=op.f("ck_workspace_invites_status")
        ),
        sa.ForeignKeyConstraint(["accepted_by"], ["users.id"], name=op.f("fk_workspace_invites_accepted_by_users")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_workspace_invites_created_by_users")),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_workspace_invites_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_invites")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_workspace_invites_code_hash")),
    )
    op.create_index(
        "ix_workspace_invites_workspace_id_created_at", "workspace_invites", ["workspace_id", "created_at"], unique=False
    )
    op.create_index(
        "uq_workspace_invites_workspace_id_email_pending", "workspace_invites", ["workspace_id", "email"], unique=True,
        sqlite_where=sa.text("status = 'pending'"), postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "workspace_settings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("default_region_codes", JSON, nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name=op.f("fk_workspace_settings_updated_by_users")),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_workspace_settings_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("workspace_id", name=op.f("pk_workspace_settings")),
    )


def downgrade() -> None:
    op.drop_table("workspace_settings")
    op.drop_index("uq_workspace_invites_workspace_id_email_pending", table_name="workspace_invites")
    op.drop_index("ix_workspace_invites_workspace_id_created_at", table_name="workspace_invites")
    op.drop_table("workspace_invites")
