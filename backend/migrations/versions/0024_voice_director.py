"""Voice Director: the voice_plans table, and the agent_runs run_type CHECK gains `voice_direct`.

Additive. A plan is the validated list of steps a typed or spoken instruction produced, with each step's outcome. The
planning call is recorded as a `voice_direct` run so it appears in Run History with its model and cost. The lead re-chains
this revision when merging.

Revision ID: 0024
Revises: 0022
Create Date: 2026-11-18 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0024"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
PRIOR_RUN_TYPES = (
    "'market_discovery', 'campaign_rehearsal', 'campaign_adaptation', 'campaign_evaluation', "
    "'cultural_profile', 'campaign_arena', 'risk_scan', 'market_comparison', 'population_study', 'social_simulation', "
    "'transcreate', 'creative_xray'"
)
RUN_TYPES = PRIOR_RUN_TYPES + ", 'voice_direct'"


def _run_types(values: str) -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint(op.f("ck_agent_runs_run_type"), type_="check")
        batch.create_check_constraint("run_type", f"run_type IN ({values})")


def upgrade() -> None:
    _run_types(RUN_TYPES)
    op.create_table(
        "voice_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("instruction", sa.String(), nullable=False),
        sa.Column("transcript", sa.String(), nullable=True),
        sa.Column("supported", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("refusal", sa.String(), nullable=True),
        sa.Column("steps", JSON, nullable=False),
        sa.Column("notes", JSON, nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("model_id", sa.String(), nullable=True),
        sa.Column("prompt_version", sa.String(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Double(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f("ck_voice_plans_mode")),
        sa.CheckConstraint("source IN ('typed', 'voice')", name=op.f("ck_voice_plans_source")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_voice_plans_project_id_projects")),
        sa.ForeignKeyConstraint(
            ["campaign_id", "project_id"], ["campaigns.id", "campaigns.project_id"], name=op.f("fk_voice_plans_campaign_id_campaigns")
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "campaign_id"], ["version_nodes.id", "version_nodes.campaign_id"], name=op.f("fk_voice_plans_version_id_version_nodes")
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], name=op.f("fk_voice_plans_run_id_agent_runs")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_voice_plans_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_voice_plans")),
    )
    op.create_index("ix_voice_plans_campaign_id_created_at", "voice_plans", ["campaign_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("voice_plans")
    op.execute("DELETE FROM agent_runs WHERE run_type = 'voice_direct'")
    _run_types(PRIOR_RUN_TYPES)
