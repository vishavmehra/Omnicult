"""The seeded demo scenario (Northstar, Japan) built from tests/fixtures/northstar, plus small test helpers."""

import json
import re
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings
from app.schemas.campaigns import Campaign
from app.schemas.projects import Project
from app.workflows import BrandContext, WorkflowContext, build_workflow_deps

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "northstar"
PROJECT = Project.model_validate_json((FIXTURES / "Project.json").read_bytes())
CAMPAIGN = Campaign.model_validate_json((FIXTURES / "Campaign.json").read_bytes())
CONTENT = CAMPAIGN.current_version.content
VERSION_ID = CAMPAIGN.current_version.id
JP = CAMPAIGN.target_markets[0]
BRAND = BrandContext(**PROJECT.brand.model_dump(exclude={"id", "updated_at"}))
TERMS = ["hiking", "minimal design", "great escape"]


def offline_settings() -> Settings:
    """No .env and blank provider keys: these tests can never reach a paid API."""
    return Settings(_env_file=None, google_cloud_project=None, gemini_api_key=None)


def demo_deps():
    return build_workflow_deps("demo", offline_settings())


def context(mode: str = "demo") -> WorkflowContext:
    return WorkflowContext(run_id=uuid4(), project_id=PROJECT.id, campaign_id=CAMPAIGN.id, mode=mode, brand=BRAND)


class Progress:
    def __init__(self):
        self.calls: list[tuple[str, int, int, str]] = []

    async def __call__(self, stage: str, completed_steps: int, total_steps: int, message: str) -> None:
        self.calls.append((stage, completed_steps, total_steps, message))


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_VOLATILE = {"created_at", "latency_ms", "retrieved_at"}


def normalized(model) -> str:
    """Model dump with run-specific ids (numbered by first appearance) and timings removed."""

    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in _VOLATILE}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value

    text = json.dumps(strip(model.model_dump(mode="json")), sort_keys=True)
    seen: dict[str, str] = {}
    return _UUID.sub(lambda m: seen.setdefault(m.group(0), f"<id{len(seen)}>"), text)
