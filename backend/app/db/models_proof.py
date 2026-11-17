"""Proof Vault tables (migration 0017): versioned Proof Report snapshots and their stored exports.

A snapshot is immutable: a new report for the same campaign gets the next `version_number`; nothing is updated in place.
Export bytes live in the blob store (`app.db.blobs`); the row keeps them only when ASSET_STORAGE_BACKEND=database
(tests and local development). A download link is a random token whose hash is stored with an expiry.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, LargeBinary, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ProofReport(Base):
    __tablename__ = "proof_reports"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID]
    workspace_id: Mapped[UUID | None] = mapped_column(ForeignKey("workspaces.id"))
    campaign_version_id: Mapped[UUID | None]
    version_number: Mapped[int]
    title: Mapped[str]
    status: Mapped[str]
    mode: Mapped[str]
    content_sha256: Mapped[str]
    content: Mapped[dict]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"]),
        UniqueConstraint("campaign_id", "version_number"),
        CheckConstraint("status IN ('complete', 'partial')", name="status"),
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        Index("ix_proof_reports_project_id_created_at", "project_id", "created_at"),
    )


class ProofReportExport(Base):
    __tablename__ = "proof_report_exports"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    report_id: Mapped[UUID] = mapped_column(ForeignKey("proof_reports.id"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    format: Mapped[str]
    filename: Mapped[str]
    content_type: Mapped[str]
    byte_size: Mapped[int]
    sha256: Mapped[str]
    storage_key: Mapped[str]
    data: Mapped[bytes | None] = mapped_column(LargeBinary)  # only for ASSET_STORAGE_BACKEND=database
    token_hash: Mapped[str]
    expires_at: Mapped[datetime]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint("format IN ('json', 'markdown', 'pdf')", name="format"),
        Index("ix_proof_report_exports_report_id", "report_id"),
    )
