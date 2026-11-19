"""Migration 0035 (State facts): the snapshot table arrives on top of 0033 and goes away again on downgrade."""

import sqlite3
from pathlib import Path

from alembic import command

from tests.api.test_migrations_lens import config, tables


def test_state_fact_snapshots_are_added_by_0035_and_dropped_by_its_downgrade(tmp_path: Path) -> None:
    db = tmp_path / "state_facts.db"
    cfg = config(db)
    command.upgrade(cfg, "0033")
    assert "state_fact_snapshots" not in tables(db)

    command.upgrade(cfg, "0035")
    assert "state_fact_snapshots" in tables(db)
    with sqlite3.connect(db) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(state_fact_snapshots)")}
        assert {"resource_id", "region_code", "metric", "period", "value", "unit", "source_updated_at", "retrieved_at"} <= columns
        unique = [r for r in conn.execute("PRAGMA index_list(state_fact_snapshots)") if r[2]]
        assert unique, "one row per resource, state, metric and period"

    command.downgrade(cfg, "0033")
    assert "state_fact_snapshots" not in tables(db)
    command.upgrade(cfg, "0035")
    assert "state_fact_snapshots" in tables(db)
