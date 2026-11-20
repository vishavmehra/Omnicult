"""Settings block and WorkflowDeps wiring for the culture layer."""

from app.core.config import Settings
from app.integrations.culture import CultureService
from app.workflows import build_workflow_deps
from app.workflows.types import WorkflowDeps


def settings(**kw) -> Settings:
    return Settings(_env_file=None, app_env="test", **kw)


def test_culture_settings_defaults_and_blank_keys_mean_unset():
    s = settings(data_gov_in_api_key="  ", data_commons_api_key=" ", youtube_api_key="")
    assert s.culture_http_timeout_seconds == 15 and s.data_gov_in_api_key is None and s.data_commons_api_key is None and s.youtube_api_key is None
    assert s.wikimedia_user_agent.startswith("CultureDataClient/") and "@" not in s.wikimedia_user_agent  # names no person
    keyed = settings(youtube_api_key="zq-test-key-7731")
    assert keyed.youtube_api_key.get_secret_value() == "zq-test-key-7731"
    assert "zq-test-key-7731" not in repr(keyed)  # secrets never print


def test_workflow_deps_carries_a_culture_service():
    demo = build_workflow_deps("demo", settings())
    assert isinstance(demo.culture, CultureService) and demo.culture.mode == "fixture"
    live = build_workflow_deps("live", settings())
    assert live.culture.mode == "live"
    assert live.culture.skipped_sources() == ["gemini_grounding"]  # no grounded_research capability configured


def test_existing_call_sites_that_omit_culture_still_work():
    assert WorkflowDeps(llm=None).culture is None  # type: ignore[arg-type]
