"""State facts: a per-figure provenance column (Omnicult; additive).

Google Data Commons names the source of every observation (a facet: its import, measurement method and publisher page), and a
stored figure keeps it. Null for the data.gov.in rows. Nothing existing changes.

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-20 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.base import JSONType

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("state_fact_snapshots", sa.Column("provenance", JSONType, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("state_fact_snapshots") as batch:
        batch.drop_column("provenance")
