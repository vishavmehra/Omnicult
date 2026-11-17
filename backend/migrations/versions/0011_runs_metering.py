"""Runs and metering: agent_runs idempotency and lease columns, ai_usage_events, audit_log (Omnicult; additive).

`agent_runs.created_by` + `idempotency_key` are unique together (a unique index, which SQLite also supports without
recreating the table), so a retried POST returns the run it created. `lease_expires_at`, `heartbeat_at` and `attempt`
let a sweep tell a live run from an orphaned one when several instances run. The run_type CHECK is left as it is:
a stream that adds a run type widens it in its own revision.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-17 14:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("created_by", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("idempotency_key", sa.String(), nullable=True))
        batch.add_column(sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("lease_expires_at", UTCDateTime(), nullable=True))
        batch.add_column(sa.Column("heartbeat_at", UTCDateTime(), nullable=True))
        batch.create_foreign_key(op.f("fk_agent_runs_created_by_users"), "users", ["created_by"], ["id"])
        batch.create_index("uq_agent_runs_created_by_idempotency_key", ["created_by", "idempotency_key"], unique=True)
    op.create_table(
        "ai_usage_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("capability", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("thinking_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Double(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_ai_usage_events_workspace_id_workspaces")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_ai_usage_events_project_id_projects")),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], name=op.f("fk_ai_usage_events_campaign_id_campaigns")),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], name=op.f("fk_ai_usage_events_run_id_agent_runs")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_ai_usage_events_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_usage_events")),
    )
    op.create_index("ix_ai_usage_events_workspace_id_created_at", "ai_usage_events", ["workspace_id", "created_at"], unique=False)
    op.create_index("ix_ai_usage_events_run_id", "ai_usage_events", ["run_id"], unique=False)
    op.create_index("ix_ai_usage_events_user_id_created_at", "ai_usage_events", ["user_id", "created_at"], unique=False)
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("detail", JSON, nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name=op.f("fk_audit_log_workspace_id_workspaces")),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_audit_log_actor_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_workspace_id_created_at", "audit_log", ["workspace_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_log_workspace_id_created_at", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_ai_usage_events_user_id_created_at", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_run_id", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_workspace_id_created_at", table_name="ai_usage_events")
    op.drop_table("ai_usage_events")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_index("uq_agent_runs_created_by_idempotency_key")
        batch.drop_constraint(op.f("fk_agent_runs_created_by_users"), type_="foreignkey")
        for column in ("heartbeat_at", "lease_expires_at", "attempt", "idempotency_key", "created_by"):
            batch.drop_column(column)
