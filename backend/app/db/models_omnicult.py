"""Omnicult tables added after the NativeProof schema (migrations 0007+): identity and tenancy, reference data,
evidence (claims, conflicts), and metering. Re-exported by `app.db.models`, so `m.User`, `m.Claim`, ... work.

Tenancy: a workspace is the tenant. `projects.workspace_id` places every project (and through it every child row) in
one workspace; new top-level tables carry `workspace_id` themselves. Reference tables (languages, regions, country
packs, moments) and shared claims (`claims.workspace_id IS NULL`) belong to nobody and are read-only to users.
Row Level Security is deliberately not used (M-07): the API authorizes every request (services.common, services.identity);
migration 0012 switches off the unusable RLS left by 0002-0005 on plain Postgres.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, utcnow

WORKSPACE_ROLES = ("owner", "editor", "reviewer", "viewer")
CLAIM_KINDS = "'observed', 'calculated', 'synthetic', 'interpretation', 'unverified'"
CLAIM_CATEGORIES = (
    "'language', 'script', 'festival', 'moment', 'food', 'colour', 'symbol', 'humour', 'family', 'custom', "
    "'sensitivity', 'trend', 'demographic', 'media'"
)
CLAIM_STATUSES = "'active', 'needs_review', 'rejected', 'superseded'"
CONFLICT_STATUSES = "'open', 'review_requested', 'resolved'"


# --- identity and tenancy -----------------------------------------------------------------


class User(Base):
    """An application user. `firebase_uid` is NULL for development users and for users created before they first sign in."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    firebase_uid: Mapped[str | None] = mapped_column(unique=True)
    email: Mapped[str | None]
    display_name: Mapped[str | None]
    is_anonymous: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str]
    kind: Mapped[str] = mapped_column(default="personal")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint("kind IN ('personal', 'team')", name="kind"),
        Index(  # one personal workspace per user, even when two first requests race
            "uq_workspaces_created_by_personal", "created_by", unique=True,
            sqlite_where=text("kind = 'personal'"), postgresql_where=text("kind = 'personal'"),
        ),
    )


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id"),
        CheckConstraint("role IN ('owner', 'editor', 'reviewer', 'viewer')", name="role"),
        Index("ix_workspace_members_user_id", "user_id"),
    )


# --- reference data (seeded by scripts.seed_reference_data, never by a schema migration) ---


class Language(Base):
    __tablename__ = "languages"

    code: Mapped[str] = mapped_column(primary_key=True)  # ISO 639-1; ISO 639-3 where no two-letter code exists
    name: Mapped[str]
    native_name: Mapped[str | None]
    script: Mapped[str]  # ISO 15924
    direction: Mapped[str] = mapped_column(default="ltr")
    code_standard: Mapped[str] = mapped_column(default="iso639-1")
    is_active: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (
        CheckConstraint("direction IN ('ltr', 'rtl')", name="direction"),
        CheckConstraint("code_standard IN ('iso639-1', 'iso639-3')", name="code_standard"),
    )


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)  # stable: uuid5 of the code (app.reference.india)
    country_code: Mapped[str]
    code: Mapped[str] = mapped_column(unique=True)  # ISO 3166-2, e.g. IN-TN
    name: Mapped[str]
    kind: Mapped[str]
    primary_language_code: Mapped[str | None] = mapped_column(ForeignKey("languages.code"))
    primary_script: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint("kind IN ('state', 'union_territory')", name="kind"),
        Index("ix_regions_country_code_name", "country_code", "name"),
    )


class CountryPack(Base):
    __tablename__ = "country_packs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    country_code: Mapped[str]
    version: Mapped[str]
    pack: Mapped[dict]
    source: Mapped[str]
    published_at: Mapped[date | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (UniqueConstraint("country_code", "version"),)


class RegionLanguageProfile(Base):
    __tablename__ = "region_language_profiles"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    region_id: Mapped[UUID] = mapped_column(ForeignKey("regions.id"))
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"))
    role: Mapped[str]
    script: Mapped[str]
    notes: Mapped[str | None]

    __table_args__ = (
        UniqueConstraint("region_id", "language_code"),
        CheckConstraint("role IN ('primary', 'secondary', 'code_mixed')", name="role"),
    )


class RegionalMoment(Base):
    """A recurring festival or season. Exact dates for a year come from a dated claim, not from this row."""

    __tablename__ = "regional_moments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    region_id: Mapped[UUID | None] = mapped_column(ForeignKey("regions.id"))  # NULL = national
    country_code: Mapped[str]
    slug: Mapped[str]
    name: Mapped[str]
    kind: Mapped[str]
    recurrence: Mapped[str] = mapped_column(default="annual")
    typical_months: Mapped[list]
    calendar: Mapped[str]
    notes: Mapped[str | None]
    starts_on: Mapped[date | None]
    ends_on: Mapped[date | None]

    __table_args__ = (
        UniqueConstraint("country_code", "slug", "region_id"),
        CheckConstraint("kind IN ('festival', 'holiday', 'season', 'event')", name="kind"),
        CheckConstraint("calendar IN ('solar', 'lunisolar', 'civil')", name="calendar"),
    )


# --- evidence -----------------------------------------------------------------------------


class Claim(Base):
    """One statement with its five tags: source (claim_sources), date, kind, scope, confidence.

    `claim_key` identifies a statement (workspace, subject, attribute, scope, value) so that a repeated retrieval adds
    a source to the same claim instead of duplicating it. Confidence is computed from the sources, never stored from
    a source or a model.
    """

    __tablename__ = "claims"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(ForeignKey("workspaces.id"))  # NULL = shared reference claim
    region_id: Mapped[UUID | None] = mapped_column(ForeignKey("regions.id"))
    claim_key: Mapped[str] = mapped_column(unique=True)
    subject: Mapped[str]
    attribute: Mapped[str]
    category: Mapped[str]
    value: Mapped[Any] = mapped_column(JSONType)
    value_text: Mapped[str]
    scope: Mapped[dict]
    kind: Mapped[str]
    confidence: Mapped[str]
    confidence_reason: Mapped[str]
    published_at: Mapped[date | None]
    retrieved_at: Mapped[datetime]
    expires_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(default="active")
    mode: Mapped[str] = mapped_column(default="live")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint(f"kind IN ({CLAIM_KINDS})", name="kind"),
        CheckConstraint(f"category IN ({CLAIM_CATEGORIES})", name="category"),
        CheckConstraint("confidence IN ('low', 'moderate', 'high')", name="confidence"),
        CheckConstraint(f"status IN ({CLAIM_STATUSES})", name="status"),
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        Index("ix_claims_region_id_category", "region_id", "category"),
        Index("ix_claims_workspace_id_region_id", "workspace_id", "region_id"),
        Index("ix_claims_subject_attribute", "subject", "attribute"),
    )


class ClaimSource(Base):
    __tablename__ = "claim_sources"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id"))
    source_type: Mapped[str]
    source_identifier: Mapped[str]
    url: Mapped[str | None]
    title: Mapped[str | None]
    publisher: Mapped[str | None]
    published_at: Mapped[date | None]
    retrieved_at: Mapped[datetime]
    excerpt: Mapped[str | None]
    independence_group: Mapped[str]

    __table_args__ = (UniqueConstraint("claim_id", "source_type", "source_identifier"),)


class Conflict(Base):
    """Two claims about the same subject, attribute and scope with different values. Both claims are kept."""

    __tablename__ = "conflicts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    region_id: Mapped[UUID | None] = mapped_column(ForeignKey("regions.id"))
    claim_a_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id"))
    claim_b_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id"))
    reason: Mapped[str]
    current_selection: Mapped[str]  # 'a' or 'b': the value used while the conflict is open, and after a decision
    selection_reason: Mapped[str]
    status: Mapped[str] = mapped_column(default="open")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("workspace_id", "claim_a_id", "claim_b_id"),
        CheckConstraint("current_selection IN ('a', 'b')", name="current_selection"),
        CheckConstraint(f"status IN ({CONFLICT_STATUSES})", name="status"),
        Index("ix_conflicts_workspace_id_status", "workspace_id", "status"),
    )


class ConflictResolution(Base):
    """A reviewer's decision on a conflict. Append-only: the history is the record."""

    __tablename__ = "conflict_resolutions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conflict_id: Mapped[UUID] = mapped_column(ForeignKey("conflicts.id"))
    decided_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str]
    selection_after: Mapped[str]
    note: Mapped[str | None]
    decided_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint("decision IN ('accept', 'switch', 'request_review')", name="decision"),
        CheckConstraint("selection_after IN ('a', 'b')", name="selection_after"),
        Index("ix_conflict_resolutions_conflict_id_decided_at", "conflict_id", "decided_at"),
    )


# --- metering and audit -------------------------------------------------------------------


class AiUsageEvent(Base):
    """One model or capability call. Costs are estimates from the registry price table, never provider invoices."""

    __tablename__ = "ai_usage_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID | None] = mapped_column(ForeignKey("campaigns.id"))
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_runs.id"))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    capability: Mapped[str]
    provider: Mapped[str]
    model: Mapped[str]
    prompt_version: Mapped[str | None]
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    thinking_tokens: Mapped[int] = mapped_column(default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(default=0.0)
    latency_ms: Mapped[int | None]
    status: Mapped[str] = mapped_column(default="ok")
    error_code: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        Index("ix_ai_usage_events_workspace_id_created_at", "workspace_id", "created_at"),
        Index("ix_ai_usage_events_run_id", "run_id"),
        Index("ix_ai_usage_events_user_id_created_at", "user_id", "created_at"),
    )


class AuditLog(Base):
    """Who did what to which record. Append-only. `detail` never holds secrets or personal data beyond ids."""

    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(ForeignKey("workspaces.id"))
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))  # NULL = the system
    action: Mapped[str]
    target_type: Mapped[str]
    target_id: Mapped[str | None]
    detail: Mapped[dict | None]
    request_id: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (Index("ix_audit_log_workspace_id_created_at", "workspace_id", "created_at"),)
