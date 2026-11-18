"""Migration 0028 (Launch Room delivery): the tables arrive with their keys and checks and leave cleanly."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[2]
NEW = {"review_links", "review_responses", "asset_packs"}


def config(path: Path) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path.as_posix()}")
    cfg.attributes["configure_logging"] = False
    return cfg


def tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_upgrade_creates_the_delivery_tables_and_downgrade_drops_only_them(tmp_path: Path) -> None:
    db = tmp_path / "delivery.db"
    cfg = config(db)
    command.upgrade(cfg, "0020")
    assert not NEW & tables(db)
    command.upgrade(cfg, "0028")
    assert NEW <= tables(db)
    with sqlite3.connect(db) as conn:
        columns = {t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")} for t in NEW}
        unique = {t: [r[1] for r in conn.execute(f"PRAGMA index_list({t})") if r[2]] for t in ("review_links", "asset_packs")}
        keys = {t: {(r[2], r[3], r[4]) for r in conn.execute(f"PRAGMA foreign_key_list({t})")} for t in NEW}
    assert {"token_hash", "token_hint", "items", "expires_at", "revoked_at", "revoked_by"} <= columns["review_links"]
    assert {"link_id", "version_id", "region_code", "decision", "comment", "reviewer_name", "reviewer_kind"} <= columns["review_responses"]
    assert {"approval_id", "storage_key", "data", "manifest", "token_hash", "expires_at", "sha256"} <= columns["asset_packs"]
    assert all(unique[t] for t in unique), "a token hash is unique"
    assert ("version_nodes", "version_id", "id") in keys["review_responses"] and ("version_nodes", "version_id", "id") in keys["asset_packs"]
    assert ("approvals", "approval_id", "id") in keys["asset_packs"] and ("review_links", "link_id", "id") in keys["review_responses"]
    command.downgrade(cfg, "0020")
    left = tables(db)
    assert not NEW & left and {"version_nodes", "approvals", "campaign_briefs"} <= left
