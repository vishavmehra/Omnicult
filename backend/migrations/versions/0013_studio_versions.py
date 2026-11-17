"""Creative Studio: version_nodes, operations, locks, chips, glossary_terms (Omnicult; additive) and the `transcreate`
run type.

A version node is an immutable snapshot of a creative's elements; an operation writes a new node and never changes its
source. Locks keep their history (released_at). The agent_runs run_type CHECK is widened with `transcreate` (the
streams that add run types widen it in their own revisions; the lead merges the lists when re-chaining).

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-17 20:43:24.729813
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = '0013'
down_revision: str | None = '0012'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
V5_RUN_TYPES = (
    "'market_discovery', 'campaign_rehearsal', 'campaign_adaptation', 'campaign_evaluation', 'cultural_profile', "
    "'campaign_arena', 'risk_scan', 'market_comparison', 'population_study', 'social_simulation'"
)
V6_RUN_TYPES = V5_RUN_TYPES + ", 'transcreate'"


def _run_types(values: str) -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_constraint(op.f("ck_agent_runs_run_type"), type_="check")
        batch_op.create_check_constraint("run_type", f"run_type IN ({values})")


def upgrade() -> None:
    _run_types(V6_RUN_TYPES)
    op.create_table('glossary_terms',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('term', sa.String(), nullable=False),
    sa.Column('term_key', sa.String(), nullable=False),
    sa.Column('language', sa.String(), nullable=False),
    sa.Column('script', sa.String(), nullable=True),
    sa.Column('approved_spelling', sa.String(), nullable=True),
    sa.Column('preferred_translation', sa.String(), nullable=True),
    sa.Column('pronunciation', sa.String(), nullable=True),
    sa.Column('protected', sa.Boolean(), nullable=False),
    sa.Column('never_translate', sa.Boolean(), nullable=False),
    sa.Column('prohibited_alternatives', JSON, nullable=False),
    sa.Column('notes', sa.String(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_glossary_terms_created_by_users')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_glossary_terms_project_id_projects')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_glossary_terms')),
    sa.UniqueConstraint('project_id', 'term_key', 'language', name=op.f('uq_glossary_terms_project_id_term_key_language'))
    )
    op.create_index('ix_glossary_terms_project_id_language', 'glossary_terms', ['project_id', 'language'], unique=False)

    op.create_table('locks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('element_id', sa.String(), nullable=False),
    sa.Column('locked_by', sa.Uuid(), nullable=False),
    sa.Column('reason', sa.String(), nullable=True),
    sa.Column('locked_at', UTCDateTime(), nullable=False),
    sa.Column('released_at', UTCDateTime(), nullable=True),
    sa.Column('released_by', sa.Uuid(), nullable=True),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_locks_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['locked_by'], ['users.id'], name=op.f('fk_locks_locked_by_users')),
    sa.ForeignKeyConstraint(['released_by'], ['users.id'], name=op.f('fk_locks_released_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_locks'))
    )
    op.create_index('ix_locks_campaign_id_locked_at', 'locks', ['campaign_id', 'locked_at'], unique=False)
    op.create_index(
        'uq_locks_campaign_id_element_id_active', 'locks', ['campaign_id', 'element_id'], unique=True,
        sqlite_where=sa.text('released_at IS NULL'), postgresql_where=sa.text('released_at IS NULL'),
    )

    op.create_table('version_nodes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('parent_id', sa.Uuid(), nullable=True),
    sa.Column('label', sa.String(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('actor', sa.String(), nullable=False),
    sa.Column('region_code', sa.String(), nullable=True),
    sa.Column('language', sa.String(), nullable=True),
    sa.Column('settings', JSON, nullable=False),
    sa.Column('elements', JSON, nullable=False),
    sa.Column('operation_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("actor IN ('user', 'ai')", name=op.f('ck_version_nodes_actor')),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_version_nodes_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_version_nodes_created_by_users')),
    sa.ForeignKeyConstraint(['parent_id', 'campaign_id'], ['version_nodes.id', 'version_nodes.campaign_id'], name=op.f('fk_version_nodes_parent_id_version_nodes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_version_nodes')),
    sa.UniqueConstraint('id', 'campaign_id', name=op.f('uq_version_nodes_id_campaign_id'))
    )
    op.create_index('ix_version_nodes_campaign_id_created_at', 'version_nodes', ['campaign_id', 'created_at'], unique=False)
    op.create_index('ix_version_nodes_parent_id', 'version_nodes', ['parent_id'], unique=False)

    op.create_table('chips',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('version_id', sa.Uuid(), nullable=False),
    sa.Column('element_id', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('operation_type', sa.String(), nullable=False),
    sa.Column('change', JSON, nullable=False),
    sa.Column('params', JSON, nullable=False),
    sa.Column('reason', sa.String(), nullable=False),
    sa.Column('claim_ids', JSON, nullable=False),
    sa.Column('expected_effect', sa.String(), nullable=False),
    sa.Column('reversible', sa.Boolean(), nullable=False),
    sa.Column('estimated_cost_usd', sa.Double(), nullable=True),
    sa.Column('prompt_version', sa.String(), nullable=True),
    sa.Column('provider', sa.String(), nullable=True),
    sa.Column('model_id', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('applied_operation_id', sa.Uuid(), nullable=True),
    sa.Column('applied_version_id', sa.Uuid(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("operation_type IN ('replace_text', 'swap_reference')", name=op.f('ck_chips_operation_type')),
    sa.CheckConstraint("status IN ('proposed', 'applied')", name=op.f('ck_chips_status')),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_chips_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_chips_created_by_users')),
    sa.ForeignKeyConstraint(['version_id', 'campaign_id'], ['version_nodes.id', 'version_nodes.campaign_id'], name=op.f('fk_chips_version_id_version_nodes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_chips'))
    )
    op.create_index('ix_chips_campaign_id_version_id', 'chips', ['campaign_id', 'version_id'], unique=False)

    op.create_table('operations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('source_version_id', sa.Uuid(), nullable=False),
    sa.Column('result_version_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('target_element_ids', JSON, nullable=False),
    sa.Column('params', JSON, nullable=False),
    sa.Column('reason', sa.String(), nullable=False),
    sa.Column('claim_ids', JSON, nullable=False),
    sa.Column('actor', sa.String(), nullable=False),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('prompt_version', sa.String(), nullable=True),
    sa.Column('estimated_cost_usd', sa.Double(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('rejection', JSON, nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("actor IN ('user', 'ai')", name=op.f('ck_operations_actor')),
    sa.CheckConstraint("kind IN ('manual_edit', 'replace_text', 'transcreate', 'apply_chip', 'swap_reference', 'change_setting', 'tone_shift', 'restore')", name=op.f('ck_operations_kind')),
    sa.CheckConstraint("status <> 'applied' OR result_version_id IS NOT NULL", name=op.f('ck_operations_applied_has_version')),
    sa.CheckConstraint("status IN ('applied', 'rejected')", name=op.f('ck_operations_status')),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name=op.f('fk_operations_actor_user_id_users')),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_operations_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['result_version_id', 'campaign_id'], ['version_nodes.id', 'version_nodes.campaign_id'], name=op.f('fk_operations_result_version_id_version_nodes')),
    sa.ForeignKeyConstraint(['source_version_id', 'campaign_id'], ['version_nodes.id', 'version_nodes.campaign_id'], name=op.f('fk_operations_source_version_id_version_nodes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_operations'))
    )
    op.create_index('ix_operations_campaign_id_created_at', 'operations', ['campaign_id', 'created_at'], unique=False)
    op.create_index('ix_operations_source_version_id', 'operations', ['source_version_id'], unique=False)



def downgrade() -> None:
    op.drop_index('ix_operations_source_version_id', table_name='operations')
    op.drop_index('ix_operations_campaign_id_created_at', table_name='operations')

    op.drop_table('operations')
    op.drop_index('ix_chips_campaign_id_version_id', table_name='chips')

    op.drop_table('chips')
    op.drop_index('ix_version_nodes_parent_id', table_name='version_nodes')
    op.drop_index('ix_version_nodes_campaign_id_created_at', table_name='version_nodes')

    op.drop_table('version_nodes')
    op.drop_index('uq_locks_campaign_id_element_id_active', table_name='locks')
    op.drop_index('ix_locks_campaign_id_locked_at', table_name='locks')

    op.drop_table('locks')
    op.drop_index('ix_glossary_terms_project_id_language', table_name='glossary_terms')

    op.drop_table('glossary_terms')
    op.execute("DELETE FROM agent_runs WHERE run_type = 'transcreate'")
    _run_types(V5_RUN_TYPES)
