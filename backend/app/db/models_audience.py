"""Audience Lab tables (migration 0015): runs, synthetic panel participants, Ask the Panel questions and answers, and Risk
Check findings. Re-exported by `app.db.models`, so `m.AudienceRun`, `m.PanelParticipant`, ... work.

Audience Lab runs keep their own lifecycle (queued, running, completed, partial, failed) in `audience_runs`; they do not
use `agent_runs`. Creative elements, scenes and version nodes are held as JSON and an opaque `version_ref`: there is no
foreign key to a media or version table. Every participant row is synthetic by constraint.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

RUN_KINDS = "'quick_read', 'audience_study', 'risk_check'"
RUN_STATUSES = "'queued', 'running', 'completed', 'partial', 'failed', 'cancelled'"
FINDING_STATUSES = "'open', 'accepted', 'dismissed', 'fixed'"


class AudienceRun(Base):
    """One Quick Read, Audience Study or Risk Check. `inputs` is the snapshot the workflow ran on (claims as they stood,
    the creative, the panel); `config` is the request as sent."""

    __tablename__ = "audience_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID]
    kind: Mapped[str]
    status: Mapped[str] = mapped_column(default="queued")
    mode: Mapped[str]
    region_codes: Mapped[list] = mapped_column(default=list)
    content_version_id: Mapped[UUID | None]  # a campaign content version; no foreign key by design
    version_ref: Mapped[str | None]  # opaque reference to a version node (Creative Studio); stored, never joined
    seed: Mapped[int | None]
    config: Mapped[dict] = mapped_column(default=dict)
    inputs: Mapped[dict] = mapped_column(default=dict)
    result: Mapped[dict | None]
    progress: Mapped[dict | None]
    steps: Mapped[list] = mapped_column(default=list)
    usage: Mapped[dict | None]
    error: Mapped[dict | None]
    limitations: Mapped[list] = mapped_column(default=list)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    lease_expires_at: Mapped[datetime | None]  # a run past its lease is reclaimed as interrupted

    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"]),
        CheckConstraint(f"kind IN ({RUN_KINDS})", name="kind"),
        CheckConstraint(f"status IN ({RUN_STATUSES})", name="status"),
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        Index("ix_audience_runs_campaign_id_kind_created_at", "campaign_id", "kind", "created_at"),
        Index("ix_audience_runs_project_id_created_at", "project_id", "created_at"),
        Index("ix_audience_runs_status", "status"),
        Index("uq_audience_runs_created_by_idempotency_key", "created_by", "idempotency_key", unique=True),
    )


class PanelParticipant(Base):
    """A synthetic panel member. The sampling dimensions are the persona; `response` holds the stored Quick Read response
    or Audience Study interview, which Ask the Panel later reads as the participant's memory."""

    __tablename__ = "audience_participants"

    id: Mapped[UUID] = mapped_column(primary_key=True)  # stable: uuid5 of the run id and ordinal
    run_id: Mapped[UUID] = mapped_column(ForeignKey("audience_runs.id"))
    ordinal: Mapped[int]
    state_code: Mapped[str]
    state_name: Mapped[str]
    language: Mapped[str]
    language_name: Mapped[str]
    city_tier: Mapped[str]
    age_band: Mapped[str]
    traits: Mapped[dict] = mapped_column(default=dict)
    persona: Mapped[str]
    response: Mapped[dict | None]
    is_synthetic: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (
        UniqueConstraint("run_id", "ordinal"),
        CheckConstraint("is_synthetic", name="synthetic"),
        CheckConstraint("city_tier IN ('tier1', 'tier2', 'tier3', 'rural')", name="city_tier"),
        CheckConstraint("age_band IN ('18-24', '25-34', '35-44', '45-54', '55+')", name="age_band"),
        Index("ix_audience_participants_run_id_ordinal", "run_id", "ordinal"),
    )


class PanelQuestion(Base):
    """One Ask the Panel question and how it was targeted. Answers are in `panel_answers`."""

    __tablename__ = "audience_questions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("audience_runs.id"))
    asked_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    target_kind: Mapped[str]
    target: Mapped[dict]
    question: Mapped[str]
    summaries: Mapped[list] = mapped_column(default=list)
    stance: Mapped[dict]
    unanswered: Mapped[list] = mapped_column(default=list)
    mode: Mapped[str]
    limitations: Mapped[list] = mapped_column(default=list)
    usage: Mapped[dict | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint("target_kind IN ('participant', 'subgroup', 'panel')", name="target_kind"),
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        Index("ix_audience_questions_run_id_created_at", "run_id", "created_at"),
    )


class PanelAnswer(Base):
    __tablename__ = "audience_answers"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    question_id: Mapped[UUID] = mapped_column(ForeignKey("audience_questions.id"))
    run_id: Mapped[UUID] = mapped_column(ForeignKey("audience_runs.id"))
    participant_id: Mapped[UUID] = mapped_column(ForeignKey("audience_participants.id"))
    answer: Mapped[str]
    stance: Mapped[str | None]
    memory_refs: Mapped[list] = mapped_column(default=list)
    model_id: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        Index("ix_audience_answers_question_id", "question_id"),
        Index("ix_audience_answers_participant_id_created_at", "participant_id", "created_at"),
    )


class RiskFindingRow(Base):
    """One Risk Check finding. Severity and blocks_go are computed by risk-rules-v1 (`severity_rules` says how); status is
    the only field a person changes."""

    __tablename__ = "audience_risk_findings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("audience_runs.id"))
    ordinal: Mapped[int]
    element_id: Mapped[str]
    category: Mapped[str]
    severity: Mapped[str]
    blocks_go: Mapped[bool] = mapped_column(default=False)
    confidence_label: Mapped[str]
    anchor: Mapped[dict]
    quote: Mapped[str | None]
    quote_start: Mapped[int | None]
    quote_end: Mapped[int | None]
    verification: Mapped[str]
    observation: Mapped[str]
    interpretation: Mapped[str]
    suggested_fix: Mapped[str | None]
    ad_codes: Mapped[list] = mapped_column(default=list)  # snapshot of the cited index entries
    claim_ids: Mapped[list] = mapped_column(default=list)
    source: Mapped[str]
    severity_rules: Mapped[list] = mapped_column(default=list)
    rules_version: Mapped[str]
    status: Mapped[str] = mapped_column(default="open")
    status_reason: Mapped[str | None]
    status_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    status_at: Mapped[datetime | None]
    limitations: Mapped[list] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "ordinal"),
        CheckConstraint("severity IN ('low', 'medium', 'high')", name="severity"),
        CheckConstraint(f"status IN ({FINDING_STATUSES})", name="status"),
        CheckConstraint("source IN ('deterministic_check', 'model_assessment')", name="source"),
        CheckConstraint("verification IN ('quote_verified', 'element_reference', 'deterministic')", name="verification"),
        Index("ix_audience_risk_findings_run_id_status", "run_id", "status"),
    )

