"""Comment Pulse and Weekly Digest tables (migration 0030).

`pulse_comments` holds the labelled sample comments of a campaign (one row per comment, stable `ref`); `source_kind`
keeps the sample apart from comments of a future connected channel, and queries always filter by it. A comment's
sentiment and themes are NOT stored here: they are a model interpretation, kept with the analysis that produced them
(`pulse_comment_analyses`: prompt version, model, labels by comment ref, themes), so a stored read always says who made it.

`pulse_digests` stores one weekly digest per campaign and ISO week: the numbers and lists computed by code (`content`),
a hash of that content, and an optional model-written summary (`narrative`) that is kept apart from it. Regenerating a
week replaces the row and bumps `revision`.

Every row is scoped through (campaign_id, project_id) -> campaigns, so a row can never point at another project's campaign.
"""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

SOURCE_KINDS = ("sample", "test_account", "live")
ANALYSIS_STATUSES = ("completed", "partial")
DIGEST_TRIGGERS = ("manual", "scheduler")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _campaign_key() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"], ondelete="RESTRICT")


class PulseComment(Base):
    __tablename__ = "pulse_comments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID]
    ref: Mapped[str]  # stable id inside the dataset, for example cm-0007; the model sees refs, never database ids
    day: Mapped[date]
    platform: Mapped[str]
    region_code: Mapped[str]
    version_label: Mapped[str]  # a Live Pulse version label exactly as the metric series lists it
    language: Mapped[str]  # ISO 639-1 of the main language
    script: Mapped[str]  # ISO 15924: Deva, Taml, Mlym, Beng or Latn
    code_mixed: Mapped[bool] = mapped_column(default=False)
    text: Mapped[str]
    likes: Mapped[int] = mapped_column(default=0)
    source_kind: Mapped[str]
    dataset_version: Mapped[str]
    last_updated_at: Mapped[datetime]

    __table_args__ = (
        _campaign_key(),
        UniqueConstraint("campaign_id", "source_kind", "ref"),
        CheckConstraint(f"source_kind IN ({_in(SOURCE_KINDS)})", name="source_kind"),
        CheckConstraint("likes >= 0", name="likes"),
        Index("ix_pulse_comments_campaign_id_source_kind_region_code_day", "campaign_id", "source_kind", "region_code", "day"),
    )


class CommentAnalysis(Base):
    """One model reading of a campaign's comments. Append-only; the newest row for the dataset is the one shown."""

    __tablename__ = "pulse_comment_analyses"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID]
    dataset_version: Mapped[str]
    mode: Mapped[str]  # demo = fixture responder, live = the model gateway
    status: Mapped[str]
    prompt_version: Mapped[str]
    provider: Mapped[str]
    model_id: Mapped[str | None]
    estimated_cost_usd: Mapped[float | None]
    comment_count: Mapped[int]  # comments sent
    read_count: Mapped[int]  # comments with a valid label after code checks
    dropped: Mapped[dict] = mapped_column(default=dict)  # what the code checks removed, by reason
    labels: Mapped[dict]  # ref -> {"sentiment": ..., "themes": [theme ids]}
    themes: Mapped[list]  # [{"id", "label", "summary"}]
    notes: Mapped[list] = mapped_column(default=list)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _campaign_key(),
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        CheckConstraint(f"status IN ({_in(ANALYSIS_STATUSES)})", name="status"),
        Index("ix_pulse_comment_analyses_campaign_id_created_at", "campaign_id", "created_at"),
    )


class PulseDigest(Base):
    __tablename__ = "pulse_digests"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID]
    iso_year: Mapped[int]
    iso_week: Mapped[int]
    week_start: Mapped[date]
    week_end: Mapped[date]
    revision: Mapped[int] = mapped_column(default=1)
    mode: Mapped[str]
    trigger: Mapped[str]
    content: Mapped[dict]  # DigestContent, computed by code from stored records
    content_sha256: Mapped[str]
    narrative: Mapped[dict | None]  # the optional model summary: text plus model metadata; never part of `content`
    generated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    generated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _campaign_key(),
        UniqueConstraint("campaign_id", "iso_year", "iso_week"),
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        CheckConstraint(f"trigger IN ({_in(DIGEST_TRIGGERS)})", name="trigger"),
        CheckConstraint("iso_week BETWEEN 1 AND 53", name="iso_week"),
        CheckConstraint("revision >= 1", name="revision"),
        Index("ix_pulse_digests_campaign_id_week_start", "campaign_id", "week_start"),
    )
