"""State facts: state_fact_snapshots (official state-wise statistics from data.gov.in, shared by every workspace).

Additive. One row per resource, state, metric and period; `source_updated_at` is the resource's own updated_date and lets a
scheduled pull skip an unchanged resource. Chained on 0033; the lead re-chains this revision after 0034 when merging.

Revision ID: 0035
Revises: 0033
Create Date: 2026-11-19 11:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.base import UTCDateTime

revision: str = "0035"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "state_fact_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("region_code", sa.String(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("period", sa.String(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("source_updated_at", UTCDateTime(), nullable=True),
        sa.Column("retrieved_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_state_fact_snapshots")),
        sa.UniqueConstraint("resource_id", "region_code", "metric", "period", name=op.f("uq_state_fact_snapshots_resource_id_region_code_metric_period")),
    )
    op.create_index("ix_state_fact_snapshots_region_code", "state_fact_snapshots", ["region_code"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_state_fact_snapshots_region_code", table_name="state_fact_snapshots")
    op.drop_table("state_fact_snapshots")
