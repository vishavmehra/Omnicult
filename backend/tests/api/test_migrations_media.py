"""Migration 0014 (media stream) on a database that already holds assets: nothing is lost going up, and going down drops
only what the old schema cannot hold."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[2]
NOW = "2026-11-17 12:00:00.000000"


def config(path: Path) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path.as_posix()}")
    cfg.attributes["configure_logging"] = False
    return cfg


def rows(db: Path, sql: str) -> list[tuple]:
    with sqlite3.connect(db) as conn:
        return conn.execute(sql).fetchall()


def run(db: Path, sql: str, *args: object) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(sql, args)


def add_asset(db: Path, project: str, kind: str, *, parent: str | None = None, extra: bool = False) -> str:
    asset_id = uuid4().hex
    columns = "id, project_id, kind, filename, content_type, size_bytes, sha256, storage_name, created_at"
    values: list[object] = [asset_id, project, kind, f"{kind}.bin", "application/octet-stream", 3, "0" * 64, f"k/{asset_id}", NOW]
    if extra:  # the 0014 columns
        columns += ", parent_asset_id, derived_role"
        values += [parent, "keyframe" if parent else None]
    run(db, f"INSERT INTO assets ({columns}) VALUES ({', '.join('?' * len(values))})", *values)
    run(db, "INSERT INTO asset_blobs (asset_id, project_id, data, created_at) VALUES (?, ?, ?, ?)", asset_id, project, b"abc", NOW)
    return asset_id


def test_existing_assets_survive_and_downgrade_drops_only_video_and_derived_files(tmp_path: Path) -> None:
    db = tmp_path / "media.db"
    cfg = config(db)
    command.upgrade(cfg, "0012")
    project = uuid4().hex
    run(db, "INSERT INTO projects (id, owner_id, name, mode, status, target_markets, created_at, updated_at) "
            "VALUES (?, ?, 'P', 'live', 'active', '[]', ?, ?)", project, uuid4().hex, NOW, NOW)
    image = add_asset(db, project, "image")
    legacy_audio = add_asset(db, project, "audio")  # the old CHECK allowed audio rows even though uploads were refused

    command.upgrade(cfg, "0014")
    (row,) = rows(db, f"SELECT kind, upload_status, processing_status, rights_confirmed, parent_asset_id, duration_ms FROM assets WHERE id = '{image}'")
    assert row == ("image", "stored", "not_required", 0, None, None)  # existing rows read as stored images that need no work
    video = add_asset(db, project, "video", extra=True)
    add_asset(db, project, "image", parent=video, extra=True)  # a keyframe of the video
    add_asset(db, project, "audio", parent=video, extra=True)
    run(db, "INSERT INTO agent_runs (id, project_id, run_type, status, mode, inputs, steps, created_at, attempt) "
            "VALUES (?, ?, 'creative_xray', 'completed', 'live', '{}', '[]', ?, 0)", uuid4().hex, project, NOW)
    with pytest.raises(sqlite3.IntegrityError):  # the CHECK constraints are real
        add_asset(db, project, "gif", extra=True)
    with pytest.raises(sqlite3.IntegrityError):
        run(db, "UPDATE assets SET processing_status = 'finished' WHERE id = ?", image)
    assert {r[0] for r in rows(db, "SELECT name FROM sqlite_master WHERE type = 'table'")} >= {"creative_assets", "creative_scenes"}

    command.downgrade(cfg, "0012")
    left = {r[0] for r in rows(db, "SELECT id FROM assets")}
    assert left == {image, legacy_audio}  # the video and everything derived from it are gone, with their bytes
    assert {r[0] for r in rows(db, "SELECT asset_id FROM asset_blobs")} == left
    assert rows(db, "SELECT count(*) FROM agent_runs") == [(0,)]
    assert not {"creative_assets", "creative_scenes"} & {r[0] for r in rows(db, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    command.upgrade(cfg, "head")  # and up again
    assert {r[0] for r in rows(db, "SELECT id FROM assets")} == left
