"""Migration 0034 (search pulse): hangs off 0033, adds lens_search_pulse with its key and check, and goes on downgrade."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.script import ScriptDirectory

from tests.api.test_migrations_youtube import columns, config, tables

ROW = "INSERT INTO lens_search_pulse (id, region_code, kind, term, week, refresh_date, retrieved_at) VALUES (?, 'IN-TN', ?, 'gold rate today', '2026-11-15', '2026-11-18', '2026-11-19 05:30:00.000000')"


def test_0034_sits_on_0033_and_is_the_head() -> None:
    script = ScriptDirectory.from_config(config(Path("unused.db")))
    assert script.get_heads() == ["0034"] and script.get_revision("0034").down_revision == "0033"


def test_the_table_arrives_with_provenance_columns_one_row_per_term_and_week_and_goes_on_downgrade(tmp_path: Path) -> None:
    db = tmp_path / "pulse.db"
    cfg = config(db)
    command.upgrade(cfg, "0033")
    assert "lens_search_pulse" not in tables(db)
    command.upgrade(cfg, "0034")
    assert {"region_code", "kind", "term", "week", "rank", "score", "percent_gain", "refresh_date", "retrieved_at", "job_id", "bytes_processed"} <= columns(db, "lens_search_pulse")
    with sqlite3.connect(db) as conn:
        conn.execute(ROW, (str(uuid4()), "top"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(ROW, (str(uuid4()), "top"))  # the same state, kind, term and week
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(ROW, (str(uuid4()), "other"))  # kind is top or rising
        conn.execute(ROW, (str(uuid4()), "rising"))
    command.downgrade(cfg, "0033")
    assert "lens_search_pulse" not in tables(db)
    command.upgrade(cfg, "0034")
    assert "lens_search_pulse" in tables(db)
