"""Comment Pulse and Weekly Digest tables (migration 0030; YouTube comments, migration 0031).

`pulse_comments` holds the comments of a campaign (one row per comment, stable `ref`): the labelled sample, or the public
comments of a YouTube video (`source_kind = 'youtube'`, with the video id, the YouTube comment id, the time it was published
and its reply count; never a name, channel id or avatar). `source_kind` keeps the sources apart and queries always filter by
it. `pulse_youtube_sources` records which video was fetched for which campaign version and region. A comment's
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

SOURCE_KINDS = ("sample", "test_account", "live", "youtube")
ANALYSIS_SOURCES = ("sample", "youtube")
YOUTUBE_ORDERS = ("relevance", "time")
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
    video_id: Mapped[str | None]  # youtube rows: the 11-character video id
    external_id: Mapped[str | None]  # youtube rows: the YouTube comment id (a re-fetch updates the row with the same id)
    published_at: Mapped[datetime | None]  # youtube rows: when the comment was posted (`day` is its UTC date)
    reply_count: Mapped[int | None]  # youtube rows: replies under the comment (replies themselves are not stored)

    __table_args__ = (
        _campaign_key(),
        UniqueConstraint("campaign_id", "source_kind", "ref"),
        UniqueConstraint("campaign_id", "source_kind", "external_id"),
        CheckConstraint(f"source_kind IN ({_in(SOURCE_KINDS)})", name="source_kind"),
        CheckConstraint("likes >= 0", name="likes"),
        CheckConstraint("reply_count IS NULL OR reply_count >= 0", name="reply_count"),
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
    source_kind: Mapped[str] = mapped_column(default="sample", server_default="sample")  # which comments were read
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
        CheckConstraint(f"source_kind IN ({_in(ANALYSIS_SOURCES)})", name="source_kind"),
        Index("ix_pulse_comment_analyses_campaign_id_created_at", "campaign_id", "created_at"),
    )


class YoutubeSource(Base):
    """The YouTube video whose public comments were fetched for one campaign version and region (one video per slice)."""

    __tablename__ = "pulse_youtube_sources"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID]
    video_id: Mapped[str]
    video_title: Mapped[str | None]
    version_label: Mapped[str]
    region_code: Mapped[str]
    comment_order: Mapped[str]
    pages_fetched: Mapped[int]
    truncated: Mapped[bool]  # the page cap stopped the last fetch while YouTube had more comments
    fetched_at: Mapped[datetime]  # the last fetch; a video is not fetched again before the configured interval
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        _campaign_key(),
        UniqueConstraint("campaign_id", "video_id"),
        UniqueConstraint("campaign_id", "version_label", "region_code"),
        CheckConstraint(f"comment_order IN ({_in(YOUTUBE_ORDERS)})", name="comment_order"),
        CheckConstraint("pages_fetched >= 1", name="pages_fetched"),
        Index("ix_pulse_youtube_sources_video_id", "video_id"),
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
