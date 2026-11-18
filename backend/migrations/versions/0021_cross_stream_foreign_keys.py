"""Cross-stream foreign keys: references the Phase 2 streams stored as plain UUIDs become real constraints.

Added (all `ON DELETE RESTRICT`, composite wherever the parent has a (id, campaign_id) or (id, project_id) key, so a row
can only point at a parent of its own campaign or project):

- readiness_verdicts and approvals: (version_id, campaign_id) -> version_nodes. A verdict or a decision always concerns
  a Creative Studio version of the same campaign.
- chips: (applied_version_id, campaign_id) -> version_nodes and applied_operation_id -> operations.
- creative_assets: (latest_run_id, project_id) and (current_run_id, project_id) -> agent_runs.
- audience_runs and proof_reports: (content_version_id | campaign_version_id, campaign_id) -> campaign_versions.
- metric_series: (campaign_id, project_id) -> campaigns, next to the single-column keys it already has.

RESTRICT everywhere, deliberately: nothing in the product deletes these parents (a project is archived, D-011), and the
rows pointing at them are records (verdicts, approvals, runs, reports) that must never vanish with a parent. A pointer is
never nulled behind a person's back.

Not added: `version_nodes.operation_id` (it and `operations.result_version_id` reference each other, so one of the two
rows is always inserted first), and `audience_runs.version_ref` (an opaque string by design).

Existing rows are never edited. On Postgres each key is added NOT VALID (new and changed rows are checked at once), then
validated in a block that tolerates failure: if old rows point at a parent that does not exist (for example a verdict
stored for a version id the client made up, before versions were checked), the key stays NOT VALID and a notice says so;
`ALTER TABLE ... VALIDATE CONSTRAINT <name>` finishes the job once those rows are fixed. SQLite copies rows unchecked.

Revision ID: 0021
Revises: 0017
Create Date: 2026-11-18 03:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, constraint name, local columns, referent table, referent columns)
KEYS: tuple[tuple[str, str, tuple[str, ...], str, tuple[str, ...]], ...] = (
    ("readiness_verdicts", "fk_readiness_verdicts_version_id_version_nodes", ("version_id", "campaign_id"), "version_nodes", ("id", "campaign_id")),
    ("approvals", "fk_approvals_version_id_version_nodes", ("version_id", "campaign_id"), "version_nodes", ("id", "campaign_id")),
    ("chips", "fk_chips_applied_version_id_version_nodes", ("applied_version_id", "campaign_id"), "version_nodes", ("id", "campaign_id")),
    ("chips", "fk_chips_applied_operation_id_operations", ("applied_operation_id",), "operations", ("id",)),
    ("creative_assets", "fk_creative_assets_latest_run_id_agent_runs", ("latest_run_id", "project_id"), "agent_runs", ("id", "project_id")),
    ("creative_assets", "fk_creative_assets_current_run_id_agent_runs", ("current_run_id", "project_id"), "agent_runs", ("id", "project_id")),
    ("audience_runs", "fk_audience_runs_content_version_id_campaign_versions", ("content_version_id", "campaign_id"), "campaign_versions", ("id", "campaign_id")),
    ("proof_reports", "fk_proof_reports_campaign_version_id_campaign_versions", ("campaign_version_id", "campaign_id"), "campaign_versions", ("id", "campaign_id")),
    ("metric_series", "fk_metric_series_campaign_id_project_id_campaigns", ("campaign_id", "project_id"), "campaigns", ("id", "project_id")),
)

VALIDATE = """
DO $$
BEGIN
    ALTER TABLE {table} VALIDATE CONSTRAINT {name};
EXCEPTION WHEN foreign_key_violation THEN
    RAISE NOTICE 'constraint {name} stays NOT VALID: existing rows of {table} point at a missing parent';
END $$;
"""


def _tables() -> list[str]:
    return list(dict.fromkeys(key[0] for key in KEYS))


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table, name, local, referent, remote in KEYS:
            op.create_foreign_key(name, table, referent, list(local), list(remote), ondelete="RESTRICT", postgresql_not_valid=True)
            op.execute(VALIDATE.format(table=table, name=name))
        return
    for table in _tables():  # SQLite: one table rebuild per table
        with op.batch_alter_table(table) as batch:
            for _, name, local, referent, remote in (k for k in KEYS if k[0] == table):
                batch.create_foreign_key(name, referent, list(local), list(remote), ondelete="RESTRICT")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table, name, *_ in KEYS:
            op.drop_constraint(name, table, type_="foreignkey")
        return
    for table in _tables():
        with op.batch_alter_table(table) as batch:
            for _, name, *_ in (k for k in KEYS if k[0] == table):
                batch.drop_constraint(name, type_="foreignkey")
