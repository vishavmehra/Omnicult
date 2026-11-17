"""projects.workspace_id, and a personal workspace for every existing project owner (Omnicult; additive).

The column stays nullable (contract phase: NOT NULL after a release on the new code). The backfill reuses each
`owner_id` as the `users.id` of a new user row (firebase_uid NULL until that person first signs in through Firebase;
development tokens map to the same UUID), creates one personal workspace and one owner membership per owner, and
points that owner's projects at it. Idempotent: users and workspaces that already exist are reused.

Downgrade drops the column; the users and workspaces stay (0007 removes them).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-17 14:10:00
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

users = sa.table("users", sa.column("id", sa.Uuid()), sa.column("firebase_uid", sa.String()),
                 sa.column("is_anonymous", sa.Boolean()), sa.column("created_at", sa.DateTime(timezone=True)))
workspaces = sa.table("workspaces", sa.column("id", sa.Uuid()), sa.column("name", sa.String()), sa.column("kind", sa.String()),
                      sa.column("created_by", sa.Uuid()), sa.column("created_at", sa.DateTime(timezone=True)))
members = sa.table("workspace_members", sa.column("id", sa.Uuid()), sa.column("workspace_id", sa.Uuid()),
                   sa.column("user_id", sa.Uuid()), sa.column("role", sa.String()),
                   sa.column("created_at", sa.DateTime(timezone=True)))
projects = sa.table("projects", sa.column("id", sa.Uuid()), sa.column("owner_id", sa.Uuid()),
                    sa.column("workspace_id", sa.Uuid()))


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("workspace_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(op.f("fk_projects_workspace_id_workspaces"), "workspaces", ["workspace_id"], ["id"])
        batch.create_index("ix_projects_workspace_id_last_activity_at", ["workspace_id", "last_activity_at"], unique=False)
    _backfill(op.get_bind())


def _backfill(bind: sa.engine.Connection) -> None:
    now = datetime.now(UTC)
    owners = [row[0] for row in bind.execute(sa.select(projects.c.owner_id).distinct())]
    for owner in owners:
        if bind.execute(sa.select(users.c.id).where(users.c.id == owner)).first() is None:
            bind.execute(sa.insert(users).values(id=owner, firebase_uid=None, is_anonymous=False, created_at=now))
        workspace = bind.execute(
            sa.select(workspaces.c.id).where(workspaces.c.created_by == owner, workspaces.c.kind == "personal")
        ).scalar()
        if workspace is None:
            workspace = uuid4()
            bind.execute(sa.insert(workspaces).values(
                id=workspace, name="My workspace", kind="personal", created_by=owner, created_at=now))
            bind.execute(sa.insert(members).values(
                id=uuid4(), workspace_id=workspace, user_id=owner, role="owner", created_at=now))
        bind.execute(
            sa.update(projects).where(projects.c.owner_id == owner, projects.c.workspace_id.is_(None))
            .values(workspace_id=workspace)
        )


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_index("ix_projects_workspace_id_last_activity_at")
        batch.drop_constraint(op.f("fk_projects_workspace_id_workspaces"), type_="foreignkey")
        batch.drop_column("workspace_id")
