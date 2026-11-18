"""Migration 0025 (Market Lens Tier 3): the three tables arrive on top of 0020 and go away again on downgrade."""

import sqlite3
from pathlib import Path

from alembic import command

from tests.api.test_migrations_lens import config, tables

NEW = {"lens_trend_batches", "lens_trend_snapshots", "lens_shelf_snapshots"}


def test_lens_tier3_tables_are_added_by_0025_and_dropped_by_its_downgrade(tmp_path: Path) -> None:
    db = tmp_path / "lens_t3.db"
    cfg = config(db)
    command.upgrade(cfg, "0020")
    assert not NEW & tables(db)

    command.upgrade(cfg, "0025")
    assert NEW <= tables(db)
    with sqlite3.connect(db) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(lens_trend_snapshots)")}
        assert {"batch_id", "region_code", "term", "editions", "source", "taken_at", "method_version"} <= columns
        unique = [r for r in conn.execute("PRAGMA index_list(lens_shelf_snapshots)") if r[2]]
        assert unique, "shelf versions are unique per workspace, mode and pack"

    command.downgrade(cfg, "0020")
    assert not NEW & tables(db)
    command.upgrade(cfg, "0025")  # and up again
    assert NEW <= tables(db)
