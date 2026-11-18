"""Migration 0024 (Voice Director): the plans table arrives on top of 0020, the run_type CHECK gains `voice_direct`, and
the downgrade removes both (voice_direct runs go with their table)."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
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


def test_voice_plans_and_the_run_type_arrive_with_0024_and_go_with_its_downgrade(tmp_path: Path) -> None:
    db = tmp_path / "voice.db"
    cfg = config(db)
    command.upgrade(cfg, "0020")
    assert "voice_plans" not in tables(db)

    command.upgrade(cfg, "0024")
    assert "voice_plans" in tables(db)
    user, workspace, project, campaign, node, run, plan = (uuid4().hex for _ in range(7))
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
            "INSERT INTO version_nodes (id, campaign_id, project_id, label, actor, settings, elements, created_at) "
            "VALUES (?, ?, ?, 'Original', 'user', '{}', '[]', ?)", (node, campaign, project, NOW))
        conn.execute(
            "INSERT INTO agent_runs (id, project_id, campaign_id, run_type, status, mode, inputs, steps, created_at, attempt) "
            "VALUES (?, ?, ?, 'voice_direct', 'completed', 'demo', '{}', '[]', ?, 0)", (run, project, campaign, NOW))
        conn.execute(
            "INSERT INTO voice_plans (id, project_id, campaign_id, version_id, run_id, mode, source, instruction, supported, steps, notes, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'demo', 'typed', 'Make it warmer', 1, '[]', '[]', ?, ?)",
            (plan, project, campaign, node, run, NOW, NOW))
        with pytest.raises(sqlite3.IntegrityError):  # the CHECK constraints are real
            conn.execute("UPDATE voice_plans SET source = 'telepathy'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE agent_runs SET run_type = 'voice_dictate'")

    command.downgrade(cfg, "0020")
    assert "voice_plans" not in tables(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM agent_runs").fetchone() == (0,)  # the voice_direct run went with its plans
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO agent_runs (id, project_id, campaign_id, run_type, status, mode, inputs, steps, created_at, attempt) "
                "VALUES (?, ?, ?, 'voice_direct', 'completed', 'demo', '{}', '[]', ?, 0)", (uuid4().hex, project, campaign, NOW))
    command.upgrade(cfg, "head")  # and up again: the revision is repeatable
    assert "voice_plans" in tables(db)
