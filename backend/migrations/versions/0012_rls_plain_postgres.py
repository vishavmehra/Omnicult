"""Make the 0002-0005 Row Level Security safe on plain Postgres (decision M-07).

Those revisions ran `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` unconditionally but created their SELECT policies only
when Supabase's `auth.uid()` and role `authenticated` exist. On Cloud SQL (no Supabase) every table was therefore left
with RLS on and no policy: a database role that does not own the tables (the runtime role, once migrations run as a
separate role) would read zero rows. Omnicult authorizes in the API (workspace membership), so this revision disables
RLS on every table of the current schema that has it, but only where Supabase's `auth.uid()` is absent. Supabase
databases keep their policies untouched. The new Omnicult tables never enable RLS.

The old revisions stay as they were; downgrade is a no-op because the previous state (RLS on, no policy) was a defect.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-17 14:50:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DISABLE_WITHOUT_SUPABASE = """
DO $do$
DECLARE tbl record;
BEGIN
  IF to_regprocedure('auth.uid()') IS NULL THEN
    FOR tbl IN
      SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = current_schema() AND c.relkind = 'r' AND c.relrowsecurity
    LOOP
      EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', tbl.relname);
    END LOOP;
  END IF;
END
$do$;
"""


def upgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.execute(DISABLE_WITHOUT_SUPABASE)


def downgrade() -> None:
    pass
