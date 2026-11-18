"""Creative Studio tables (migration 0013): the version tree, its operations, locks, Tweak Chips and the Brand Glossary.

A version node is an immutable snapshot of a creative's elements. Nothing here is ever updated in place except a lock
being released and a chip being marked applied: an operation reads a node and writes a NEW node (D-006 applied to
creative elements). Every row is project-scoped (composite foreign keys keep a node, operation or chip inside one
campaign), so workspace access is decided by the same membership helpers as the rest of the API (services.common).
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

OPERATION_KINDS = (
    "'manual_edit', 'replace_text', 'transcreate', 'apply_chip', 'swap_reference', 'change_setting', 'tone_shift', "
    "'restore'"
)
CHIP_STATUSES = "'proposed', 'applied'"


def _fk(columns: list[str], table: str, remote: list[str]) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(columns, [f"{table}.{column}" for column in remote])


class VersionNode(Base):
    """One node of a campaign's creative version tree. `elements` is the full snapshot (CreativeElement list)."""

    __tablename__ = "version_nodes"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID]
    project_id: Mapped[UUID]
    parent_id: Mapped[UUID | None]  # NULL = a root (an imported original)
    label: Mapped[str]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    actor: Mapped[str]  # 'user' or 'ai': who produced the content of this node
    region_code: Mapped[str | None]  # ISO 3166-2, e.g. IN-TN
    language: Mapped[str | None]  # ISO 639-1
    settings: Mapped[dict] = mapped_column(default=dict)  # {"tone": Tone | None, "generation": {...} | None}
    elements: Mapped[list]
    operation_id: Mapped[UUID | None]  # the operation that created this node (NULL for a root)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        _fk(["parent_id", "campaign_id"], "version_nodes", ["id", "campaign_id"]),
        UniqueConstraint("id", "campaign_id"),
        CheckConstraint("actor IN ('user', 'ai')", name="actor"),
        Index("ix_version_nodes_campaign_id_created_at", "campaign_id", "created_at"),
        Index("ix_version_nodes_parent_id", "parent_id"),
    )


class Operation(Base):
    """A requested change to a version. `applied` operations point at the node they created; `rejected` ones (a locked
    element, a failed check) are kept as the audit trail and never produced a node."""

    __tablename__ = "operations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID]
    project_id: Mapped[UUID]
    source_version_id: Mapped[UUID]
    result_version_id: Mapped[UUID | None]
    kind: Mapped[str]
    target_element_ids: Mapped[list] = mapped_column(default=list)
    params: Mapped[dict] = mapped_column(default=dict)
    reason: Mapped[str]
    claim_ids: Mapped[list] = mapped_column(default=list)
    actor: Mapped[str]
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    prompt_version: Mapped[str | None]
    estimated_cost_usd: Mapped[float | None]
    status: Mapped[str]
    rejection: Mapped[dict | None]  # {"code": "LOCKED" | "INVALID" | "CHECKS_FAILED", "message": str, "element_ids": [...]}
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        _fk(["source_version_id", "campaign_id"], "version_nodes", ["id", "campaign_id"]),
        _fk(["result_version_id", "campaign_id"], "version_nodes", ["id", "campaign_id"]),
        CheckConstraint(f"kind IN ({OPERATION_KINDS})", name="kind"),
        CheckConstraint("actor IN ('user', 'ai')", name="actor"),
        CheckConstraint("status IN ('applied', 'rejected')", name="status"),
        CheckConstraint("status <> 'applied' OR result_version_id IS NOT NULL", name="applied_has_version"),
        Index("ix_operations_campaign_id_created_at", "campaign_id", "created_at"),
        Index("ix_operations_source_version_id", "source_version_id"),
    )


class Lock(Base):
    """A lock on one element of a campaign (the element id is stable across versions). Releasing keeps the row:
    every lock change is part of the record."""

    __tablename__ = "locks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID]
    project_id: Mapped[UUID]
    element_id: Mapped[str]
    locked_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None]
    locked_at: Mapped[datetime] = mapped_column(default=utcnow)
    released_at: Mapped[datetime | None]
    released_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        Index(  # one active lock per element
            "uq_locks_campaign_id_element_id_active", "campaign_id", "element_id", unique=True,
            sqlite_where=text("released_at IS NULL"), postgresql_where=text("released_at IS NULL"),
        ),
        Index("ix_locks_campaign_id_locked_at", "campaign_id", "locked_at"),
    )


class Chip(Base):
    """A Tweak Chip: an AI-proposed, evidence-linked change to one element. Applying it runs an `apply_chip` operation."""

    __tablename__ = "chips"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID]
    project_id: Mapped[UUID]
    version_id: Mapped[UUID]  # the version the chip was proposed for
    element_id: Mapped[str]
    title: Mapped[str]
    operation_type: Mapped[str]  # 'replace_text' or 'swap_reference': how the engine applies it
    change: Mapped[dict]  # the proposed change, e.g. {"value": "..."} or {"from_text": "...", "to_text": "..."}
    params: Mapped[dict] = mapped_column(default=dict)  # what the model was asked for: region_code, language
    reason: Mapped[str]
    claim_ids: Mapped[list] = mapped_column(default=list)
    expected_effect: Mapped[str]
    reversible: Mapped[bool] = mapped_column(default=True)
    estimated_cost_usd: Mapped[float | None]
    prompt_version: Mapped[str | None]
    provider: Mapped[str | None]
    model_id: Mapped[str | None]
    status: Mapped[str] = mapped_column(default="proposed")
    applied_operation_id: Mapped[UUID | None] = mapped_column(ForeignKey("operations.id", ondelete="RESTRICT"))
    applied_version_id: Mapped[UUID | None]  # with campaign_id: version_nodes (migration 0021)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _fk(["campaign_id", "project_id"], "campaigns", ["id", "project_id"]),
        _fk(["version_id", "campaign_id"], "version_nodes", ["id", "campaign_id"]),
        ForeignKeyConstraint(["applied_version_id", "campaign_id"], ["version_nodes.id", "version_nodes.campaign_id"], ondelete="RESTRICT"),
        CheckConstraint("operation_type IN ('replace_text', 'swap_reference')", name="operation_type"),
        CheckConstraint(f"status IN ({CHIP_STATUSES})", name="status"),
        Index("ix_chips_campaign_id_version_id", "campaign_id", "version_id"),
    )


class GlossaryTerm(Base):
    """One Brand Glossary entry: a term, in one target language and script. `language` is an ISO 639-1 code or '*'
    (every language). A protected or never-translate term must survive transcreation; a prohibited alternative must not
    appear (both are checked in code on the regional copy and on its English back-translation)."""

    __tablename__ = "glossary_terms"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    term: Mapped[str]  # the original term, as written in the source copy
    term_key: Mapped[str]  # casefolded `term`, for uniqueness and lookup
    language: Mapped[str] = mapped_column(default="*")
    script: Mapped[str | None]  # ISO 15924 of `approved_spelling`
    approved_spelling: Mapped[str | None]  # the brand-approved spelling in this language and script
    preferred_translation: Mapped[str | None]
    pronunciation: Mapped[str | None]
    protected: Mapped[bool] = mapped_column(default=False)
    never_translate: Mapped[bool] = mapped_column(default=False)
    prohibited_alternatives: Mapped[list] = mapped_column(default=list)
    notes: Mapped[str | None]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "term_key", "language"),
        Index("ix_glossary_terms_project_id_language", "project_id", "language"),
    )

