"""Settings tables (migration 0022): workspace invites and per-workspace settings.

`workspace_invites` is a stored record only. Nothing is emailed in this build: the owner is shown the invite code once
and shares it themselves. Only a SHA-256 hash of the code is stored, so a database read never yields a usable code.
An invite is single use, expires after a fixed time, and can be revoked. `expired` is written lazily; a pending invite
whose `expires_at` has passed is read as expired everywhere.

`workspace_settings` holds the settings a workspace owner edits beyond its name (which stays on `workspaces`): the default
regions for new campaigns. Membership and roles live in `workspace_members` (identity and tenancy, models_omnicult).
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

INVITE_STATUSES = ("pending", "accepted", "revoked", "expired")


class WorkspaceInvite(Base):
    __tablename__ = "workspace_invites"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    email: Mapped[str]  # lower-case; the address the owner meant the invite for
    role: Mapped[str]
    code_hash: Mapped[str] = mapped_column(unique=True)  # sha256 hex of the code; the code itself is never stored
    status: Mapped[str] = mapped_column(default="pending")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    accepted_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    accepted_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint("role IN ('owner', 'editor', 'reviewer', 'viewer')", name="role"),
        CheckConstraint("status IN ('pending', 'accepted', 'revoked', 'expired')", name="status"),
        Index(  # one open invite per address and workspace
            "uq_workspace_invites_workspace_id_email_pending", "workspace_id", "email", unique=True,
            sqlite_where=text("status = 'pending'"), postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_workspace_invites_workspace_id_created_at", "workspace_id", "created_at"),
    )


class WorkspaceSettings(Base):
    __tablename__ = "workspace_settings"

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    default_region_codes: Mapped[list] = mapped_column(default=list)  # ISO 3166-2 codes, validated against `regions`
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
