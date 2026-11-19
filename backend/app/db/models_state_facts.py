"""State facts snapshot (migration 0035): official state-wise statistics pulled from data.gov.in, one row per resource, state,
metric and period. The data is public and the same for every workspace, so the table has no owner column (like `regions`).

`region_code` is an Omnicult region code (`IN-TN`) or `IN` for the all-India row of a dataset. `source_updated_at` is the
resource's own `updated_date`: a pull that finds it unchanged skips the download and only moves `retrieved_at`.
Demo campaigns never read this table; they read the recorded fixture.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class StateFactSnapshot(Base):
    __tablename__ = "state_fact_snapshots"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    resource_id: Mapped[str]
    region_code: Mapped[str]
    metric: Mapped[str]
    period: Mapped[str]
    value: Mapped[float]
    unit: Mapped[str]
    source_updated_at: Mapped[datetime | None]
    retrieved_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("resource_id", "region_code", "metric", "period"),
        Index("ix_state_fact_snapshots_region_code", "region_code"),
    )
