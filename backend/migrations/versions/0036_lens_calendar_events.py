"""Moment Calendar: lens_calendar_events (Omnicult; additive).

One row per event of Google Calendar's public "Holidays in India" calendar (Calendar API, read with an API key): date, name,
public holiday or observance, and a tentative flag. Public data shared by every workspace; refreshed by the daily signals job.
No existing table changes.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-19 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.base import UTCDateTime

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lens_calendar_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("calendar_id", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("tentative", sa.Boolean(), nullable=False),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("source_updated_at", UTCDateTime(), nullable=True),
        sa.Column("retrieved_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('public_holiday', 'observance')", name=op.f("ck_lens_calendar_events_kind")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lens_calendar_events")),
        sa.UniqueConstraint("calendar_id", "event_id", name=op.f("uq_lens_calendar_events_calendar_id_event_id")),
    )
    op.create_index("ix_lens_calendar_events_calendar_id_year", "lens_calendar_events", ["calendar_id", "year"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_lens_calendar_events_calendar_id_year", table_name="lens_calendar_events")
    op.drop_table("lens_calendar_events")
