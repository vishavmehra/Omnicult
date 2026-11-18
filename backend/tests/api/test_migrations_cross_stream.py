"""Migration 0021 (cross-stream foreign keys): old rows are kept untouched, the nine keys exist with ON DELETE RESTRICT, and
downgrading removes exactly them. (That the models and the migration agree is checked by test_migrations.py.)"""

import sqlite3
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[2]
NOW = "2026-11-18 03:00:00.000000"
EXPECTED = {
    "readiness_verdicts": {("version_nodes", ("version_id", "campaign_id"), ("id", "campaign_id"))},
    "approvals": {("version_nodes", ("version_id", "campaign_id"), ("id", "campaign_id"))},
    "chips": {("version_nodes", ("applied_version_id", "campaign_id"), ("id", "campaign_id")), ("operations", ("applied_operation_id",), ("id",))},
    "creative_assets": {("agent_runs", ("latest_run_id", "project_id"), ("id", "project_id")),
                        ("agent_runs", ("current_run_id", "project_id"), ("id", "project_id"))},
    "audience_runs": {("campaign_versions", ("content_version_id", "campaign_id"), ("id", "campaign_id"))},
    "proof_reports": {("campaign_versions", ("campaign_version_id", "campaign_id"), ("id", "campaign_id"))},
    "metric_series": {("campaigns", ("campaign_id", "project_id"), ("id", "project_id"))},
}


def config(path: Path) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path.as_posix()}")
    cfg.attributes["configure_logging"] = False
    return cfg


def keys(db: Path, table: str) -> dict[tuple, str]:
    """(referenced table, local columns, referenced columns) -> ON DELETE action, from PRAGMA foreign_key_list."""
    grouped: dict[int, dict] = {}
    with sqlite3.connect(db) as conn:
        for fid, _seq, ref, src, dst, _on_update, on_delete, _match in conn.execute(f"PRAGMA foreign_key_list({table})"):
            entry = grouped.setdefault(fid, {"ref": ref, "src": [], "dst": [], "on_delete": on_delete})
            entry["src"].append(src)
            entry["dst"].append(dst)
    return {(g["ref"], tuple(g["src"]), tuple(g["dst"])): g["on_delete"] for g in grouped.values()}


def test_the_nine_keys_are_added_restrict_old_rows_survive_and_downgrade_removes_only_them(tmp_path: Path) -> None:
    db = tmp_path / "cross.db"
    cfg = config(db)
    command.upgrade(cfg, "0017")
    before = {table: set(keys(db, table)) for table in EXPECTED}
    assert all(not (EXPECTED[t] & before[t]) for t in EXPECTED)  # none of them exists yet
    orphan = uuid4().hex  # a verdict stored before versions were checked: its version id is not a version node
    with sqlite3.connect(db) as conn:  # foreign keys are off on this connection, as they are in migrations
        conn.execute(
            "INSERT INTO readiness_verdicts (id, project_id, campaign_id, region_id, version_id, verdict, main_reason, rule_version, "
            "scoring_version, overall_score, input_fingerprint, inputs, result, mode, computed_by, computed_at) "
            "VALUES (?, ?, ?, ?, ?, 'go', 'r', 'ready-1', 'mvp-2', NULL, 'f', '{}', '{}', 'live', ?, ?)",
            (uuid4().hex, uuid4().hex, uuid4().hex, uuid4().hex, orphan, uuid4().hex, NOW))

    command.upgrade(cfg, "0021")
    for table, expected in EXPECTED.items():
        found = keys(db, table)
        assert expected <= set(found), table
        assert all(found[key] == "RESTRICT" for key in expected), table  # deliberate: a parent is never deleted under its records
        assert before[table] <= set(found), table  # every key that was there is still there
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT version_id FROM readiness_verdicts").fetchall() == [(orphan,)]  # never edited, never dropped

    command.downgrade(cfg, "0017")
    for table in EXPECTED:
        assert set(keys(db, table)) == before[table], table
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM readiness_verdicts").fetchone() == (1,)
    command.upgrade(cfg, "head")
    assert all(EXPECTED[t] <= set(keys(db, t)) for t in EXPECTED)
