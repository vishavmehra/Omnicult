"""Audience Lab session tables (migration 0027): Live Focus Group turns and interjections, and Buzz Simulator acts.

The three session kinds (`focus_group`, `buzz_sim`, `message_check`) are rows of `audience_runs`, like Quick Read: they
reuse the run lifecycle, the idempotency key, the usage scope and the panel participants (`audience_participants`).
Only what a panel run does not already store lives here. Every row is synthetic by what it is: a turn, an interjection
or an act written during a simulation. Re-exported by `app.db.models`, so `m.FocusGroupTurn`, ... work.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

TURN_KINDS = "'moderator', 'participant', 'researcher'"
RELATIONS = "'agrees', 'disagrees', 'builds_on', 'new_point'"
STANCES = "'positive', 'mixed', 'neutral', 'negative', 'confused'"
INTERJECTION_STATUSES = "'pending', 'taken', 'dropped'"
BUZZ_ACTIONS = "'post', 'reply', 'share', 'ignore'"


class FocusGroupTurn(Base):
    """One turn of a moderated session, in order. A moderator turn is a guide question (or a probe written by code from
    earlier turns), a researcher turn is a person's interjection, a participant turn is a synthetic participant's reply."""

    __tablename__ = "audience_focus_turns"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("audience_runs.id"))
    turn_index: Mapped[int]
    round_index: Mapped[int]  # which guide question or interjection this turn belongs to (0-based, in session order)
    kind: Mapped[str]
    participant_id: Mapped[UUID | None] = mapped_column(ForeignKey("audience_participants.id"))
    text: Mapped[str]
    reply_to_turn_index: Mapped[int | None]
    relation: Mapped[str | None]
    stance: Mapped[str | None]
    themes: Mapped[list] = mapped_column(default=list)
    claim_ids: Mapped[list] = mapped_column(default=list)
    interjection_id: Mapped[UUID | None] = mapped_column(ForeignKey("audience_focus_interjections.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "turn_index"),
        CheckConstraint(f"kind IN ({TURN_KINDS})", name="kind"),
        CheckConstraint(f"relation IS NULL OR relation IN ({RELATIONS})", name="relation"),
        CheckConstraint(f"stance IS NULL OR stance IN ({STANCES})", name="stance"),
        CheckConstraint("(kind = 'participant') = (participant_id IS NOT NULL)", name="speaker"),
        Index("ix_audience_focus_turns_run_id_turn_index", "run_id", "turn_index"),
    )


class FocusGroupInterjection(Base):
    """A question a person typed while the session ran. It is relayed at the next turn boundary (`taken`), or dropped when
    the session ended first."""

    __tablename__ = "audience_focus_interjections"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("audience_runs.id"))
    text: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    taken_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint(f"status IN ({INTERJECTION_STATUSES})", name="status"),
        Index("ix_audience_focus_interjections_run_id_created_at", "run_id", "created_at"),
    )


class BuzzAct(Base):
    """What one simulated account did when it saw the creative: posted, replied, reshared or scrolled past. Each account
    acts once, in the round after it first saw the creative. `exposed_by` is the account whose post showed it (null for
    the seed audience); the text is the model's, the counts over these rows are code's."""

    __tablename__ = "audience_buzz_acts"

    id: Mapped[UUID] = mapped_column(primary_key=True)  # uuid5 of the run id, round and participant: stable
    run_id: Mapped[UUID] = mapped_column(ForeignKey("audience_runs.id"))
    round_index: Mapped[int]
    participant_id: Mapped[UUID] = mapped_column(ForeignKey("audience_participants.id"))
    action: Mapped[str]
    text: Mapped[str | None]
    text_en: Mapped[str | None]
    message_gloss: Mapped[str | None]
    stance: Mapped[str]
    topics: Mapped[list] = mapped_column(default=list)
    parent_act_id: Mapped[UUID | None] = mapped_column(ForeignKey("audience_buzz_acts.id"))
    exposed_by: Mapped[UUID | None] = mapped_column(ForeignKey("audience_participants.id"))
    wording_overlap: Mapped[float | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "participant_id"),
        CheckConstraint(f"action IN ({BUZZ_ACTIONS})", name="action"),
        CheckConstraint(f"stance IN ({STANCES})", name="stance"),
        CheckConstraint("round_index >= 1", name="round_index"),
        Index("ix_audience_buzz_acts_run_id_round_index", "run_id", "round_index"),
    )
