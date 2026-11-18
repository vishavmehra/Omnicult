"""Migration 0029 (Live Pulse Tier 3): the six tables arrive on top of 0020, enforce their constraints, and go away on downgrade."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[2]
NOW = "2026-11-18 12:00:00.000000"
TABLES = {"pulse_alert_rules", "pulse_alerts", "pulse_alert_events", "pulse_alert_evaluations", "pulse_version_links", "pulse_comparison_snapshots"}


def config(path: Path) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path.as_posix()}")
    cfg.attributes["configure_logging"] = False
    return cfg


def tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_pulse_t3_tables_are_added_by_0029_hold_rows_and_are_dropped_by_the_downgrade(tmp_path: Path) -> None:
    db = tmp_path / "pulse_t3.db"
    cfg = config(db)
    command.upgrade(cfg, "0020")
    assert not TABLES & tables(db)

    command.upgrade(cfg, "0029")
    assert TABLES <= tables(db)
    user, workspace, project, campaign, rule, alert = (uuid4().hex for _ in range(6))
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
            "INSERT INTO pulse_alert_rules (id, project_id, campaign_id, name, alert_type, params, enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, 'CTR', 'ctr_drop', '{}', 1, ?, ?)", (rule, project, campaign, NOW, NOW))
        insert_alert = (
            "INSERT INTO pulse_alerts (id, project_id, campaign_id, rule_id, rule_name, alert_key, alert_type, region_code, version_label, metric, "
            "threshold, observed_value, comparison_value, comparison, window_from, window_to, suggested_action, source_path, dataset_version, "
            "status, opened_at, last_seen_at) VALUES (?, ?, ?, ?, 'CTR', ?, 'ctr_drop', 'IN-KL', 'v1', 'ctr', -0.2, -0.3, 0.01, 'c', "
            "'2026-10-27', '2026-11-14', 'a', '/p', 'd', ?, ?, ?)")
        conn.execute(insert_alert, (alert, project, campaign, rule, "k1", "open", NOW, NOW))
        for statement, args in (
            (insert_alert, (uuid4().hex, project, campaign, rule, "k2", "bogus", NOW, NOW)),  # the status CHECK
            (insert_alert, (uuid4().hex, project, campaign, rule, "k1", "open", NOW, NOW)),  # one row per (campaign, key)
            ("INSERT INTO pulse_alert_events (id, alert_id, campaign_id, at, kind, trigger) VALUES (?, ?, ?, ?, 'deleted', 'user')",
             (uuid4().hex, alert, campaign, NOW)),  # the event kind CHECK
            ("INSERT INTO pulse_alert_rules (id, project_id, campaign_id, name, alert_type, params, enabled, created_at, updated_at) "
             "VALUES (?, ?, ?, 'X', 'comment_backlash', '{}', 1, ?, ?)", (uuid4().hex, project, campaign, NOW, NOW)),  # the alert type CHECK
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(statement, args)
        evaluation = ("INSERT INTO pulse_alert_evaluations (id, project_id, campaign_id, trigger, period_key, dataset_version, evaluated_at, "
                      "rules_evaluated, alerts_found, opened, reopened, resolved, not_evaluated) VALUES (?, ?, ?, 'scheduler', ?, 'd', ?, 1, 1, 1, 0, 0, 0)")
        conn.execute(evaluation, (uuid4().hex, project, campaign, "2026-11-18", NOW))
        with pytest.raises(sqlite3.IntegrityError):  # one scheduled evaluation per campaign and period
            conn.execute(evaluation, (uuid4().hex, project, campaign, "2026-11-18", NOW))
        conn.execute("DELETE FROM pulse_alert_rules WHERE id = ?", (rule,))
        assert conn.execute("SELECT rule_id FROM pulse_alerts WHERE id = ?", (alert,)).fetchone() == (None,)  # the alert outlives its rule
        conn.commit()

    command.downgrade(cfg, "0020")
    assert not TABLES & tables(db)
    command.upgrade(cfg, "head")
    assert TABLES <= tables(db)
