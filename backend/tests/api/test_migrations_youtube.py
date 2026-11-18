"""Migration 0031 (YouTube comments): hangs off 0026, keeps sample rows, enforces its keys and goes on downgrade."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[2]
NOW = "2026-11-18 12:00:00.000000"


def config(path: Path) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path.as_posix()}")
    cfg.attributes["configure_logging"] = False
    return cfg


def columns(db: Path, table: str) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_0031_sits_on_0026_in_the_single_head_chain() -> None:
    script = ScriptDirectory.from_config(config(Path("unused.db")))
    heads = script.get_heads()
    assert len(heads) == 1 and script.get_revision("0031").down_revision == "0026"
    assert "0031" in {rev.revision for rev in script.walk_revisions("base", heads[0])}


def test_youtube_columns_arrive_on_top_of_0026_keep_sample_rows_enforce_their_rules_and_go_on_downgrade(tmp_path: Path) -> None:
    db = tmp_path / "youtube.db"
    cfg = config(db)
    command.upgrade(cfg, "0026")
    assert "pulse_youtube_sources" not in tables(db) and "video_id" not in columns(db, "pulse_comments")
    user, workspace, project, campaign = (uuid4().hex for _ in range(4))
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("INSERT INTO users (id, is_anonymous, created_at) VALUES (?, 0, ?)", (user, NOW))
        conn.execute("INSERT INTO workspaces (id, name, kind, created_by, created_at) VALUES (?, 'W', 'personal', ?, ?)", (workspace, user, NOW))
        conn.execute(
            "INSERT INTO projects (id, owner_id, workspace_id, name, mode, status, target_markets, created_at, updated_at) "
            "VALUES (?, ?, ?, 'P', 'live', 'active', '[]', ?, ?)", (project, user, workspace, NOW, NOW))
        conn.execute(
            "INSERT INTO campaigns (id, project_id, name, campaign_type, evaluation_criteria, target_markets, created_at, updated_at) "
            "VALUES (?, ?, 'C', 'advertisement', '{}', '[]', ?, ?)", (campaign, project, NOW, NOW))
        conn.execute(
            "INSERT INTO pulse_comments (id, workspace_id, project_id, campaign_id, ref, day, platform, region_code, version_label, language, "
            "script, code_mixed, text, likes, source_kind, dataset_version, last_updated_at) "
            "VALUES (?, ?, ?, ?, 'cm-0001', '2026-11-02', 'youtube', 'IN-TN', 'v1', 'ta', 'Taml', 0, 'text', 3, 'sample', 'v', ?)",
            (uuid4().hex, workspace, project, campaign, NOW))
        conn.execute(
            "INSERT INTO pulse_comment_analyses (id, workspace_id, project_id, campaign_id, dataset_version, mode, status, prompt_version, provider, "
            "comment_count, read_count, dropped, labels, themes, notes, created_at) "
            "VALUES (?, ?, ?, ?, 'v', 'demo', 'completed', 'comment-read-v1', 'fixture', 1, 1, '{}', '{}', '[]', '[]', ?)",
            (uuid4().hex, workspace, project, campaign, NOW))

    command.upgrade(cfg, "0031")
    assert {"video_id", "external_id", "published_at", "reply_count"} <= columns(db, "pulse_comments")
    assert "source_kind" in columns(db, "pulse_comment_analyses") and "pulse_youtube_sources" in tables(db)
    assert not [c for table in ("pulse_comments", "pulse_youtube_sources") for c in columns(db, table) if "author" in c or "channel" in c or "avatar" in c]
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        assert conn.execute("SELECT source_kind, video_id, external_id, reply_count FROM pulse_comments").fetchall() == [("sample", None, None, None)]
        assert conn.execute("SELECT source_kind FROM pulse_comment_analyses").fetchall() == [("sample",)], "an earlier reading is a sample reading"
        comment = (
            "INSERT INTO pulse_comments (id, workspace_id, project_id, campaign_id, ref, day, platform, region_code, version_label, language, "
            "script, code_mixed, text, likes, source_kind, dataset_version, last_updated_at, video_id, external_id, published_at, reply_count) "
            "VALUES (?, ?, ?, ?, ?, '2026-11-02', 'youtube', 'IN-TN', 'v1', 'ta', 'Taml', 0, 'text', 3, ?, 'v', ?, 'dQw4w9WgXcQ', ?, ?, ?)")
        ok = (uuid4().hex, workspace, project, campaign, "yt-aaaaaaaaaa", "youtube", NOW, "UgxOne", NOW, 2)
        conn.execute(comment, ok)
        for bad, why in (
            ((uuid4().hex, workspace, project, campaign, "yt-bbbbbbbbbb", "youtube", NOW, "UgxOne", NOW, 2), "one row per YouTube comment id"),
            ((uuid4().hex, workspace, project, campaign, "yt-aaaaaaaaaa", "youtube", NOW, "UgxTwo", NOW, 2), "a ref is unique per campaign and source"),
            ((uuid4().hex, workspace, project, campaign, "yt-cccccccccc", "tiktok", NOW, "UgxThree", NOW, 2), "source_kind is checked"),
            ((uuid4().hex, workspace, project, campaign, "yt-dddddddddd", "youtube", NOW, "UgxFour", NOW, -1), "replies cannot be negative"),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(comment, bad)
            print("refused:", why)
        analysis = (
            "INSERT INTO pulse_comment_analyses (id, workspace_id, project_id, campaign_id, dataset_version, source_kind, mode, status, prompt_version, "
            "provider, comment_count, read_count, dropped, labels, themes, notes, created_at) "
            "VALUES (?, ?, ?, ?, 'v', ?, 'live', 'completed', 'comment-read-yt-v1', 'p', 1, 1, '{}', '{}', '[]', '[]', ?)")
        conn.execute(analysis, (uuid4().hex, workspace, project, campaign, "youtube", NOW))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(analysis, (uuid4().hex, workspace, project, campaign, "tiktok", NOW))
        source = (
            "INSERT INTO pulse_youtube_sources (id, workspace_id, project_id, campaign_id, video_id, version_label, region_code, comment_order, "
            "pages_fetched, truncated, fetched_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)")
        conn.execute(source, (uuid4().hex, workspace, project, campaign, "dQw4w9WgXcQ", "Campaign video", "IN-TN", "relevance", 1, NOW, NOW))
        for bad, why in (
            ((uuid4().hex, workspace, project, campaign, "dQw4w9WgXcQ", "Other", "IN-KL", "time", 1, NOW, NOW), "one source row per video and campaign"),
            ((uuid4().hex, workspace, project, campaign, "9bZkp7q19f0", "Campaign video", "IN-TN", "time", 1, NOW, NOW), "one video per version and region"),
            ((uuid4().hex, workspace, project, campaign, "9bZkp7q19f0", "Other", "IN-KL", "random", 1, NOW, NOW), "the order is relevance or time"),
            ((uuid4().hex, workspace, project, campaign, "9bZkp7q19f0", "Other", "IN-KL", "time", 0, NOW, NOW), "a fetch reads at least one page"),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(source, bad)
            print("refused:", why)

    command.downgrade(cfg, "0026")
    assert "pulse_youtube_sources" not in tables(db) and "video_id" not in columns(db, "pulse_comments")
    assert "source_kind" not in columns(db, "pulse_comment_analyses")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT ref, source_kind FROM pulse_comments").fetchall() == [("cm-0001", "sample")], "YouTube rows go, the sample stays"
        assert conn.execute("SELECT count(*) FROM pulse_comment_analyses").fetchone() == (1,)
    command.upgrade(cfg, "head")
