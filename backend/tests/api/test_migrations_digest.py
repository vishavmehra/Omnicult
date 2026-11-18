"""Migration 0030 (Comment Pulse and Weekly Digest): the three tables arrive on top of 0020, hold rows, enforce their keys and go on downgrade."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[2]
NOW = "2026-11-18 12:00:00.000000"
TABLES = {"pulse_comments", "pulse_comment_analyses", "pulse_digests"}


def config(path: Path) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path.as_posix()}")
    cfg.attributes["configure_logging"] = False
    return cfg


def tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_digest_tables_are_added_by_0030_enforce_their_rules_and_go_on_downgrade(tmp_path: Path) -> None:
    db = tmp_path / "digest.db"
    cfg = config(db)
    command.upgrade(cfg, "0020")
    assert not TABLES & tables(db)

    command.upgrade(cfg, "0030")  # the digest revision hangs off 0020 until the lead re-chains it
    assert TABLES <= tables(db)
    user, workspace, project, campaign, other = (uuid4().hex for _ in range(5))
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("INSERT INTO users (id, is_anonymous, created_at) VALUES (?, 0, ?)", (user, NOW))
        conn.execute("INSERT INTO workspaces (id, name, kind, created_by, created_at) VALUES (?, 'W', 'personal', ?, ?)", (workspace, user, NOW))
        for pid in (project, other):
            conn.execute(
                "INSERT INTO projects (id, owner_id, workspace_id, name, mode, status, target_markets, created_at, updated_at) "
                "VALUES (?, ?, ?, 'P', 'demo', 'active', '[]', ?, ?)", (pid, user, workspace, NOW, NOW))
        conn.execute(
            "INSERT INTO campaigns (id, project_id, name, campaign_type, evaluation_criteria, target_markets, created_at, updated_at) "
            "VALUES (?, ?, 'C', 'advertisement', '{}', '[]', ?, ?)", (campaign, project, NOW, NOW))
        comment = (
            "INSERT INTO pulse_comments (id, workspace_id, project_id, campaign_id, ref, day, platform, region_code, version_label, language, "
            "script, code_mixed, text, likes, source_kind, dataset_version, last_updated_at) "
            "VALUES (?, ?, ?, ?, ?, '2026-11-02', 'youtube', 'IN-TN', 'v1', 'ta', 'Taml', 0, 'text', 3, ?, 'v', ?)")
        conn.execute(comment, (uuid4().hex, workspace, project, campaign, "cm-0001", "sample", NOW))
        for bad, why in (
            ((uuid4().hex, workspace, project, campaign, "cm-0001", "sample", NOW), "a ref is unique per campaign and source"),
            ((uuid4().hex, workspace, project, campaign, "cm-0002", "bogus", NOW), "source_kind is checked"),
            ((uuid4().hex, workspace, other, campaign, "cm-0003", "sample", NOW), "a campaign must belong to the project"),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(comment, bad)
            print("refused:", why)
        conn.execute(
            "INSERT INTO pulse_comment_analyses (id, workspace_id, project_id, campaign_id, dataset_version, mode, status, prompt_version, provider, "
            "comment_count, read_count, dropped, labels, themes, notes, created_at) "
            "VALUES (?, ?, ?, ?, 'v', 'demo', 'completed', 'comment-read-v1', 'fixture', 1, 1, '{}', '{}', '[]', '[]', ?)",
            (uuid4().hex, workspace, project, campaign, NOW))
        digest = (
            "INSERT INTO pulse_digests (id, workspace_id, project_id, campaign_id, iso_year, iso_week, week_start, week_end, revision, mode, "
            "trigger, content, content_sha256, generated_at) VALUES (?, ?, ?, ?, 2026, ?, '2026-11-09', '2026-11-15', 1, 'demo', ?, '{}', 'h', ?)")
        conn.execute(digest, (uuid4().hex, workspace, project, campaign, 46, "scheduler", NOW))
        for bad, why in (
            ((uuid4().hex, workspace, project, campaign, 46, "manual", NOW), "one digest per campaign and ISO week"),
            ((uuid4().hex, workspace, project, campaign, 54, "manual", NOW), "the ISO week is 1 to 53"),
            ((uuid4().hex, workspace, project, campaign, 47, "email", NOW), "a digest is manual or scheduled, never sent"),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(digest, bad)
            print("refused:", why)

    command.downgrade(cfg, "0020")
    assert not TABLES & tables(db)
