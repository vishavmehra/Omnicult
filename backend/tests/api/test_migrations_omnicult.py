"""Omnicult migrations 0007-0012 with data: the owner backfill, downgrades, and re-running safely."""

import sqlite3
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[2]
NOW = "2026-01-01 00:00:00.000000"


def config(path: Path) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path.as_posix()}")
    cfg.attributes["configure_logging"] = False
    return cfg


def insert_project(db: Path, owner: str, name: str) -> str:
    project_id = uuid4().hex
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO projects (id, owner_id, name, mode, status, target_markets, created_at, updated_at) "
            "VALUES (?, ?, ?, 'live', 'active', '[]', ?, ?)",
            (project_id, owner, name, NOW, NOW),
        )
    return project_id


def rows(db: Path, sql: str) -> list[tuple]:
    with sqlite3.connect(db) as conn:
        return conn.execute(sql).fetchall()


def test_existing_owners_get_a_personal_workspace_and_their_projects_move_into_it(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    cfg = config(db)
    command.upgrade(cfg, "0006")
    ada, grace = uuid4().hex, uuid4().hex
    ada_projects = {insert_project(db, ada, "A1"), insert_project(db, ada, "A2")}
    grace_project = insert_project(db, grace, "G1")

    command.upgrade(cfg, "0008")

    users = {r[0]: r[1] for r in rows(db, "SELECT id, firebase_uid FROM users")}
    assert set(users) == {ada, grace} and set(users.values()) == {None}  # the owner id is reused; no Firebase uid yet
    workspaces = rows(db, "SELECT id, created_by, kind FROM workspaces")
    assert sorted((w[1], w[2]) for w in workspaces) == sorted([(ada, "personal"), (grace, "personal")])
    owner_of = {w[1]: w[0] for w in workspaces}
    members = {(r[0], r[1], r[2]) for r in rows(db, "SELECT workspace_id, user_id, role FROM workspace_members")}
    assert members == {(owner_of[ada], ada, "owner"), (owner_of[grace], grace, "owner")}
    placed = {r[0]: r[1] for r in rows(db, "SELECT id, workspace_id FROM projects")}
    assert {placed[p] for p in ada_projects} == {owner_of[ada]} and placed[grace_project] == owner_of[grace]


def test_a_database_without_projects_migrates_and_a_rerun_after_downgrade_is_safe(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    cfg = config(db)
    command.upgrade(cfg, "head")
    assert rows(db, "SELECT count(*) FROM users") == [(0,)]
    command.downgrade(cfg, "0006")
    owner = uuid4().hex
    insert_project(db, owner, "P")
    command.upgrade(cfg, "head")  # the backfill runs again on a database that has data
    assert rows(db, "SELECT count(*) FROM workspaces") == [(1,)]
    command.downgrade(cfg, "0007")  # drops the project column; users and workspaces stay until 0007 goes
    assert rows(db, "SELECT count(*) FROM users") == [(1,)]
    command.upgrade(cfg, "head")  # and the backfill is idempotent: the existing user and workspace are reused
    assert rows(db, "SELECT count(*) FROM users") == [(1,)]
    assert rows(db, "SELECT count(*) FROM workspaces") == [(1,)]
    assert rows(db, "SELECT workspace_id IS NOT NULL FROM projects") == [(1,)]


def test_data_in_the_new_tables_survives_up_and_down_to_the_old_schema(tmp_path: Path) -> None:
    db = tmp_path / "full.db"
    cfg = config(db)
    command.upgrade(cfg, "head")
    user, workspace, region, claim = (uuid4().hex for _ in range(4))
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO users (id, is_anonymous, created_at) VALUES (?, 0, ?)", (user, NOW))
        conn.execute("INSERT INTO workspaces (id, name, kind, created_by, created_at) VALUES (?, 'w', 'team', ?, ?)", (workspace, user, NOW))
        conn.execute("INSERT INTO languages (code, name, script, direction, code_standard, is_active) VALUES ('ta', 'Tamil', 'Taml', 'ltr', 'iso639-1', 1)")
        conn.execute("INSERT INTO regions (id, country_code, code, name, kind, is_active, created_at) VALUES (?, 'IN', 'IN-TN', 'Tamil Nadu', 'state', 1, ?)", (region, NOW))
        conn.execute(
            "INSERT INTO claims (id, workspace_id, region_id, claim_key, subject, attribute, category, value, value_text, scope, kind, "
            "confidence, confidence_reason, retrieved_at, status, mode, created_at, updated_at) "
            "VALUES (?, ?, ?, 'k', 's', 'a', 'festival', '\"v\"', 't', '{}', 'observed', 'low', 'r', ?, 'active', 'live', ?, ?)",
            (claim, workspace, region, NOW, NOW, NOW),
        )
    command.downgrade(cfg, "0006")
    tables = {r[0] for r in rows(db, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert not tables & {"users", "workspaces", "claims", "conflicts", "regions", "ai_usage_events", "audit_log"}
    command.upgrade(cfg, "head")
    assert rows(db, "SELECT count(*) FROM claims") == [(0,)]  # the new tables are recreated empty
