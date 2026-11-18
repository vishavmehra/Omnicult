"""One list of run types, kept in step everywhere it is written down.

`schemas.runs.RunType` is the source of truth. The agent_runs CHECK (models and the migrated database), the run engine's
tables, the Run History labels, the frontend maps and the generated frontend types must all hold exactly the same thirteen
names: today's ten plus `transcreate`, `creative_xray` and `voice_direct`. A type added in one place and forgotten in another
fails here. `voice_direct` is recorded synchronously (one planning call, no queue), so it has no run-engine tables.
"""

import re
import sqlite3
from pathlib import Path
from typing import get_args

from alembic import command
from alembic.config import Config

from app import workflows
from app.db import models
from app.schemas.runs import RunType
from app.services import run_history, runs

BACKEND = Path(__file__).resolve().parents[3]
FRONTEND = BACKEND.parent / "frontend" / "src"
RUN_TYPES = set(get_args(RunType))
SYNCHRONOUS = {"voice_direct"}  # recorded by the service that made the call; never queued, so the run engine has no entry for it
ENGINE_TYPES = RUN_TYPES - SYNCHRONOUS


def names(text: str) -> set[str]:
    return {a or b for a, b in re.findall(r"'([a-z_]+)'|\"([a-z_]+)\"", text)}


def test_the_list_is_ten_types_plus_transcreate_creative_xray_voice_direct_and_remakes() -> None:
    added = {"transcreate", "creative_xray", "voice_direct", "remake_visual", "remake_sound"}
    assert len(RUN_TYPES) == 15
    assert RUN_TYPES >= added
    assert len(RUN_TYPES - added) == 10


def test_the_model_check_constraint_lists_the_same_types() -> None:
    assert names(models.RUN_TYPES) == RUN_TYPES


def test_the_migrated_database_check_constraint_lists_the_same_types(tmp_path: Path) -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{(tmp_path / 'types.db').as_posix()}")
    config.attributes["configure_logging"] = False
    command.upgrade(config, "head")
    with sqlite3.connect(tmp_path / "types.db") as conn:
        (sql,) = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'agent_runs'").fetchone()
    (listed,) = re.findall(r"run_type IN \(([^)]*)\)", sql)
    assert names(listed) == RUN_TYPES


def test_the_run_engine_tables_cover_every_queued_type_and_run_history_every_type() -> None:
    assert set(runs.STAGES) == set(runs.LABELS) == set(runs.ENTRY_POINTS) == ENGINE_TYPES
    assert set(run_history.OPERATIONS) == RUN_TYPES
    assert all(hasattr(workflows, entry) for entry in runs.ENTRY_POINTS.values())


def test_the_frontend_maps_and_generated_types_cover_every_type() -> None:
    meta = (FRONTEND / "features" / "project" / "workflow.ts").read_text(encoding="utf-8")
    block = meta.split("RUN_TYPE_META", 1)[1].split("};", 1)[0]
    assert set(re.findall(r"^\s+(\w+): \{ label:", block, re.M)) == RUN_TYPES
    mock = (FRONTEND / "lib" / "api" / "mock.ts").read_text(encoding="utf-8")
    block = mock.split("const RUNNING_STAGE", 1)[1].split("};", 1)[0]
    assert set(re.findall(r"^\s+(\w+): \"", block, re.M)) == RUN_TYPES
    generated = (FRONTEND / "lib" / "api" / "schema.d.ts").read_text(encoding="utf-8")
    unions = [u for u in re.findall(r"run_type\??: \(([^)]*)\)", generated) if "market_discovery" in u]
    assert unions, "the generated types no longer mention run_type"
    assert all(set(re.findall(r'"([a-z_]+)"', u)) == RUN_TYPES for u in unions)
