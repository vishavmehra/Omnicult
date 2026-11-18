"""Migration 0019 (Campaign Desk): the brief and Brand Kit tables arrive with their constraints and leave cleanly."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[2]


def config(path: Path) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path.as_posix()}")
    cfg.attributes["configure_logging"] = False
    return cfg


def tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_upgrade_creates_the_desk_tables_and_downgrade_drops_only_them(tmp_path: Path) -> None:
    db = tmp_path / "desk.db"
    cfg = config(db)
    command.upgrade(cfg, "0017")
    assert not {"campaign_briefs", "brand_kit_designs"} & tables(db)
    command.upgrade(cfg, "0019")
    assert {"campaign_briefs", "brand_kit_designs", "campaigns", "brand_kits"} <= tables(db)
    with sqlite3.connect(db) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(campaign_briefs)")}
        unique = [r for r in conn.execute("PRAGMA index_list(campaign_briefs)") if r[2]]
    assert {"campaign_id", "project_id", "version_number", "content", "change_note", "provenance", "created_by"} <= columns
    assert unique, "campaign_id and version_number must be unique together"
    command.downgrade(cfg, "0017")
    left = tables(db)
    assert not {"campaign_briefs", "brand_kit_designs"} & left and {"campaigns", "proof_reports"} <= left
