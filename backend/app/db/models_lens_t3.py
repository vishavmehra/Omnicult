"""Market Lens Tier 3 tables (migration 0025): retained snapshots of Trend Radar series and Category Shelf discoveries.

A `LensTrendBatch` is one refresh; it names the states asked for and what could not be read. A `LensTrendSnapshot` is one retrieval of one article's monthly pageviews for one region and term, kept so the radar can
say how the direction read last time. The series is stored as retrieved; the direction is recomputed from it by
`app.analytics.lens_trends` whenever it is read, so a snapshot never holds a stale label. Snapshots are never edited or
overwritten, and a `batch_id` ties together the snapshots one refresh took.

A `LensShelfSnapshot` is one saved category discovery (the brands and products Wikidata records for a category pack, with
what was left out and why), versioned per workspace, mode and pack.
"""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class LensTrendBatch(Base):
    """One Trend Radar refresh: when, in which mode, for which states, and what could not be read."""

    __tablename__ = "lens_trend_batches"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("campaigns.id"))
    mode: Mapped[str]
    category_text: Mapped[str | None]
    pack_key: Mapped[str | None]
    regions: Mapped[dict]  # region_code -> {"asked": n, "read": n, "gaps": [str]}
    window_start: Mapped[date]
    window_end: Mapped[date]
    method_version: Mapped[str]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    taken_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        Index("ix_lens_trend_batches_workspace_id_mode_taken_at", "workspace_id", "mode", "taken_at"),
    )


class LensTrendSnapshot(Base):
    __tablename__ = "lens_trend_snapshots"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("campaigns.id"))
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("lens_trend_batches.id"))  # the refresh that took this snapshot
    mode: Mapped[str]  # live | demo
    region_code: Mapped[str]
    term: Mapped[str]  # English Wikipedia title or a Wikidata Q-id, as passed to the pageviews source
    term_kind: Mapped[str]  # festival | category
    label: Mapped[str]
    festival_subject: Mapped[str | None]  # the festival claim subject, to link a moment to its attention
    granularity: Mapped[str]
    window_start: Mapped[date]
    window_end: Mapped[date]
    method_version: Mapped[str]  # the method that was current when this was taken; the read always recomputes
    editions: Mapped[list]  # [{language, project, article, points: [[YYYY-MM, views]]}]
    source: Mapped[dict]  # {url, title, publisher, source_identifier, retrieved_at}
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    taken_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        CheckConstraint("term_kind IN ('festival', 'category')", name="term_kind"),
        Index("ix_lens_trend_snapshots_workspace_id_mode_region_code_term", "workspace_id", "mode", "region_code", "term"),
        Index("ix_lens_trend_snapshots_batch_id", "batch_id"),
    )


class LensShelfSnapshot(Base):
    __tablename__ = "lens_shelf_snapshots"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("campaigns.id"))
    mode: Mapped[str]
    pack_key: Mapped[str]
    category_text: Mapped[str | None]
    version: Mapped[int]  # 1, 2, ... per workspace, mode and pack
    discovery: Mapped[dict]  # the ShelfDiscovery as retrieved
    attention: Mapped[dict]  # entity_id -> {region_code, editions: [...], source: {...}}; only for entities that were read
    gaps: Mapped[list]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    taken_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("workspace_id", "mode", "pack_key", "version"),
        CheckConstraint("mode IN ('live', 'demo')", name="mode"),
        Index("ix_lens_shelf_snapshots_workspace_id_mode_pack_key", "workspace_id", "mode", "pack_key"),
    )


class LensSearchPulse(Base):
    """Search pulse (migration 0034): one row per state, kind, term and week of Google's public search-interest lists, as BigQuery
    returned them. Public data shared by every workspace; demo reads a recorded file instead. A refresh replaces a state's rows
    (each carries the refresh_date, retrieval time, BigQuery job id and bytes processed it came from)."""

    __tablename__ = "lens_search_pulse"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    region_code: Mapped[str]  # Omnicult code, e.g. IN-CG (the dataset says IN-CT)
    kind: Mapped[str]  # top | rising
    term: Mapped[str]
    week: Mapped[date]  # the Sunday starting the week
    rank: Mapped[int | None]
    score: Mapped[int | None]  # 0 to 100, null where Google reported none
    percent_gain: Mapped[int | None]  # rising terms only
    refresh_date: Mapped[date]  # the dataset partition read
    retrieved_at: Mapped[datetime] = mapped_column(default=utcnow)
    job_id: Mapped[str | None]
    bytes_processed: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint("region_code", "kind", "term", "week"),
        CheckConstraint("kind IN ('top', 'rising')", name="kind"),
    )
