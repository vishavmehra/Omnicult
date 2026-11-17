"""Audience Lab: audience_runs, audience_participants, audience_questions, audience_answers, audience_risk_findings
(Omnicult; additive).

Quick Read, Audience Study and Risk Check keep their own run lifecycle in `audience_runs` (queued, running, completed,
partial, failed, cancelled), with an idempotency key unique per user. Panel participants are synthetic by a CHECK
constraint. Creative elements and scenes are JSON and `version_ref` is an opaque string: no foreign key reaches a media
or version table. `agent_runs` and its run_type CHECK are not touched.

Revision ID: 0015
Revises: 0013
Create Date: 2026-11-17 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0015"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table('audience_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=True),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('mode', sa.String(), nullable=False),
    sa.Column('region_codes', JSON, nullable=False),
    sa.Column('content_version_id', sa.Uuid(), nullable=True),
    sa.Column('version_ref', sa.String(), nullable=True),
    sa.Column('seed', sa.Integer(), nullable=True),
    sa.Column('config', JSON, nullable=False),
    sa.Column('inputs', JSON, nullable=False),
    sa.Column('result', JSON, nullable=True),
    sa.Column('progress', JSON, nullable=True),
    sa.Column('steps', JSON, nullable=False),
    sa.Column('usage', JSON, nullable=True),
    sa.Column('error', JSON, nullable=True),
    sa.Column('limitations', JSON, nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('idempotency_key', sa.String(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('started_at', UTCDateTime(), nullable=True),
    sa.Column('completed_at', UTCDateTime(), nullable=True),
    sa.Column('lease_expires_at', UTCDateTime(), nullable=True),
    sa.CheckConstraint("kind IN ('quick_read', 'audience_study', 'risk_check')", name=op.f('ck_audience_runs_kind')),
    sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f('ck_audience_runs_mode')),
    sa.CheckConstraint("status IN ('queued', 'running', 'completed', 'partial', 'failed', 'cancelled')", name=op.f('ck_audience_runs_status')),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_audience_runs_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_audience_runs_created_by_users')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_audience_runs_project_id_projects')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_audience_runs_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audience_runs'))
    )
    with op.batch_alter_table('audience_runs', schema=None) as batch_op:
        batch_op.create_index('ix_audience_runs_campaign_id_kind_created_at', ['campaign_id', 'kind', 'created_at'], unique=False)
        batch_op.create_index('ix_audience_runs_project_id_created_at', ['project_id', 'created_at'], unique=False)
        batch_op.create_index('ix_audience_runs_status', ['status'], unique=False)
        batch_op.create_index('uq_audience_runs_created_by_idempotency_key', ['created_by', 'idempotency_key'], unique=True)

    op.create_table('audience_participants',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('state_code', sa.String(), nullable=False),
    sa.Column('state_name', sa.String(), nullable=False),
    sa.Column('language', sa.String(), nullable=False),
    sa.Column('language_name', sa.String(), nullable=False),
    sa.Column('city_tier', sa.String(), nullable=False),
    sa.Column('age_band', sa.String(), nullable=False),
    sa.Column('traits', JSON, nullable=False),
    sa.Column('persona', sa.String(), nullable=False),
    sa.Column('response', JSON, nullable=True),
    sa.Column('is_synthetic', sa.Boolean(), nullable=False),
    sa.CheckConstraint("age_band IN ('18-24', '25-34', '35-44', '45-54', '55+')", name=op.f('ck_audience_participants_age_band')),
    sa.CheckConstraint("city_tier IN ('tier1', 'tier2', 'tier3', 'rural')", name=op.f('ck_audience_participants_city_tier')),
    sa.CheckConstraint('is_synthetic', name=op.f('ck_audience_participants_synthetic')),
    sa.ForeignKeyConstraint(['run_id'], ['audience_runs.id'], name=op.f('fk_audience_participants_run_id_audience_runs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audience_participants')),
    sa.UniqueConstraint('run_id', 'ordinal', name=op.f('uq_audience_participants_run_id_ordinal'))
    )
    with op.batch_alter_table('audience_participants', schema=None) as batch_op:
        batch_op.create_index('ix_audience_participants_run_id_ordinal', ['run_id', 'ordinal'], unique=False)

    op.create_table('audience_questions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('asked_by', sa.Uuid(), nullable=True),
    sa.Column('target_kind', sa.String(), nullable=False),
    sa.Column('target', JSON, nullable=False),
    sa.Column('question', sa.String(), nullable=False),
    sa.Column('summaries', JSON, nullable=False),
    sa.Column('stance', JSON, nullable=False),
    sa.Column('unanswered', JSON, nullable=False),
    sa.Column('mode', sa.String(), nullable=False),
    sa.Column('limitations', JSON, nullable=False),
    sa.Column('usage', JSON, nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f('ck_audience_questions_mode')),
    sa.CheckConstraint("target_kind IN ('participant', 'subgroup', 'panel')", name=op.f('ck_audience_questions_target_kind')),
    sa.ForeignKeyConstraint(['asked_by'], ['users.id'], name=op.f('fk_audience_questions_asked_by_users')),
    sa.ForeignKeyConstraint(['run_id'], ['audience_runs.id'], name=op.f('fk_audience_questions_run_id_audience_runs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audience_questions'))
    )
    with op.batch_alter_table('audience_questions', schema=None) as batch_op:
        batch_op.create_index('ix_audience_questions_run_id_created_at', ['run_id', 'created_at'], unique=False)

    op.create_table('audience_risk_findings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('element_id', sa.String(), nullable=False),
    sa.Column('category', sa.String(), nullable=False),
    sa.Column('severity', sa.String(), nullable=False),
    sa.Column('blocks_go', sa.Boolean(), nullable=False),
    sa.Column('confidence_label', sa.String(), nullable=False),
    sa.Column('anchor', JSON, nullable=False),
    sa.Column('quote', sa.String(), nullable=True),
    sa.Column('quote_start', sa.Integer(), nullable=True),
    sa.Column('quote_end', sa.Integer(), nullable=True),
    sa.Column('verification', sa.String(), nullable=False),
    sa.Column('observation', sa.String(), nullable=False),
    sa.Column('interpretation', sa.String(), nullable=False),
    sa.Column('suggested_fix', sa.String(), nullable=True),
    sa.Column('ad_codes', JSON, nullable=False),
    sa.Column('claim_ids', JSON, nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('severity_rules', JSON, nullable=False),
    sa.Column('rules_version', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('status_reason', sa.String(), nullable=True),
    sa.Column('status_by', sa.Uuid(), nullable=True),
    sa.Column('status_at', UTCDateTime(), nullable=True),
    sa.Column('limitations', JSON, nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("severity IN ('low', 'medium', 'high')", name=op.f('ck_audience_risk_findings_severity')),
    sa.CheckConstraint("source IN ('deterministic_check', 'model_assessment')", name=op.f('ck_audience_risk_findings_source')),
    sa.CheckConstraint("status IN ('open', 'accepted', 'dismissed', 'fixed')", name=op.f('ck_audience_risk_findings_status')),
    sa.CheckConstraint("verification IN ('quote_verified', 'element_reference', 'deterministic')", name=op.f('ck_audience_risk_findings_verification')),
    sa.ForeignKeyConstraint(['run_id'], ['audience_runs.id'], name=op.f('fk_audience_risk_findings_run_id_audience_runs')),
    sa.ForeignKeyConstraint(['status_by'], ['users.id'], name=op.f('fk_audience_risk_findings_status_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audience_risk_findings')),
    sa.UniqueConstraint('run_id', 'ordinal', name=op.f('uq_audience_risk_findings_run_id_ordinal'))
    )
    with op.batch_alter_table('audience_risk_findings', schema=None) as batch_op:
        batch_op.create_index('ix_audience_risk_findings_run_id_status', ['run_id', 'status'], unique=False)

    op.create_table('audience_answers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('question_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('participant_id', sa.Uuid(), nullable=False),
    sa.Column('answer', sa.String(), nullable=False),
    sa.Column('stance', sa.String(), nullable=True),
    sa.Column('memory_refs', JSON, nullable=False),
    sa.Column('model_id', sa.String(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['participant_id'], ['audience_participants.id'], name=op.f('fk_audience_answers_participant_id_audience_participants')),
    sa.ForeignKeyConstraint(['question_id'], ['audience_questions.id'], name=op.f('fk_audience_answers_question_id_audience_questions')),
    sa.ForeignKeyConstraint(['run_id'], ['audience_runs.id'], name=op.f('fk_audience_answers_run_id_audience_runs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audience_answers'))
    )
    with op.batch_alter_table('audience_answers', schema=None) as batch_op:
        batch_op.create_index('ix_audience_answers_participant_id_created_at', ['participant_id', 'created_at'], unique=False)
        batch_op.create_index('ix_audience_answers_question_id', ['question_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('audience_answers', schema=None) as batch_op:
        batch_op.drop_index('ix_audience_answers_question_id')
        batch_op.drop_index('ix_audience_answers_participant_id_created_at')

    op.drop_table('audience_answers')
    with op.batch_alter_table('audience_risk_findings', schema=None) as batch_op:
        batch_op.drop_index('ix_audience_risk_findings_run_id_status')

    op.drop_table('audience_risk_findings')
    with op.batch_alter_table('audience_questions', schema=None) as batch_op:
        batch_op.drop_index('ix_audience_questions_run_id_created_at')

    op.drop_table('audience_questions')
    with op.batch_alter_table('audience_participants', schema=None) as batch_op:
        batch_op.drop_index('ix_audience_participants_run_id_ordinal')

    op.drop_table('audience_participants')
    with op.batch_alter_table('audience_runs', schema=None) as batch_op:
        batch_op.drop_index('uq_audience_runs_created_by_idempotency_key')
        batch_op.drop_index('ix_audience_runs_status')
        batch_op.drop_index('ix_audience_runs_project_id_created_at')
        batch_op.drop_index('ix_audience_runs_campaign_id_kind_created_at')

    op.drop_table('audience_runs')
