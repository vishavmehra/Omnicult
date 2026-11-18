"""Audience Lab sessions: Live Focus Group, Buzz Simulator and Message Check (Omnicult; additive).

The three kinds are rows of `audience_runs`, so the `kind` CHECK widens to the union of the current kinds and the new ones.
New tables: `audience_focus_interjections`, `audience_focus_turns` (the saved transcript) and `audience_buzz_acts` (what each
simulated account did). Participants stay in `audience_participants`. `agent_runs` is not touched.
The lead re-chains this revision when merging.

Revision ID: 0027
Revises: 0025
Create Date: 2026-11-18 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0027"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
PRIOR_KINDS = "'quick_read', 'audience_study', 'risk_check'"
KINDS = PRIOR_KINDS + ", 'focus_group', 'buzz_sim', 'message_check'"
STANCES = "'positive', 'mixed', 'neutral', 'negative', 'confused'"


def _kinds(values: str) -> None:
    with op.batch_alter_table("audience_runs") as batch:
        batch.drop_constraint(op.f("ck_audience_runs_kind"), type_="check")
        batch.create_check_constraint("kind", f"kind IN ({values})")


def upgrade() -> None:
    _kinds(KINDS)
    op.create_table(
        "audience_focus_interjections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("taken_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'taken', 'dropped')", name=op.f("ck_audience_focus_interjections_status")),
        sa.ForeignKeyConstraint(["run_id"], ["audience_runs.id"], name=op.f("fk_audience_focus_interjections_run_id_audience_runs")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_audience_focus_interjections_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audience_focus_interjections")),
    )
    op.create_index("ix_audience_focus_interjections_run_id_created_at", "audience_focus_interjections", ["run_id", "created_at"])
    op.create_table(
        "audience_focus_turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("round_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=True),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("reply_to_turn_index", sa.Integer(), nullable=True),
        sa.Column("relation", sa.String(), nullable=True),
        sa.Column("stance", sa.String(), nullable=True),
        sa.Column("themes", JSON, nullable=False),
        sa.Column("claim_ids", JSON, nullable=False),
        sa.Column("interjection_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('moderator', 'participant', 'researcher')", name=op.f("ck_audience_focus_turns_kind")),
        sa.CheckConstraint(
            "relation IS NULL OR relation IN ('agrees', 'disagrees', 'builds_on', 'new_point')", name=op.f("ck_audience_focus_turns_relation")),
        sa.CheckConstraint(f"stance IS NULL OR stance IN ({STANCES})", name=op.f("ck_audience_focus_turns_stance")),
        sa.CheckConstraint("(kind = 'participant') = (participant_id IS NOT NULL)", name=op.f("ck_audience_focus_turns_speaker")),
        sa.ForeignKeyConstraint(["run_id"], ["audience_runs.id"], name=op.f("fk_audience_focus_turns_run_id_audience_runs")),
        sa.ForeignKeyConstraint(
            ["participant_id"], ["audience_participants.id"], name=op.f("fk_audience_focus_turns_participant_id_audience_participants")),
        sa.ForeignKeyConstraint(
            ["interjection_id"], ["audience_focus_interjections.id"],
            name=op.f("fk_audience_focus_turns_interjection_id_audience_focus_interjections")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audience_focus_turns")),
        sa.UniqueConstraint("run_id", "turn_index", name=op.f("uq_audience_focus_turns_run_id_turn_index")),
    )
    op.create_index("ix_audience_focus_turns_run_id_turn_index", "audience_focus_turns", ["run_id", "turn_index"])
    op.create_table(
        "audience_buzz_acts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("round_index", sa.Integer(), nullable=False),
        sa.Column("participant_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("text", sa.String(), nullable=True),
        sa.Column("text_en", sa.String(), nullable=True),
        sa.Column("message_gloss", sa.String(), nullable=True),
        sa.Column("stance", sa.String(), nullable=False),
        sa.Column("topics", JSON, nullable=False),
        sa.Column("parent_act_id", sa.Uuid(), nullable=True),
        sa.Column("exposed_by", sa.Uuid(), nullable=True),
        sa.Column("wording_overlap", sa.Double(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("action IN ('post', 'reply', 'share', 'ignore')", name=op.f("ck_audience_buzz_acts_action")),
        sa.CheckConstraint(f"stance IN ({STANCES})", name=op.f("ck_audience_buzz_acts_stance")),
        sa.CheckConstraint("round_index >= 1", name=op.f("ck_audience_buzz_acts_round_index")),
        sa.ForeignKeyConstraint(["run_id"], ["audience_runs.id"], name=op.f("fk_audience_buzz_acts_run_id_audience_runs")),
        sa.ForeignKeyConstraint(
            ["participant_id"], ["audience_participants.id"], name=op.f("fk_audience_buzz_acts_participant_id_audience_participants")),
        sa.ForeignKeyConstraint(["parent_act_id"], ["audience_buzz_acts.id"], name=op.f("fk_audience_buzz_acts_parent_act_id_audience_buzz_acts")),
        sa.ForeignKeyConstraint(["exposed_by"], ["audience_participants.id"], name=op.f("fk_audience_buzz_acts_exposed_by_audience_participants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audience_buzz_acts")),
        sa.UniqueConstraint("run_id", "participant_id", name=op.f("uq_audience_buzz_acts_run_id_participant_id")),
    )
    op.create_index("ix_audience_buzz_acts_run_id_round_index", "audience_buzz_acts", ["run_id", "round_index"])


def downgrade() -> None:
    op.drop_index("ix_audience_buzz_acts_run_id_round_index", table_name="audience_buzz_acts")
    op.drop_table("audience_buzz_acts")
    op.drop_index("ix_audience_focus_turns_run_id_turn_index", table_name="audience_focus_turns")
    op.drop_table("audience_focus_turns")
    op.drop_index("ix_audience_focus_interjections_run_id_created_at", table_name="audience_focus_interjections")
    op.drop_table("audience_focus_interjections")
    # Rows of the new kinds cannot satisfy the narrower CHECK: they and what hangs off them are removed first (already gone above).
    op.execute("DELETE FROM audience_participants WHERE run_id IN (SELECT id FROM audience_runs WHERE kind NOT IN (" + PRIOR_KINDS + "))")
    op.execute("DELETE FROM audience_runs WHERE kind NOT IN (" + PRIOR_KINDS + ")")
    _kinds(PRIOR_KINDS)
