"""Migration 0022 (Settings): invites and workspace settings are created, constrained, and removed on downgrade."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory

from tests.api.test_migrations_omnicult import BACKEND, config, rows


def tables(db: Path) -> set[str]:
    return {r[0] for r in rows(db, "SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_0022_is_the_single_head_and_upgrades_and_downgrades(tmp_path: Path) -> None:
    cfg = config(tmp_path / "settings.db")
    assert ScriptDirectory.from_config(cfg).get_heads() == ["0022"]
    command.upgrade(cfg, "head")
    assert {"workspace_invites", "workspace_settings"} <= tables(tmp_path / "settings.db")
    command.downgrade(cfg, "0017")
    assert not {"workspace_invites", "workspace_settings"} & tables(tmp_path / "settings.db")
    command.upgrade(cfg, "head")  # re-running after a downgrade is safe


def test_the_invite_table_refuses_a_second_pending_invite_and_unknown_roles(tmp_path: Path) -> None:
    db = tmp_path / "constraints.db"
    command.upgrade(config(db), "head")
    now = "2026-01-01 00:00:00.000000"
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        insert = (
            "INSERT INTO workspace_invites (id, workspace_id, email, role, code_hash, status, created_by, created_at, expires_at) "
            "VALUES (?, 'w', 'a@b.co', ?, ?, ?, 'u', ?, ?)"
        )
        conn.execute(insert, ("1", "viewer", "h1", "pending", now, now))
        conn.execute(insert, ("2", "viewer", "h2", "revoked", now, now))  # a closed invite does not count
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("3", "viewer", "h3", "pending", now, now))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("4", "admin", "h4", "revoked", now, now))
