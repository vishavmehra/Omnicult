"""Proof Vault: versioned Proof Report snapshots and their stored exports (Omnicult; additive).

Revision ID: 0017
Revises: 0014
Create Date: 2026-11-17 22:00:00

The lead re-chains this revision when merging (the Phase 2 contract gives every stream its own `down_revision`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import UTCDateTime

revision: str = "0017"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table('proof_reports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('campaign_id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=True),
    sa.Column('campaign_version_id', sa.Uuid(), nullable=True),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('mode', sa.String(), nullable=False),
    sa.Column('content_sha256', sa.String(), nullable=False),
    sa.Column('content', JSON, nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("mode IN ('live', 'demo')", name=op.f('ck_proof_reports_mode')),
    sa.CheckConstraint("status IN ('complete', 'partial')", name=op.f('ck_proof_reports_status')),
    sa.ForeignKeyConstraint(['campaign_id', 'project_id'], ['campaigns.id', 'campaigns.project_id'], name=op.f('fk_proof_reports_campaign_id_campaigns')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_proof_reports_created_by_users')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_proof_reports_project_id_projects')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_proof_reports_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_proof_reports')),
    sa.UniqueConstraint('campaign_id', 'version_number', name=op.f('uq_proof_reports_campaign_id_version_number'))
    )
    with op.batch_alter_table('proof_reports', schema=None) as batch_op:
        batch_op.create_index('ix_proof_reports_project_id_created_at', ['project_id', 'created_at'], unique=False)

    op.create_table('proof_report_exports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('report_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('format', sa.String(), nullable=False),
    sa.Column('filename', sa.String(), nullable=False),
    sa.Column('content_type', sa.String(), nullable=False),
    sa.Column('byte_size', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(), nullable=False),
    sa.Column('storage_key', sa.String(), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=True),
    sa.Column('token_hash', sa.String(), nullable=False),
    sa.Column('expires_at', UTCDateTime(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.CheckConstraint("format IN ('json', 'markdown', 'pdf')", name=op.f('ck_proof_report_exports_format')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_proof_report_exports_created_by_users')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_proof_report_exports_project_id_projects')),
    sa.ForeignKeyConstraint(['report_id'], ['proof_reports.id'], name=op.f('fk_proof_report_exports_report_id_proof_reports')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_proof_report_exports'))
    )
    with op.batch_alter_table('proof_report_exports', schema=None) as batch_op:
        batch_op.create_index('ix_proof_report_exports_report_id', ['report_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('proof_report_exports', schema=None) as batch_op:
        batch_op.drop_index('ix_proof_report_exports_report_id')

    op.drop_table('proof_report_exports')
    with op.batch_alter_table('proof_reports', schema=None) as batch_op:
        batch_op.drop_index('ix_proof_reports_project_id_created_at')

    op.drop_table('proof_reports')
