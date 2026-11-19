"""Search pulse: lens_search_pulse (Omnicult; additive).

One row per state, kind (top or rising), term and week of the Google Trends public dataset (BigQuery), with the refresh_date,
retrieval time, BigQuery job id and bytes processed each came from. Feeds the Market Lens State Profile and Trend Radar.
Public data shared by every workspace; no existing table changes.

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-19 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "lens_search_pulse",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("region_code", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("term", sa.String(), nullable=False),
        sa.Column("week", sa.Date(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("percent_gain", sa.Integer(), nullable=True),
        sa.Column("refresh_date", sa.Date(), nullable=False),
        sa.Column("retrieved_at", UTCDateTime(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("bytes_processed", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("kind IN ('top', 'rising')", name=op.f("ck_lens_search_pulse_kind")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lens_search_pulse")),
        sa.UniqueConstraint("region_code", "kind", "term", "week", name=op.f("uq_lens_search_pulse_region_code_kind_term_week")),
    )


def downgrade() -> None:
    op.drop_table("lens_search_pulse")
