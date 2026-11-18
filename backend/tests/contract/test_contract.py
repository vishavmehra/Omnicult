"""Contract guard: the committed OpenAPI document is current."""

import json
from pathlib import Path

from app.main import create_app

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def test_openapi_is_current() -> None:
    committed = json.loads((CONTRACTS / "openapi.json").read_text(encoding="utf-8"))
    assert committed == create_app().openapi(), "Regenerate: uv run python -m scripts.export_openapi"
