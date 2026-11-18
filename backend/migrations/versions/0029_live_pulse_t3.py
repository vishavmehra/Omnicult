"""Live Pulse Tier 3: saved alert rules with their alerts, events and evaluations; version links and comparison snapshots.

Additive. The lead re-chains this revision when merging.

Revision ID: 0029
Revises: 0023
Create Date: 2026-11-18 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0029"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table('pulse_alert_evaluations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('trigger', sa.String(), nullable=False),
    sa.Column('period_key', sa.String(), nullable=True),
    sa.Column('dataset_version', sa.String(), nullable=False),
    sa.Column('evaluated_at', UTCDateTime(), nullable=False),
    sa.Column('rules_evaluated', sa.Integer(), nullable=False),
    sa.Column('alerts_found', sa.Integer(), nullable=False),
    sa.Column('opened', sa.Integer(), nullable=False),
    sa.Column('reopened', sa.Integer(), nullable=False),
    sa.Column('resolved', sa.Integer(), nullable=False),
    sa.Column('not_evaluated', sa.Integer(), nullable=False),
    sa.CheckConstraint("trigger IN ('refresh', 'manual', 'scheduler')", name=op.f('ck_pulse_alert_evaluations_trigger')),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_pulse_alert_evaluations_campaign_id_campaigns')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pulse_alert_evaluations')),
    sa.UniqueConstraint('campaign_id', 'period_key', name=op.f('uq_pulse_alert_evaluations_campaign_id_period_key'))
    )
    with op.batch_alter_table('pulse_alert_evaluations', schema=None) as batch_op:
        batch_op.create_index('ix_pulse_alert_evaluations_campaign_id_evaluated_at', ['campaign_id', 'evaluated_at'], unique=False)

    op.create_table('pulse_alert_rules',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('alert_type', sa.String(), nullable=False),
    sa.Column('region_code', sa.String(), nullable=True),
    sa.Column('version_label', sa.String(), nullable=True),
    sa.Column('params', JSON, nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("alert_type IN ('ctr_drop', 'frequency_fatigue', 'cost_spike', 'prediction_miss')", name=op.f('ck_pulse_alert_rules_alert_type')),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_pulse_alert_rules_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_pulse_alert_rules_created_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pulse_alert_rules'))
    )
    with op.batch_alter_table('pulse_alert_rules', schema=None) as batch_op:
        batch_op.create_index('ix_pulse_alert_rules_campaign_id', ['campaign_id'], unique=False)

    op.create_table('pulse_comparison_snapshots',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('metric', sa.String(), nullable=False),
    sa.Column('method_version', sa.String(), nullable=False),
    sa.Column('fingerprint', sa.String(), nullable=False),
    sa.Column('dataset_version', sa.String(), nullable=False),
    sa.Column('pair_count', sa.Integer(), nullable=False),
    sa.Column('inputs', JSON, nullable=False),
    sa.Column('result', JSON, nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_pulse_comparison_snapshots_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_pulse_comparison_snapshots_created_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pulse_comparison_snapshots'))
    )
    with op.batch_alter_table('pulse_comparison_snapshots', schema=None) as batch_op:
        batch_op.create_index('ix_pulse_comparison_snapshots_campaign_id_created_at', ['campaign_id', 'created_at'], unique=False)

    op.create_table('pulse_alerts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('rule_id', sa.Uuid(), nullable=True),
    sa.Column('rule_name', sa.String(), nullable=False),
    sa.Column('alert_key', sa.String(), nullable=False),
    sa.Column('alert_type', sa.String(), nullable=False),
    sa.Column('region_code', sa.String(), nullable=False),
    sa.Column('version_label', sa.String(), nullable=False),
    sa.Column('metric', sa.String(), nullable=False),
    sa.Column('threshold', sa.Double(), nullable=False),
    sa.Column('observed_value', sa.Double(), nullable=False),
    sa.Column('comparison_value', sa.Double(), nullable=False),
    sa.Column('comparison', sa.String(), nullable=False),
    sa.Column('window_from', sa.Date(), nullable=False),
    sa.Column('window_to', sa.Date(), nullable=False),
    sa.Column('suggested_action', sa.String(), nullable=False),
    sa.Column('source_path', sa.String(), nullable=False),
    sa.Column('dataset_version', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('resolution', sa.String(), nullable=True),
    sa.Column('opened_at', UTCDateTime(), nullable=False),
    sa.Column('last_seen_at', UTCDateTime(), nullable=False),
    sa.Column('acknowledged_at', UTCDateTime(), nullable=True),
    sa.Column('acknowledged_by', sa.Uuid(), nullable=True),
    sa.Column('resolved_at', UTCDateTime(), nullable=True),
    sa.Column('resolved_by', sa.Uuid(), nullable=True),
    sa.CheckConstraint("alert_type IN ('ctr_drop', 'frequency_fatigue', 'cost_spike', 'prediction_miss')", name=op.f('ck_pulse_alerts_alert_type')),
    sa.CheckConstraint("status IN ('open', 'acknowledged', 'resolved')", name=op.f('ck_pulse_alerts_status')),
    sa.ForeignKeyConstraint(['acknowledged_by'], ['users.id'], name=op.f('fk_pulse_alerts_acknowledged_by_users')),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_pulse_alerts_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], name=op.f('fk_pulse_alerts_resolved_by_users')),
    sa.ForeignKeyConstraint(['rule_id'], ['pulse_alert_rules.id'], name=op.f('fk_pulse_alerts_rule_id_pulse_alert_rules'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pulse_alerts')),
    sa.UniqueConstraint('campaign_id', 'alert_key', name=op.f('uq_pulse_alerts_campaign_id_alert_key'))
    )
    with op.batch_alter_table('pulse_alerts', schema=None) as batch_op:
        batch_op.create_index('ix_pulse_alerts_campaign_id_status', ['campaign_id', 'status'], unique=False)

    op.create_table('pulse_version_links',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('region_code', sa.String(), nullable=False),
    sa.Column('pulse_version', sa.String(), nullable=False),
    sa.Column('version_id', sa.Uuid(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_pulse_version_links_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_pulse_version_links_created_by_users')),
    sa.ForeignKeyConstraint(['version_id', 'campaign_id'], ['version_nodes.id', 'version_nodes.campaign_id'], name=op.f('fk_pulse_version_links_version_id_version_nodes'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pulse_version_links')),
    sa.UniqueConstraint('campaign_id', 'region_code', 'pulse_version', name=op.f('uq_pulse_version_links_campaign_id_region_code_pulse_version'))
    )
    op.create_table('pulse_alert_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('alert_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('at', UTCDateTime(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('trigger', sa.String(), nullable=False),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('note', sa.String(), nullable=True),
    sa.Column('observed_value', sa.Double(), nullable=True),
    sa.CheckConstraint("kind IN ('opened', 'acknowledged', 'resolved', 'reopened')", name=op.f('ck_pulse_alert_events_kind')),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name=op.f('fk_pulse_alert_events_actor_user_id_users')),
    sa.ForeignKeyConstraint(['alert_id'], ['pulse_alerts.id'], name=op.f('fk_pulse_alert_events_alert_id_pulse_alerts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], name=op.f('fk_pulse_alert_events_campaign_id_campaigns')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pulse_alert_events'))
    )
    with op.batch_alter_table('pulse_alert_events', schema=None) as batch_op:
        batch_op.create_index('ix_pulse_alert_events_alert_id_at', ['alert_id', 'at'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('pulse_alert_events', schema=None) as batch_op:
        batch_op.drop_index('ix_pulse_alert_events_alert_id_at')

    op.drop_table('pulse_alert_events')
    op.drop_table('pulse_version_links')
    with op.batch_alter_table('pulse_alerts', schema=None) as batch_op:
        batch_op.drop_index('ix_pulse_alerts_campaign_id_status')

    op.drop_table('pulse_alerts')
    with op.batch_alter_table('pulse_comparison_snapshots', schema=None) as batch_op:
        batch_op.drop_index('ix_pulse_comparison_snapshots_campaign_id_created_at')

    op.drop_table('pulse_comparison_snapshots')
    with op.batch_alter_table('pulse_alert_rules', schema=None) as batch_op:
        batch_op.drop_index('ix_pulse_alert_rules_campaign_id')

    op.drop_table('pulse_alert_rules')
    with op.batch_alter_table('pulse_alert_evaluations', schema=None) as batch_op:
        batch_op.drop_index('ix_pulse_alert_evaluations_campaign_id_evaluated_at')

    op.drop_table('pulse_alert_evaluations')
