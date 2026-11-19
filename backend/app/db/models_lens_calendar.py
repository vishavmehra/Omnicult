"""Moment Calendar events from Google Calendar's public "Holidays in India" calendar (migration 0036).

One row per event as the Calendar API returned it: the date, the name, whether Google lists it as a public holiday or an
observance, and whether the date is marked tentative. Public data, the same for every workspace, so the table has no owner
column (like `lens_search_pulse`). A refresh replaces a year's rows; demo campaigns read a recording instead.
"""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class LensCalendarEvent(Base):
    __tablename__ = "lens_calendar_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    calendar_id: Mapped[str]
    event_id: Mapped[str]
    year: Mapped[int]
    day: Mapped[date]
    name: Mapped[str]
    kind: Mapped[str]  # public_holiday | observance, from the event's own description
    tentative: Mapped[bool] = mapped_column(default=False)
    url: Mapped[str | None]  # the event's page in Google Calendar
    source_updated_at: Mapped[datetime | None]  # the event's own `updated`
    retrieved_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("calendar_id", "event_id"),
        CheckConstraint("kind IN ('public_holiday', 'observance')", name="kind"),
        Index("ix_lens_calendar_events_calendar_id_year", "calendar_id", "year"),
    )
