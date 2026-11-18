"""Migration 0020 (Market Lens): the two tables arrive on top of 0017, hold rows, and go away again on downgrade."""

import sqlite3
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[2]
NOW = "2026-11-18 12:00:00.000000"


def config(path: Path) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path.as_posix()}")
    cfg.attributes["configure_logging"] = False
    return cfg


def tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_lens_tables_are_added_by_0020_and_dropped_by_its_downgrade(tmp_path: Path) -> None:
    db = tmp_path / "lens.db"
    cfg = config(db)
    command.upgrade(cfg, "0017")
    assert not {"lens_builds", "culture_calls"} & tables(db)

    command.upgrade(cfg, "0020")
    assert {"lens_builds", "culture_calls"} <= tables(db)
    user, workspace, project, campaign, build = (uuid4().hex for _ in range(5))
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("INSERT INTO users (id, is_anonymous, created_at) VALUES (?, 0, ?)", (user, NOW))
        conn.execute("INSERT INTO workspaces (id, name, kind, created_by, created_at) VALUES (?, 'W', 'personal', ?, ?)", (workspace, user, NOW))
        conn.execute(
            "INSERT INTO projects (id, owner_id, workspace_id, name, mode, status, target_markets, created_at, updated_at) "
            "VALUES (?, ?, ?, 'P', 'demo', 'active', '[]', ?, ?)", (project, user, workspace, NOW, NOW))
        conn.execute(
            "INSERT INTO campaigns (id, project_id, name, campaign_type, evaluation_criteria, target_markets, created_at, updated_at) "
            "VALUES (?, ?, 'C', 'advertisement', '{}', '[]', ?, ?)", (campaign, project, NOW, NOW))
        conn.execute(
            "INSERT INTO lens_builds (id, workspace_id, project_id, campaign_id, region_code, mode, version, status, years, options, claim_count, "
            "created_claims, updated_claims, conflicts_opened, rejected_claims, categories, gaps, sources_skipped, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, 'IN-TN', 'demo', 1, 'completed', '[2027]', '{}', 0, 0, 0, 0, 0, '{}', '[]', '[]', ?, ?)",
            (build, workspace, project, campaign, NOW, NOW))
        conn.execute(
            "INSERT INTO culture_calls (id, workspace_id, build_id, mode, source, operation, request_hash, status, cached, result_count, "
            "duration_ms, retrieved_at) VALUES (?, ?, ?, 'demo', 'fixture', 'moments', 'h', 'ok', 0, 3, 5, ?)", (uuid4().hex, workspace, build, NOW))
        try:
            conn.execute("UPDATE lens_builds SET status = 'bogus'")
            raise AssertionError("the status CHECK did not hold")
        except sqlite3.IntegrityError:
            pass

    command.downgrade(cfg, "0017")
    assert not {"lens_builds", "culture_calls"} & tables(db)
    command.upgrade(cfg, "0020")  # and up again: the revision is repeatable
    assert {"lens_builds", "culture_calls"} <= tables(db)
