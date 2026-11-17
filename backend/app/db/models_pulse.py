"""Live Pulse tables (migration 0018): platform connections and the metric series behind the regional dashboard.

`metric_series` is the long format used by ad platforms' reports: one row per date, platform, channel, version, region
and base metric. Calculated metrics (CTR, CPM, ...) are never stored; they are computed in code from sums of base
metrics (app.services.pulse_metrics). `source_kind` keeps the three origins apart: `sample` (the labelled generated
dataset), `test_account` and `live` (a connected Google Ads account). Queries always filter by source, so sample rows
never reach a connected-account series.

`platform_connections` is a read-only status list in this build: no platform can be connected (Connect Accounts,
feature 42, is roadmap), so every platform reads `not_connected`. No token or credential column exists.
"""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

PLATFORMS = ("google_ads", "youtube", "meta", "ga4")
CONNECTION_STATUSES = ("not_connected", "test_account", "connected")
SOURCE_KINDS = ("sample", "test_account", "live")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class PlatformConnection(Base):
    __tablename__ = "platform_connections"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    platform: Mapped[str]
    status: Mapped[str] = mapped_column(default="not_connected")
    last_sync_at: Mapped[datetime | None]
    scopes: Mapped[list] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("workspace_id", "platform"),
        CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name="platform"),
        CheckConstraint(f"status IN ({_in(CONNECTION_STATUSES)})", name="status"),
    )


class MetricSeries(Base):
    __tablename__ = "metric_series"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(ForeignKey("workspaces.id"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    campaign_id: Mapped[UUID] = mapped_column(ForeignKey("campaigns.id"))
    day: Mapped[date]
    platform: Mapped[str]
    channel: Mapped[str]
    version_label: Mapped[str]
    region_code: Mapped[str]
    metric: Mapped[str]
    value: Mapped[float]
    provisional: Mapped[bool] = mapped_column(default=False)
    source_kind: Mapped[str]
    dataset_version: Mapped[str]
    last_updated_at: Mapped[datetime]

    __table_args__ = (
        UniqueConstraint(  # named: the generated name would exceed Postgres' 63-character identifier limit
            "campaign_id", "source_kind", "day", "platform", "channel", "version_label", "region_code", "metric",
            name="uq_metric_series_slice",
        ),
        CheckConstraint(f"platform IN ({_in(PLATFORMS)})", name="platform"),
        CheckConstraint(f"source_kind IN ({_in(SOURCE_KINDS)})", name="source_kind"),
        Index("ix_metric_series_campaign_id_source_kind_region_code_day", "campaign_id", "source_kind", "region_code", "day"),
    )
