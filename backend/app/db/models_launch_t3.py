"""Launch Room delivery tables (migration 0028): Review Links, the decisions reviewers leave, and Asset Packs.

A review link is a bearer secret: only the SHA-256 of its token is stored, with an expiry and an optional revocation.
Its scope is a list of (version, region) pairs of one campaign; a reviewer can reach nothing else. A reviewer's decision
is a `review_responses` row, kept apart from `approvals` (which only a signed-in workspace member can record): a stakeholder
decision informs the people who approve, it never approves for them. Responses are append-only.

An Asset Pack is a ZIP built on the server for one region and the approved version, stored like a Proof export (the bytes
sit in the blob store, or in this row when ASSET_STORAGE_BACKEND=database) and served through an expiring download link
whose token is stored only as a hash. The manifest, with every file's checksum and provenance, is kept on the row.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

REVIEW_DECISIONS = "'approve', 'request_changes', 'reject', 'comment'"


class ReviewLink(Base):
    __tablename__ = "review_links"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    label: Mapped[str]
    note: Mapped[str | None]  # a message from the sender, shown to the reviewer
    items: Mapped[list]  # [{"version_id": str, "region_code": str}]: the only things the link can show or accept decisions on
    token_hash: Mapped[str] = mapped_column(unique=True)
    token_hint: Mapped[str]  # the last 4 characters of the token, so the owner can tell links apart
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    revoked_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    mode: Mapped[str]
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"]),
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        Index("ix_review_links_campaign_id_created_at", "campaign_id", "created_at"),
    )


class ReviewResponse(Base):
    """A decision or comment from a reviewer, recorded against one version in one region. `reviewer_kind` says whether the
    reviewer gave a name; the name is self-declared and never verified."""

    __tablename__ = "review_responses"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    link_id: Mapped[UUID] = mapped_column(ForeignKey("review_links.id"))
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    version_id: Mapped[UUID]
    region_code: Mapped[str]
    decision: Mapped[str]
    comment: Mapped[str | None]
    reviewer_name: Mapped[str | None]
    reviewer_kind: Mapped[str]
    mode: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"]),
        ForeignKeyConstraint(["version_id", "campaign_id"], ["version_nodes.id", "version_nodes.campaign_id"], ondelete="RESTRICT"),
        CheckConstraint(f"decision IN ({REVIEW_DECISIONS})", name="decision"),
        CheckConstraint("reviewer_kind IN ('named', 'anonymous')", name="reviewer_kind"),
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        Index("ix_review_responses_link_id_created_at", "link_id", "created_at"),
        Index("ix_review_responses_campaign_id_version_id", "campaign_id", "version_id"),
    )


class AssetPack(Base):
    __tablename__ = "asset_packs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    region_code: Mapped[str]
    version_id: Mapped[UUID]
    approval_id: Mapped[UUID] = mapped_column(ForeignKey("approvals.id"))  # the human decision that makes the version packable
    filename: Mapped[str]
    byte_size: Mapped[int]
    sha256: Mapped[str]
    file_count: Mapped[int]
    storage_key: Mapped[str]
    data: Mapped[bytes | None] = mapped_column(LargeBinary)  # only for ASSET_STORAGE_BACKEND=database
    manifest: Mapped[dict]
    token_hash: Mapped[str] = mapped_column(unique=True)
    expires_at: Mapped[datetime]
    mode: Mapped[str]
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"]),
        ForeignKeyConstraint(["version_id", "campaign_id"], ["version_nodes.id", "version_nodes.campaign_id"], ondelete="RESTRICT"),
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        Index("ix_asset_packs_campaign_id_created_at", "campaign_id", "created_at"),
    )
