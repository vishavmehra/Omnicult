"""Identity and tenancy: users, workspaces, workspace_members (Omnicult; additive).

`users.firebase_uid` maps Firebase Authentication uids to the internal UUID that every other table and service uses.
No Supabase objects are referenced. Row Level Security is not enabled on these tables (M-07; see 0012).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-17 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.base import UTCDateTime

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("firebase_uid", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("is_anonymous", sa.Boolean(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("firebase_uid", name=op.f("uq_users_firebase_uid")),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('personal', 'team')", name=op.f("ck_workspaces_kind")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_workspaces_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
    )
    op.create_index(
        "uq_workspaces_created_by_personal", "workspaces", ["created_by"], unique=True,
        sqlite_where=sa.text("kind = 'personal'"), postgresql_where=sa.text("kind = 'personal'"),
    )
    op.create_table(
        "workspace_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'editor', 'reviewer', 'viewer')", name=op.f("ck_workspace_members_role")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_workspace_members_workspace_id_workspaces")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_workspace_members_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_members")),
        sa.UniqueConstraint("workspace_id", "user_id", name=op.f("uq_workspace_members_workspace_id_user_id")),
    )
    op.create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_workspace_members_user_id", table_name="workspace_members")
    op.drop_table("workspace_members")
    op.drop_index("uq_workspaces_created_by_personal", table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_table("users")
