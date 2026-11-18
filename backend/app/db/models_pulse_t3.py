"""Live Pulse Tier 3 tables (migration 0029): saved alert rules and their alert history, the version links and stored
comparison snapshots behind Predicted vs Actual. Fatigue Watch is computed on read and stores nothing.

An alert is one row per (campaign, key): the key names the rule, region, version and metric, so a condition that clears and
returns reopens the same row and its history stays in one place. `pulse_alert_events` is append-only. Evaluations are
recorded per campaign; a scheduled evaluation carries a `period_key`, unique per campaign, which is what makes the
scheduler's call idempotent for a period.
"""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

ALERT_TYPES = ("ctr_drop", "frequency_fatigue", "cost_spike", "prediction_miss")
ALERT_STATUSES = ("open", "acknowledged", "resolved")
ALERT_EVENT_KINDS = ("opened", "acknowledged", "resolved", "reopened")
EVALUATION_TRIGGERS = ("refresh", "manual", "scheduler")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class PulseAlertRule(Base):
    __tablename__ = "pulse_alert_rules"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    name: Mapped[str]
    alert_type: Mapped[str]
    region_code: Mapped[str | None]  # null: every region
    version_label: Mapped[str | None]  # null: every version
    params: Mapped[dict] = mapped_column(default=dict)  # only the thresholds this alert type reads
    enabled: Mapped[bool] = mapped_column(default=True)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"]),
        CheckConstraint(f"alert_type IN ({_in(ALERT_TYPES)})", name="alert_type"),
        Index("ix_pulse_alert_rules_campaign_id", "campaign_id"),
    )


class PulseAlert(Base):
    __tablename__ = "pulse_alerts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    rule_id: Mapped[UUID | None] = mapped_column(ForeignKey("pulse_alert_rules.id", ondelete="SET NULL"))
    rule_name: Mapped[str]  # kept when the rule is deleted
    alert_key: Mapped[str]
    alert_type: Mapped[str]
    region_code: Mapped[str]
    version_label: Mapped[str]
    metric: Mapped[str]
    threshold: Mapped[float]
    observed_value: Mapped[float]
    comparison_value: Mapped[float]
    comparison: Mapped[str]
    window_from: Mapped[date]
    window_to: Mapped[date]
    suggested_action: Mapped[str]
    source_path: Mapped[str]
    dataset_version: Mapped[str]
    status: Mapped[str] = mapped_column(default="open")
    resolution: Mapped[str | None]  # manual | cleared | rule_removed | rule_disabled
    opened_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    acknowledged_at: Mapped[datetime | None]
    acknowledged_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None]
    resolved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"]),
        UniqueConstraint("campaign_id", "alert_key"),
        CheckConstraint(f"alert_type IN ({_in(ALERT_TYPES)})", name="alert_type"),
        CheckConstraint(f"status IN ({_in(ALERT_STATUSES)})", name="status"),
        Index("ix_pulse_alerts_campaign_id_status", "campaign_id", "status"),
    )


class PulseAlertEvent(Base):
    """What happened to an alert and when. `actor_user_id` is null for the system (an evaluation)."""

    __tablename__ = "pulse_alert_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    alert_id: Mapped[UUID] = mapped_column(ForeignKey("pulse_alerts.id", ondelete="CASCADE"))
    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("campaigns.id"))
    at: Mapped[datetime] = mapped_column(default=utcnow)
    kind: Mapped[str]
    trigger: Mapped[str]  # refresh | manual | scheduler | user
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None]
    observed_value: Mapped[float | None]

    __table_args__ = (
        CheckConstraint(f"kind IN ({_in(ALERT_EVENT_KINDS)})", name="kind"),
        Index("ix_pulse_alert_events_alert_id_at", "alert_id", "at"),
    )


class PulseAlertEvaluation(Base):
    """One evaluation of a campaign's rules. `period_key` is set for scheduled runs only and is unique per campaign."""

    __tablename__ = "pulse_alert_evaluations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    trigger: Mapped[str]
    period_key: Mapped[str | None]
    dataset_version: Mapped[str]
    evaluated_at: Mapped[datetime] = mapped_column(default=utcnow)
    rules_evaluated: Mapped[int]
    alerts_found: Mapped[int]
    opened: Mapped[int]
    reopened: Mapped[int]
    resolved: Mapped[int]
    not_evaluated: Mapped[int]  # version and region pairs a rule could not read (reported, never read as "no alert")

    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"]),
        UniqueConstraint("campaign_id", "period_key"),
        CheckConstraint(f"trigger IN ({_in(EVALUATION_TRIGGERS)})", name="trigger"),
        Index("ix_pulse_alert_evaluations_campaign_id_evaluated_at", "campaign_id", "evaluated_at"),
    )


class PulseVersionLink(Base):
    """Which Creative Studio version a Pulse version label ran as in one region: the only way a stored prediction and an
    actual result are paired. A label with no link is never compared."""

    __tablename__ = "pulse_version_links"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    region_code: Mapped[str]
    pulse_version: Mapped[str]
    version_id: Mapped[UUID]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"]),
        ForeignKeyConstraint(["version_id", "campaign_id"], ["version_nodes.id", "version_nodes.campaign_id"], ondelete="RESTRICT"),
        UniqueConstraint("campaign_id", "region_code", "pulse_version"),
    )


class PulseComparisonSnapshot(Base):
    """A stored Predicted vs Actual comparison: the inputs it read, the method version and the result, append-only.
    Identical inputs under the same method give the same fingerprint, and the newest snapshot with it is returned
    instead of a duplicate."""

    __tablename__ = "pulse_comparison_snapshots"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID]
    campaign_id: Mapped[UUID]
    metric: Mapped[str]
    method_version: Mapped[str]
    fingerprint: Mapped[str]
    dataset_version: Mapped[str]
    pair_count: Mapped[int]
    inputs: Mapped[dict]
    result: Mapped[dict]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"]),
        Index("ix_pulse_comparison_snapshots_campaign_id_created_at", "campaign_id", "created_at"),
    )
