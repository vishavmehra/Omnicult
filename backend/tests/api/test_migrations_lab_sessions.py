"""Migration 0027 (Audience Lab sessions): the run kinds widen to the union, the session tables arrive with their constraints, and
the downgrade leaves the earlier kinds and their rows alone."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[2]
NEW = {"audience_focus_turns", "audience_focus_interjections", "audience_buzz_acts"}


def config(path: Path) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path.as_posix()}")
    cfg.attributes["configure_logging"] = False
    return cfg


def tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def kinds_check(db: Path) -> str:
    with sqlite3.connect(db) as conn:
        (sql,) = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'audience_runs'").fetchone()
    return sql


def test_upgrade_adds_the_session_tables_and_the_union_of_kinds_and_downgrade_removes_only_them(tmp_path: Path) -> None:
    db = tmp_path / "lab.db"
    cfg = config(db)
    command.upgrade(cfg, "0020")
    assert not NEW & tables(db) and "focus_group" not in kinds_check(db)
    command.upgrade(cfg, "0027")
    assert NEW <= tables(db) and {"audience_runs", "audience_participants"} <= tables(db)
    check = kinds_check(db)
    for kind in ("quick_read", "audience_study", "risk_check", "focus_group", "buzz_sim", "message_check"):
        assert f"'{kind}'" in check
    with sqlite3.connect(db) as conn:
        turns = {r[1] for r in conn.execute("PRAGMA table_info(audience_focus_turns)")}
        acts = {r[1] for r in conn.execute("PRAGMA table_info(audience_buzz_acts)")}
        unique = [r for r in conn.execute("PRAGMA index_list(audience_buzz_acts)") if r[2]]
    assert {"run_id", "turn_index", "round_index", "kind", "participant_id", "reply_to_turn_index", "relation", "stance", "themes", "claim_ids",
            "interjection_id"} <= turns
    assert {"run_id", "round_index", "participant_id", "action", "text", "text_en", "message_gloss", "stance", "parent_act_id", "exposed_by",
            "wording_overlap"} <= acts
    assert unique, "an account acts once per run"
    command.downgrade(cfg, "0020")
    left = tables(db)
    assert not NEW & left and {"audience_runs", "audience_participants", "audience_questions"} <= left
    assert "focus_group" not in kinds_check(db) and "'risk_check'" in kinds_check(db)


def test_the_kind_check_accepts_the_new_kinds_and_refuses_unknown_ones_and_a_turn_needs_a_speaker_only_when_a_participant(tmp_path: Path) -> None:
    db = tmp_path / "check.db"
    command.upgrade(config(db), "0027")
    run, now = str(uuid4()), "2026-11-18 00:00:00"
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        columns = [r[1] for r in conn.execute("PRAGMA table_info(audience_runs)")]
        base = {"id": run, "project_id": str(uuid4()), "campaign_id": str(uuid4()), "kind": "buzz_sim", "status": "queued", "mode": "demo",
                "region_codes": "[]", "config": "{}", "inputs": "{}", "steps": "[]", "limitations": "[]", "created_at": now}

        def insert(**over: object) -> None:
            row = {**base, **over}
            conn.execute(f"INSERT INTO audience_runs ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))

        assert set(base) <= set(columns)
        for kind in ("focus_group", "buzz_sim", "message_check"):
            insert(id=str(uuid4()), kind=kind)
        with pytest.raises(sqlite3.IntegrityError):
            insert(id=str(uuid4()), kind="viral_prediction")
        turn = {"id": str(uuid4()), "run_id": run, "turn_index": 0, "round_index": 0, "text": "q", "themes": "[]", "claim_ids": "[]", "created_at": now}

        def add_turn(**over: object) -> None:
            row = {**turn, "id": str(uuid4()), **over}
            conn.execute(f"INSERT INTO audience_focus_turns ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))

        add_turn(kind="moderator")
        with pytest.raises(sqlite3.IntegrityError):
            add_turn(kind="participant", turn_index=1)  # a participant turn names its speaker
        with pytest.raises(sqlite3.IntegrityError):
            add_turn(kind="moderator", turn_index=2, participant_id=str(uuid4()))  # a moderator turn has none
        with pytest.raises(sqlite3.IntegrityError):
            add_turn(kind="moderator", turn_index=0)  # a turn index is used once per run
        with pytest.raises(sqlite3.IntegrityError):
            add_turn(kind="researcher", turn_index=3, stance="ecstatic")
