"""Audience Lab API: Quick Read, Audience Study, Ask the Panel and Risk Check end to end on the fixture provider (demo
projects) and on a scripted provider (live projects): persistence, synthetic labels, grounding, idempotency, roles,
cross-workspace denial, deterministic severity and human finding status. No network, no paid call."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.analytics.panel import describe
from app.core.auth import dev_user_id
from app.core.config import get_settings
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.fixtures.audience_llm import AUDIENCE_RESPONDERS
from app.llm.fixture import FixtureLLMProvider
from app.llm.gateway import Completion, LLMGateway
from app.schemas.common import Usage
from app.services import audience as service
from tests.api.omnicult_support import add_member, client_for, draft, put_claims, seeded, source, workspace_of  # noqa: F401
from tests.api.test_crud import make_campaign, make_project
from tests.api.test_runs import demo_setup
from tests.conftest import BOB

API = "/api/v1"
TERMINAL = ("completed", "partial", "failed", "cancelled")


# --- helpers --------------------------------------------------------------------------------------------------------------


async def finish(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    """Wait for every Audience Lab run to finish, then read the result resource."""
    await service.wait_idle()
    response = await client.get(url)
    assert response.status_code == 200, response.text
    return response.json()


async def post_run(client: httpx.AsyncClient, campaign_id: str, path: str, body: dict[str, Any], **kw: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/campaigns/{campaign_id}/{path}", json=body, **kw)
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["status"] == "queued" and accepted["status_url"].endswith(f"/{accepted['run_id']}")
    return accepted


async def run_and_read(client: httpx.AsyncClient, campaign_id: str, path: str, body: dict[str, Any], **kw: Any) -> dict[str, Any]:
    accepted = await post_run(client, campaign_id, path, body, **kw)
    return await finish(client, accepted["status_url"])


async def add_region_claims(workspace_id: UUID, mode: str = "demo") -> dict[str, Any]:
    """Three IN-MH claims: two observed (two independent sources each: moderate) and one interpretation."""
    observed = draft("marigold", attribute="festive_decor", category="custom", region="IN-MH", kind="observed",
                     text="Marigold garlands are common in Maharashtra festive settings.",
                     sources=[source("wikimedia", source_type="wikidata"), source("curated", source_type="curated_reference")])
    sensitive = draft("cow", attribute="imagery_sensitivity", category="sensitivity", region="IN-MH", kind="observed",
                      text="Cow imagery in commercial settings is sensitive for some audiences.",
                      sources=[source("wikimedia2", source_type="wikidata", identifier="wd:cow"),
                               source("curated2", source_type="curated_reference", identifier="cur:cow")])
    guess = draft("puns", attribute="humour_style", category="humour", region="IN-MH", kind="interpretation", sources=[],
                  text="Wordplay in Marathi may read as informal.")
    await put_claims(workspace_id, [observed, sensitive, guess], mode=mode)
    return {"observed": observed.value_text, "sensitive": sensitive.value_text, "guess": guess.value_text}


async def demo_campaign(client: httpx.AsyncClient, label: str = "alice") -> tuple[dict, dict, UUID]:
    project, campaign, _ = await demo_setup(client)
    return project, campaign, await workspace_of(label)


class Metered(FixtureLLMProvider):
    """A provider named `metered` (so the gateway treats it as live) that reports token usage and records every request."""

    name = "metered"

    def __init__(self, responders: dict[str, Callable]) -> None:
        super().__init__(responders)
        self.contexts: list[tuple[str, Any]] = []

    async def complete(self, request):
        self.contexts.append((request.prompt_version, request.fixture_context))
        done = await super().complete(request)
        return Completion(text=done.text, usage=Usage(input_tokens=10, output_tokens=20, total_tokens=30))


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Live projects with a scripted provider: tests put responders in `live.responders` (prompt version -> function)."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "qa-test-project")  # Vertex AI is configured; every call is faked
    for tier in ("GEMINI_MODEL_FAST", "GEMINI_MODEL_DEFAULT", "GEMINI_MODEL_REASONING"):
        monkeypatch.setenv(tier, "test-model")
    get_settings.cache_clear()
    state = SimpleNamespace(responders={}, provider=None)
    state.provider = Metered(state.responders)
    original = service.make_llm
    monkeypatch.setattr(service, "make_llm", lambda mode: original(mode) if mode == "demo" else
                        LLMGateway(get_settings(), provider=state.provider, backoff_seconds=0))
    return state


async def live_campaign(client: httpx.AsyncClient, **project: Any) -> tuple[dict, dict]:
    p = await make_project(client, **project)
    return p, await make_campaign(client, p["id"], {"headline": "Festive gifts for the whole family", "body": "Sweets and savouries, fresh.",
                                                   "call_to_action": "Order now"})


# --- Quick Read -----------------------------------------------------------------------------------------------------------


async def test_quick_read_on_a_demo_project_is_grounded_persisted_and_labelled_synthetic(seeded, client: httpx.AsyncClient) -> None:
    project, campaign, ws = await demo_campaign(client)
    texts = await add_region_claims(ws)
    result = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 12,
                                                                        "intended_message": "Festive gifts for families"})
    assert result["status"] == "completed" and result["mode"] == "demo" and result["kind"] == "quick_read"
    assert result["region"] == {"code": "IN-MH", "name": "Maharashtra"} and result["content_version_id"] == campaign["current_version"]["id"]
    assert result["creative"]["headline"] == campaign["current_version"]["content"]["headline"]
    assert result["progress"]["stage"] == "completed" and "(demo fixtures)" in result["progress"]["message"]

    panel = result["panel"]
    assert panel["requested_size"] == 12 and panel["generated_size"] == 12 and panel["seed"] == 42
    assert [s["code"] for s in panel["states"]] == ["IN-MH"] and panel["languages"] == ["mr", "hi", "en"]
    assert panel["city_tiers"] == ["tier1", "tier2", "tier3", "rural"] and panel["sampling_version"] == "panel-v1"
    assert all(max(v.values()) - min(v.values()) <= 1 for v in panel["marginal_counts"].values())
    assert "not statistically representative" in panel["method"]

    people = result["participants"]
    assert len(people) == 12 and [p["ordinal"] for p in people] == list(range(12))
    for p in people:
        assert p["is_synthetic"] is True and p["state_code"] == "IN-MH" and p["response"]["is_synthetic"] is True
        assert p["persona"] == describe("Maharashtra", p["language_name"], p["city_tier"], p["age_band"])
        assert set(p["traits"]) == {"adoption_style", "price_sensitivity", "media_habit", "tone_preference"}
        resp = p["response"]
        assert resp["first_reaction"] and resp["message"]["restated"] and resp["follow_up_question"]
        assert resp["message"]["survival"] in ("understood", "partial", "misunderstood")
    assert result["disclosure"] == {
        "is_synthetic": True, "independent_human_sample": False, "statistically_representative": False,
        "description": result["disclosure"]["description"], "shared_model_note": result["disclosure"]["shared_model_note"]}
    assert "not a survey" in result["disclosure"]["description"]

    summary = result["summary"]
    assert summary["message_survival"]["denominator"] == 12 and summary["sentiment"]["denominator"] == 12
    assert summary["dimension_results"]["clarity"]["n"] == 12 and summary["suggested_follow_ups"]

    grounding = result["grounding"]
    assert grounding["claims_supplied"] == 3 and grounding["region_codes"] == ["IN-MH"] and "IN-MH" in grounding["evidence_strength"]
    kinds = {c["value_text"]: c["kind"] for c in grounding["claims"]}
    assert kinds[texts["observed"]] == "observed" and kinds[texts["guess"]] == "interpretation"
    supported = [pt for p in people for pt in p["response"]["regional_concerns"] if pt["basis"] == "claim_supported"]
    assert supported and all(set(pt["claim_kinds"]) & {"observed", "calculated"} for pt in supported)
    assert set(grounding["cited_claim_ids"]) <= {c["id"] for c in grounding["claims"]}
    interpretation = [pt for p in people for key in ("positives", "negatives", "confusion", "regional_concerns")
                      for pt in p["response"][key] if pt["basis"] == "interpretation"]
    assert interpretation and all(pt["label"] == "synthetic" for pt in interpretation)
    assert not any(pt["basis"] == "observed" for p in people for pt in p["response"]["regional_concerns"])  # never labelled observed

    meta = result["run_metadata"]
    assert meta["prompt_versions"] == ["quick-read-v1"] and meta["providers"] == ["fixture"] and meta["model_ids"] == []
    assert meta["seed"] == 42 and meta["usage"]["model_stages"] == 0 and meta["usage"]["estimated_cost_usd"] is None
    assert [s["stage"] for s in meta["steps"]] == ["loading_context", "generating_reactions", "aggregating_results"]
    assert any("fixture" in lim.lower() for lim in result["limitations"]) and any("real people" in lim for lim in result["limitations"])

    async with read_session() as s:
        rows = (await s.execute(select(m.PanelParticipant).where(m.PanelParticipant.run_id == UUID(result["id"])))).scalars().all()
        run = await s.get(m.AudienceRun, UUID(result["id"]))
    assert len(rows) == 12 and all(r.is_synthetic and r.response for r in rows)
    assert run.config["region_code"] == "IN-MH" and run.inputs["panel"]["seed"] == 42 and run.version_ref is None


async def test_quick_read_lists_and_is_scoped_to_the_campaign(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    first = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-TN", "size": 6})
    page = (await client.get(f"{API}/campaigns/{campaign['id']}/quick-reads")).json()
    assert page["total"] == 1 and page["items"][0]["id"] == first["id"] and page["items"][0]["participant_count"] == 6
    assert page["items"][0]["region_codes"] == ["IN-TN"] and page["items"][0]["kind"] == "quick_read"
    assert (await client.get(f"{API}/campaigns/{campaign['id']}/risk-checks")).json()["total"] == 0
    assert (await client.get(f"{API}/campaigns/{campaign['id']}/risk-checks/{first['id']}")).status_code == 404  # wrong kind


async def test_the_language_and_region_affect_the_panel(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    tn = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-TN", "size": 6, "sampling": {"languages": ["ta"]}})
    assert {p["language"] for p in tn["participants"]} == {"ta"} and {p["state_code"] for p in tn["participants"]} == {"IN-TN"}
    assert tn["region"]["name"] == "Tamil Nadu" and tn["panel"]["languages"] == ["ta"]
    kl = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-KL", "size": 6})
    assert kl["panel"]["languages"] == ["ml", "en"] and "Kerala" in kl["participants"][0]["persona"]


async def test_quick_read_is_reproducible_for_the_same_seed(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    a = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 8, "seed": 11})
    b = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 8, "seed": 11})
    c = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 8, "seed": 12})
    key = lambda r: [(p["language"], p["city_tier"], p["age_band"], p["response"]["sentiment"]) for p in r["participants"]]  # noqa: E731
    assert key(a) == key(b) and key(a) != key(c) and a["id"] != b["id"]


async def test_a_run_with_no_region_claims_says_so_and_labels_every_statement_an_interpretation(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    result = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-KL", "size": 6})
    assert result["grounding"]["claims_supplied"] == 0
    points = [pt for p in result["participants"] for key in ("positives", "negatives", "confusion", "regional_concerns")
              for pt in p["response"][key]]
    assert points and all(pt["basis"] == "interpretation" and pt["claim_ids"] == [] for pt in points)
    assert any("model interpretation" in lim for lim in result["limitations"])


async def test_demo_runs_never_read_live_claims_and_live_runs_never_read_demo_claims(seeded, client: httpx.AsyncClient, live) -> None:
    ws = await workspace_of("alice")
    await put_claims(ws, [draft("a", attribute="live_only", category="custom", region="IN-MH", kind="interpretation", sources=[],
                                text="A live-only statement.")], mode="live")
    await put_claims(ws, [draft("b", attribute="demo_only", category="custom", region="IN-MH", kind="interpretation", sources=[],
                                text="A demo-only statement.")], mode="demo")
    _, demo, _ = await demo_setup(client)
    demo_result = await run_and_read(client, demo["id"], "quick-reads", {"region_code": "IN-MH", "size": 6})
    assert [c["value_text"] for c in demo_result["grounding"]["claims"]] == ["A demo-only statement."]
    live.responders["quick-read-v1"] = AUDIENCE_RESPONDERS["quick-read-v1"]
    _, campaign = await live_campaign(client)
    live_result = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 6})
    assert live_result["mode"] == "live" and [c["value_text"] for c in live_result["grounding"]["claims"]] == ["A live-only statement."]


async def test_a_live_run_records_the_model_prompt_version_usage_and_metering(seeded, client: httpx.AsyncClient, live) -> None:
    live.responders["quick-read-v1"] = AUDIENCE_RESPONDERS["quick-read-v1"]
    project, campaign = await live_campaign(client)
    result = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 12, "version_ref": "node:v3"})
    meta = result["run_metadata"]
    assert result["status"] == "completed" and result["mode"] == "live" and result["version_ref"] == "node:v3"
    assert meta["providers"] == ["metered"] and meta["model_ids"] == ["test-model"] and meta["prompt_versions"] == ["quick-read-v1"]
    assert meta["usage"]["input_tokens"] == 20 and meta["usage"]["output_tokens"] == 40 and meta["usage"]["model_stages"] == 1
    assert meta["usage"]["estimated_cost_usd"] is None and "estimate" in meta["usage"]["cost_note"].lower()
    assert meta["seed"] == 42 and meta["usage"]["model_stages"] == 1
    async with read_session() as s:
        events = (await s.execute(select(m.AiUsageEvent).where(m.AiUsageEvent.campaign_id == UUID(campaign["id"])))).scalars().all()
    assert len(events) == 1 and events[0].provider == "metered" and events[0].model == "test-model"
    assert events[0].prompt_version == "quick-read-v1" and (events[0].input_tokens, events[0].output_tokens) == (20, 40)
    assert events[0].project_id == UUID(project["id"]) and events[0].user_id is not None


async def test_a_failed_live_run_reports_the_error_and_keeps_the_panel_without_responses(seeded, client: httpx.AsyncClient, live) -> None:
    live.responders["quick-read-v1"] = lambda ctx: None
    _, campaign = await live_campaign(client)
    result = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 6})
    assert result["status"] == "failed" and result["error"]["stage"] == "generating_reactions" and result["error"]["code"] == "PROVIDER_ERROR"
    assert "retrying is safe" in result["error"]["message"] and result["summary"] is None
    assert len(result["participants"]) == 6 and all(p["response"] is None for p in result["participants"])
    asked = await client.post(f"{API}/campaigns/{campaign['id']}/panels/{result['id']}/questions",
                              json={"question": "Why?", "target": {"kind": "panel"}})
    assert asked.status_code == 409  # a panel with no usable responses cannot be asked


async def test_a_live_project_without_a_provider_is_refused_not_faked(seeded, client: httpx.AsyncClient) -> None:
    _, campaign = await live_campaign(client)
    response = await client.post(f"{API}/campaigns/{campaign['id']}/quick-reads", json={"region_code": "IN-MH"})
    assert response.status_code == 503 and response.json()["error"]["code"] == "PROVIDER_NOT_CONFIGURED"
    assert (await client.get(f"{API}/campaigns/{campaign['id']}/quick-reads")).json()["total"] == 0


async def test_quick_read_requests_are_validated(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    url = f"{API}/campaigns/{campaign['id']}/quick-reads"

    async def reject(body: dict[str, Any], field: str, text: str = "") -> None:
        response = await client.post(url, json=body)
        assert response.status_code == 422, (body, response.text)
        details = response.json()["error"]["details"]
        assert any(d["field"] and d["field"].startswith(field) and text in d["message"] for d in details), (field, details)

    await reject({"region_code": "IN-MH", "sampling": {"religion": ["x"]}}, "sampling", "protected trait")
    await reject({"region_code": "IN-MH", "sampling": {"caste": ["x"]}}, "sampling", "protected trait")
    await reject({"region_code": "IN-MH", "sampling": {"weights": {"health": {"a": 1}}}}, "sampling", "protected trait")
    await reject({"region_code": "IN-MH", "sampling": {"states": ["IN-TN"]}}, "sampling.states", "one region")
    await reject({"region_code": "IN-ZZ"}, "region_code", "not a known")
    await reject({"region_code": "IN-MH", "size": 25}, "size", "limited to 24")
    await reject({"region_code": "IN-MH", "size": 5}, "size")
    await reject({"region_code": "IN-MH", "sampling": {"languages": ["xx"]}}, "sampling.languages", "Unknown language")
    await reject({"region_code": "IN-MH", "sampling": {"city_tiers": ["tier9"]}}, "sampling.city_tiers")
    await reject({"region_code": "IN-MH", "seed": -1}, "seed")
    await reject({"region_code": "IN-MH", "extra_field": 1}, "extra_field")
    other = await make_campaign(client, (await make_project(client))["id"])
    conflict = await client.post(url, json={"region_code": "IN-MH", "content_version_id": other["current_version"]["id"]})
    assert conflict.status_code == 409
    assert (await client.post(f"{API}/campaigns/{uuid4()}/quick-reads", json={"region_code": "IN-MH"})).status_code == 404
    assert (await client.get(f"{API}/campaigns/{campaign['id']}/quick-reads")).json()["total"] == 0  # nothing was started


async def test_the_server_limits_bound_panel_sizes(seeded, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _, campaign, _ = await demo_campaign(client)
    monkeypatch.setenv("AUDIENCE_QUICK_READ_MAX_PARTICIPANTS", "8")
    monkeypatch.setenv("AUDIENCE_STUDY_MAX_PARTICIPANTS", "30")
    get_settings.cache_clear()
    assert (await client.post(f"{API}/campaigns/{campaign['id']}/quick-reads", json={"region_code": "IN-MH", "size": 9})).status_code == 422
    assert (await client.post(f"{API}/campaigns/{campaign['id']}/audience-studies",
                              json={"sampling": {"states": ["IN-MH"]}, "size": 31})).status_code == 422
    options = (await client.get(f"{API}/audience-lab/sampling-options")).json()
    assert options["limits"]["quick_read_max_participants"] == 8 and options["limits"]["audience_study_max_participants"] == 30


# --- idempotency, access and roles ------------------------------------------------------------------------------------------


async def test_a_retried_start_with_the_same_idempotency_key_returns_the_same_run(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    body, headers = {"region_code": "IN-MH", "size": 6}, {"Idempotency-Key": "qr-2026-11-17:mh"}
    first = await post_run(client, campaign["id"], "quick-reads", body, headers=headers)
    retry = await client.post(f"{API}/campaigns/{campaign['id']}/quick-reads", json=body, headers=headers)
    assert retry.status_code == 202 and retry.json()["run_id"] == first["run_id"]
    await finish(client, first["status_url"])
    later = await client.post(f"{API}/campaigns/{campaign['id']}/quick-reads", json=body, headers=headers)
    assert later.json()["run_id"] == first["run_id"] and later.json()["status"] == "completed"
    assert (await client.get(f"{API}/campaigns/{campaign['id']}/quick-reads")).json()["total"] == 1
    other_kind = await client.post(f"{API}/campaigns/{campaign['id']}/risk-checks", json={"region_code": "IN-MH"}, headers=headers)
    assert other_kind.status_code == 409 and "Idempotency-Key" in other_kind.json()["error"]["message"]
    fresh = await post_run(client, campaign["id"], "quick-reads", body)  # no key: a new run
    assert fresh["run_id"] != first["run_id"]
    await finish(client, fresh["status_url"])
    bad = await client.post(f"{API}/campaigns/{campaign['id']}/quick-reads", json=body, headers={"Idempotency-Key": "no spaces!"})
    assert bad.status_code == 422


async def test_other_workspaces_cannot_see_or_use_a_campaign(seeded, client: httpx.AsyncClient, client_for) -> None:
    _, campaign, _ = await demo_campaign(client)
    quick = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 6})
    risk = await run_and_read(client, campaign["id"], "risk-checks", {"region_code": "IN-MH"})
    bob, base = client_for(BOB), f"{API}/campaigns/{campaign['id']}"
    finding_url = f"{base}/risk-checks/{risk['id']}/findings"
    denied = [
        await bob.post(f"{base}/quick-reads", json={"region_code": "IN-MH"}),
        await bob.post(f"{base}/audience-studies", json={"sampling": {"states": ["IN-MH"]}, "size": 20}),
        await bob.post(f"{base}/risk-checks", json={"region_code": "IN-MH"}),
        await bob.get(f"{base}/quick-reads"), await bob.get(f"{base}/quick-reads/{quick['id']}"),
        await bob.get(f"{base}/risk-checks/{risk['id']}"), await bob.get(finding_url),
        await bob.get(f"{base}/panels/{quick['id']}/participants"), await bob.get(f"{base}/panels/{quick['id']}/questions"),
        await bob.post(f"{base}/panels/{quick['id']}/questions", json={"question": "Why?", "target": {"kind": "panel"}}),
        await bob.patch(f"{finding_url}/{uuid4()}", json={"status": "fixed"}),
    ]
    assert [r.status_code for r in denied] == [404] * len(denied)
    assert all(quick["id"] not in r.text for r in denied)
    # Bob's own campaign cannot reach Alice's run through his campaign id either.
    mine = await make_campaign(bob, (await make_project(bob))["id"])
    assert (await bob.get(f"{API}/campaigns/{mine['id']}/quick-reads/{quick['id']}")).status_code == 404
    assert (await bob.get(f"{API}/campaigns/{mine['id']}/risk-checks/{risk['id']}/findings")).status_code == 404


async def test_roles_viewers_read_reviewers_decide_editors_run(seeded, client: httpx.AsyncClient, client_for) -> None:
    _, campaign, ws = await demo_campaign(client)
    quick = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 6})
    risk = await run_and_read(client, campaign["id"], "risk-checks", {"region_code": "IN-MH", "elements": [
        {"id": "h", "kind": "headline", "value": "Guaranteed results, better than any rival"}]})
    base, finding = f"{API}/campaigns/{campaign['id']}", risk["findings"][0]["id"]
    await add_member(ws, "bob", "viewer")
    bob = client_for(BOB)
    assert (await bob.get(f"{base}/quick-reads/{quick['id']}")).status_code == 200
    assert (await bob.get(f"{base}/risk-checks/{risk['id']}/findings")).status_code == 200
    for response in (await bob.post(f"{base}/quick-reads", json={"region_code": "IN-MH"}),
                     await bob.post(f"{base}/risk-checks", json={"region_code": "IN-MH"}),
                     await bob.post(f"{base}/audience-studies", json={"sampling": {"states": ["IN-MH"]}, "size": 20}),
                     await bob.post(f"{base}/panels/{quick['id']}/questions", json={"question": "Why?", "target": {"kind": "panel"}}),
                     await bob.patch(f"{base}/risk-checks/{risk['id']}/findings/{finding}", json={"status": "fixed"})):
        assert response.status_code == 403, response.text
    await add_member(ws, "bob", "reviewer")  # a reviewer decides on findings but does not start runs
    assert (await bob.patch(f"{base}/risk-checks/{risk['id']}/findings/{finding}", json={"status": "accepted"})).status_code == 200
    assert (await bob.post(f"{base}/quick-reads", json={"region_code": "IN-MH"})).status_code == 403
    await add_member(ws, "bob", "editor")
    started = await bob.post(f"{base}/quick-reads", json={"region_code": "IN-MH", "size": 6})
    assert started.status_code == 202
    await finish(bob, started.json()["status_url"])


async def test_a_run_past_its_lease_is_reclaimed_so_it_cannot_hold_the_run_quota(seeded, client: httpx.AsyncClient) -> None:
    project, campaign, ws = await demo_campaign(client)
    async with session() as s, s.begin():
        for _ in range(2):  # the default limit is two active runs per user
            s.add(m.AudienceRun(
                id=uuid4(), workspace_id=ws, project_id=UUID(project["id"]), campaign_id=UUID(campaign["id"]), kind="quick_read",
                status="running", mode="demo", created_by=dev_user_id("alice"), created_at=utcnow(), region_codes=["IN-MH"], inputs={}, config={},
                lease_expires_at=utcnow()))
    fresh = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 6})
    assert fresh["status"] == "completed"
    async with read_session() as s:
        stale = (await s.execute(select(m.AudienceRun).where(m.AudienceRun.status == "failed"))).scalars().all()
    assert len(stale) == 2 and all(r.error["code"] == "RUN_INTERRUPTED" and r.completed_at for r in stale)


async def test_a_participant_row_cannot_be_stored_as_non_synthetic(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    quick = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 6})
    with pytest.raises(IntegrityError):
        async with session() as s, s.begin():
            row = await s.get(m.PanelParticipant, UUID(quick["participants"][0]["id"]))
            row.is_synthetic = False


# --- Audience Study ---------------------------------------------------------------------------------------------------------


async def test_audience_study_samples_across_states_and_summarises_by_dimension(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, ws = await demo_campaign(client)
    await add_region_claims(ws)
    result = await run_and_read(client, campaign["id"], "audience-studies", {
        "sampling": {"states": ["IN-MH", "IN-TN"], "languages": ["mr", "ta", "en"], "city_tiers": ["tier1", "tier2", "rural"],
                     "weights": {"city_tiers": {"tier1": 2, "tier2": 1, "rural": 1}}},
        "size": 24, "interview_depth": "brief", "seed": 3})
    assert result["status"] == "completed" and result["kind"] == "audience_study" and result["interview_depth"] == "brief"
    assert result["panel"]["requested_size"] == 24 and result["panel"]["marginal_counts"]["city_tiers"] == {"tier1": 12, "tier2": 6, "rural": 6}
    assert {p["state_code"] for p in result["participants"]} == {"IN-MH", "IN-TN"}
    for p in result["participants"]:
        assert p["is_synthetic"] is True and p["interview"]["is_synthetic"] is True and p["interview"]["status"] == "completed"
        assert len(p["interview"]["answers"]) == 8  # brief: the eight core questions, no follow-ups
    summary = result["summary"]
    assert summary["overall"]["denominator"] == 24 and {s["dimension"] for s in summary["by_dimension"]} == {
        "states", "languages", "city_tiers", "age_bands"}
    assert summary["group_differences"] and summary["next_actions"] and summary["evidence_gaps"]
    assert result["grounding"]["claims_supplied"] == 3 and result["grounding"]["region_codes"] == ["IN-MH", "IN-TN"]
    assert result["run_metadata"]["prompt_versions"] == ["audience-study-interviews-v1", "audience-study-analysis-v1"]
    assert any("not statistically representative" in lim for lim in result["limitations"])
    assert result["disclosure"]["independent_human_sample"] is False
    listed = (await client.get(f"{API}/campaigns/{campaign['id']}/audience-studies")).json()
    assert listed["total"] == 1 and listed["items"][0]["participant_count"] == 24


async def test_audience_study_is_bounded_and_validated(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    url = f"{API}/campaigns/{campaign['id']}/audience-studies"
    for body in ({"sampling": {}, "size": 30}, {"sampling": {"states": ["IN-MH"]}, "size": 19}, {"sampling": {"states": ["IN-MH"]}, "size": 61},
                 {"sampling": {"states": ["IN-ZZ"]}, "size": 30}, {"sampling": {"states": ["IN-MH"], "religion": ["x"]}, "size": 30},
                 {"sampling": {"states": ["IN-MH"]}, "size": 30, "interview_depth": "deep"}):
        assert (await client.post(url, json=body)).status_code == 422, body


# --- Ask the Panel ----------------------------------------------------------------------------------------------------------


async def test_ask_the_panel_supports_one_participant_a_subgroup_and_the_whole_panel_in_demo_mode(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    quick = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 12})
    base, people = f"{API}/campaigns/{campaign['id']}/panels/{quick['id']}", quick["participants"]
    listed = (await client.get(f"{base}/participants")).json()
    assert listed["total"] == 12 and [p["id"] for p in listed["items"]] == [p["id"] for p in people]

    one = await client.post(f"{base}/questions", json={"question": "What would you change?", "target": {"kind": "participant", "participant_id": people[0]["id"]}})
    assert one.status_code == 201, one.text
    one = one.json()
    assert one["target_kind"] == "participant" and len(one["answers"]) == 1 and one["answers"][0]["participant_id"] == people[0]["id"]
    assert one["answers"][0]["is_synthetic"] is True and one["disclosure"]["independent_human_sample"] is False
    assert one["answers"][0]["answer"].startswith("Demo fixture answer") and one["answers"][0]["model_id"] is None
    assert one["answers"][0]["memory_refs"] == [people[0]["id"]]  # cites the stored response, nothing invented
    assert any("no model was called" in lim for lim in one["limitations"]) and one["mode"] == "demo"

    tier = people[0]["city_tier"]
    expected = {p["id"] for p in people if p["city_tier"] == tier}
    group = (await client.post(f"{base}/questions", json={"question": "Would you share it?", "target": {"kind": "subgroup", "filter": {"city_tiers": [tier]}}})).json()
    assert group["target_kind"] == "subgroup" and {a["participant_id"] for a in group["answers"]} == expected
    assert group["target"] == {"filter": {"city_tiers": [tier]}} and group["stance"]["denominator"] == len(expected)
    assert group["unanswered_participant_ids"] == []

    whole = (await client.post(f"{base}/questions", json={"question": "Anything unclear?", "target": {"kind": "panel"}})).json()
    assert {a["participant_id"] for a in whole["answers"]} == {p["id"] for p in people} and len(whole["summaries"]) == 2  # two batches of up to 8
    assert [a["ordinal"] for a in whole["answers"]] == list(range(12))

    history = (await client.get(f"{base}/questions", params={"participant_id": people[0]["id"]})).json()
    assert history["total"] == 3 and [q["target_kind"] for q in history["items"]] == ["panel", "subgroup", "participant"]  # newest first
    assert (await client.get(f"{base}/questions")).json()["total"] == 3


async def test_ask_the_panel_rejects_bad_targets_and_protected_filters(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    quick = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 6})
    other = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-TN", "size": 6})
    url = f"{API}/campaigns/{campaign['id']}/panels/{quick['id']}/questions"
    ask = lambda target, q="Why?": client.post(url, json={"question": q, "target": target})  # noqa: E731
    for filt in ({"religion": ["x"]}, {"caste": ["x"]}, {"health": ["x"]}, {}, {"city_tiers": ["tier9"]}):
        response = await ask({"kind": "subgroup", "filter": filt})
        assert response.status_code == 422, filt
    assert "protected trait" in (await ask({"kind": "subgroup", "filter": {"religion": ["x"]}})).text
    assert (await ask({"kind": "participant", "participant_id": str(uuid4())})).status_code == 404
    assert (await ask({"kind": "participant", "participant_id": other["participants"][0]["id"]})).status_code == 404  # another panel
    assert (await ask({"kind": "subgroup", "filter": {"states": ["IN-GA"]}})).status_code == 409  # nobody matches
    assert (await ask({"kind": "panel"}, q="")).status_code == 422
    assert (await ask({"kind": "everyone"})).status_code == 422
    assert (await client.post(f"{API}/campaigns/{campaign['id']}/panels/{uuid4()}/questions",
                              json={"question": "Why?", "target": {"kind": "panel"}})).status_code == 404


async def test_live_answers_come_from_stored_memory_with_a_stable_identity_and_retained_history(seeded, client: httpx.AsyncClient, live) -> None:
    seen: list[dict] = []

    def followup(ctx):
        seen.append(ctx)
        n = len(seen)
        return {"answer": f"Answer {n}: I would keep the wording.", "stance": "positive", "memory_refs": ["M1", "M2", "M99"]}

    live.responders |= {"quick-read-v1": AUDIENCE_RESPONDERS["quick-read-v1"], "participant-followup-v1": followup}
    _, campaign = await live_campaign(client)
    quick = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 6})
    base, person = f"{API}/campaigns/{campaign['id']}/panels/{quick['id']}", quick["participants"][2]
    target = {"kind": "participant", "participant_id": person["id"]}
    first = (await client.post(f"{base}/questions", json={"question": "Is the tone right?", "target": target})).json()
    second = (await client.post(f"{base}/questions", json={"question": "And the offer?", "target": target})).json()
    profile1, profile2 = seen[0]["participant"], seen[1]["participant"]
    assert person["persona"][:100] in profile1["region"] and profile1["region"] == profile2["region"]  # identity is stable
    assert profile1["current_stance"] == person["response"]["sentiment"]
    texts1 = [mem["text"] for mem in profile1["memories"]]
    assert texts1[0].startswith("First reaction:") and person["response"]["first_reaction"] in texts1[0]  # the stored response is the memory
    texts2 = [mem["text"] for mem in profile2["memories"]]
    assert texts2[0] == "Asked: Is the tone right? I answered: Answer 1: I would keep the wording."  # earlier answers are retained
    assert texts2[1:] == texts1
    assert first["answers"][0]["memory_refs"] == [person["id"]] and first["answers"][0]["model_id"] == "test-model"  # M99 is not stored
    assert second["answers"][0]["memory_refs"] == [first["answers"][0]["id"], person["id"]]
    assert second["usage"]["input_tokens"] == 10 and second["mode"] == "live"
    stored = (await client.get(f"{base}/questions", params={"participant_id": person["id"]})).json()
    assert [q["question"] for q in stored["items"]] == ["And the offer?", "Is the tone right?"]
    async with read_session() as s:
        answers = (await s.execute(select(m.PanelAnswer).where(m.PanelAnswer.participant_id == UUID(person["id"])))).scalars().all()
    assert len(answers) == 2 and all(a.model_id == "test-model" for a in answers)


async def test_a_live_group_question_batches_the_panel_and_reports_unanswered_participants(seeded, client: httpx.AsyncClient, live) -> None:
    def group(ctx):
        rows = ctx["participants"]
        answering = rows[:-1] if len(rows) > 4 else rows  # the model leaves one participant out of the larger batch
        return {"summary": f"{len(answering)} answered.", "answers": [
            {"participant": r["participant"], "answer": f"I am {r['region']}", "stance": "mixed", "memory_refs": ["M1"]} for r in answering]}

    live.responders |= {"quick-read-v1": AUDIENCE_RESPONDERS["quick-read-v1"], "group-question-v1": group}
    _, campaign = await live_campaign(client)
    quick = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 12})
    result = (await client.post(f"{API}/campaigns/{campaign['id']}/panels/{quick['id']}/questions",
                                json={"question": "Thoughts?", "target": {"kind": "panel"}})).json()
    assert len(result["answers"]) == 11 and len(result["unanswered_participant_ids"]) == 1 and len(result["summaries"]) == 2
    assert result["stance"]["denominator"] == 11 and all(a["persona"] in a["answer"] for a in result["answers"])
    assert any("did not get an answer" in lim for lim in result["limitations"])
    calls = [c for v, c in live.provider.contexts if v == "group-question-v1"]
    assert sorted(len(c["participants"]) for c in calls) == [4, 8]  # the panel is asked in batches of at most eight


async def test_a_live_ask_that_fails_everywhere_is_a_provider_error_and_stores_nothing(seeded, client: httpx.AsyncClient, live) -> None:
    live.responders |= {"quick-read-v1": AUDIENCE_RESPONDERS["quick-read-v1"], "group-question-v1": lambda ctx: None}
    _, campaign = await live_campaign(client)
    quick = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 6})
    response = await client.post(f"{API}/campaigns/{campaign['id']}/panels/{quick['id']}/questions",
                                 json={"question": "Thoughts?", "target": {"kind": "panel"}})
    assert response.status_code == 502 and response.json()["error"]["code"] == "PROVIDER_ERROR"
    assert (await client.get(f"{API}/campaigns/{campaign['id']}/panels/{quick['id']}/questions")).json()["total"] == 0


# --- Risk Check -------------------------------------------------------------------------------------------------------------

ELEMENTS = [
    {"id": "h1", "kind": "headline", "value": "Clinically proven: No.1 festive sweets in India", "language": "en", "script": "Latn", "scene_id": "s1"},
    {"id": "b1", "kind": "body", "value": "Gift boxes for the whole family. Free delivery.", "scene_id": "s1", "bbox": [0.1, 0.5, 0.8, 0.2]},
    {"id": "img", "kind": "image_region", "value": {"description": "A cow beside two children lighting fireworks"}, "scene_id": "s2", "bbox": [0.2, 0.2, 0.4, 0.4]},
]
SCENES = [{"id": "s1", "start_ms": 0, "end_ms": 3000}, {"id": "s2", "start_ms": 3000, "end_ms": 6500, "summary": "Festival street"}]


async def test_risk_check_returns_anchored_verified_findings_with_computed_severity(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, ws = await demo_campaign(client)
    texts = await add_region_claims(ws)
    result = await run_and_read(client, campaign["id"], "risk-checks", {
        "region_code": "IN-MH", "elements": ELEMENTS, "scenes": SCENES, "product_category": "packaged sweets", "version_ref": "node:7"})
    assert result["status"] == "completed" and result["kind"] == "risk_check" and result["rules_version"] == "risk-rules-v1"
    assert result["human_review_required"] is True and "not legal advice" in result["disclaimer"] and result["version_ref"] == "node:7"
    assert result["ad_code_index_version"] == "asci-index-v1" and result["product_category"] == "packaged sweets"
    assert [e["id"] for e in result["elements"]] == ["h1", "b1", "img"] and [s["id"] for s in result["scenes"]] == ["s1", "s2"]
    findings = result["findings"]
    assert findings and result["counts"]["total"] == len(findings) and result["counts"]["by_status"]["open"] == len(findings)
    health = next(f for f in findings if f["category"] == "health_nutrition_claim")
    assert health["quote"] == "Clinically proven" and health["verification"] == "quote_verified" and health["source"] == "model_assessment"
    assert ELEMENTS[0]["value"][health["quote_start"]:health["quote_end"]] == "Clinically proven"
    assert health["anchor"] == {"scene_id": "s1", "start_ms": 0, "end_ms": 3000, "bbox": None}
    assert health["observation"] and health["interpretation"] and health["observation"] != health["interpretation"]
    assert {a["id"] for a in health["ad_codes"]} == {"asci-1-1", "asci-1-5-d"} and health["severity"] == "high" and health["blocks_go"] is True
    assert all(a["url"].startswith("https://www.ascionline.in/") and a["excerpt"] for a in health["ad_codes"])
    assert [r["rule"] for r in health["severity_rules"]][:2] == ["R1_base", "R2_ad_code"] and health["rules_version"] == "risk-rules-v1"
    child = next(f for f in findings if f["category"] == "children_safety")
    assert child["element_id"] == "img" and child["quote"] is None and child["verification"] == "element_reference"
    assert child["anchor"] == {"scene_id": "s2", "start_ms": 3000, "end_ms": 6500, "bbox": [0.2, 0.2, 0.4, 0.4]}
    assert {a["id"] for a in child["ad_codes"]} == {"asci-3-2"}
    for f in findings:
        assert f["status"] == "open" and f["status_by"] is None and f["severity_rules"] and f["limitations"]
    assert result["counts"]["blocking_go"] == sum(1 for f in findings if f["blocks_go"]) and result["counts"]["blocking_go"] >= 1
    assert result["grounding"]["claims_supplied"] == 3 and texts["sensitive"] in [c["value_text"] for c in result["grounding"]["claims"]]
    assert result["run_metadata"]["prompt_versions"] == ["risk-check-v1"] and result["run_metadata"]["providers"] == ["fixture"]
    assert any("not a verified violation" in lim for f in findings for lim in f["limitations"])
    assert any("partial set of public ASCI clauses" in lim for lim in result["limitations"])
    for forbidden in ("compliant", "cleared", "approved by", "safe to run"):
        assert forbidden not in " ".join(f["interpretation"] + (f["suggested_fix"] or "") for f in findings).lower()


async def test_risk_check_without_elements_checks_the_campaign_version_text(seeded, client: httpx.AsyncClient, live) -> None:
    live.responders["risk-check-v1"] = lambda ctx: {"findings": [{
        "element": "E1", "quote": "Guaranteed", "category": "unsubstantiated_claim", "observation": "The headline promises a result.",
        "interpretation": "It may need substantiation.", "suggested_fix": None, "ad_codes": [], "claims": []}]}
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"], {"headline": "Guaranteed glow in 7 days", "body": "Free delivery."})
    result = await run_and_read(client, campaign["id"], "risk-checks", {"region_code": "IN-MH"})
    assert result["content_version_id"] == campaign["current_version"]["id"]
    assert [(e["id"], e["kind"]) for e in result["elements"]] == [("headline", "headline"), ("body", "body")]
    model = next(f for f in result["findings"] if f["source"] == "model_assessment")
    assert model["element_id"] == "headline" and model["quote"] == "Guaranteed" and model["severity"] == "medium" and not model["blocks_go"]
    assert model["severity_rules"][-1]["rule"] == "R5_cap" and model["confidence_label"] == "insufficient"


async def test_a_live_risk_check_drops_unverifiable_findings_and_applies_brand_rules(seeded, client: httpx.AsyncClient, live) -> None:
    def findings(ctx):
        base = {"observation": "obs", "interpretation": "It may matter.", "suggested_fix": None, "ad_codes": [], "claims": [], "category": "other"}
        return {"findings": [
            base | {"element": "E1", "quote": "A phrase that is not in the creative"},
            base | {"element": "E7", "quote": "Order now"},
            base | {"element": "E2", "quote": "Order now", "category": "language_ambiguity"},
        ]}

    live.responders["risk-check-v1"] = findings
    project = await make_project(client, prohibited_terms=["cheapest"])
    campaign = await make_campaign(client, project["id"], {"headline": "The cheapest festive gifts", "body": "Order now."})
    result = await run_and_read(client, campaign["id"], "risk-checks", {"region_code": "IN-MH", "elements": [
        {"id": "h", "kind": "headline", "value": "The cheapest festive gifts"}, {"id": "c", "kind": "cta", "value": "Order now"}]})
    assert result["status"] == "completed" and result["mode"] == "live"
    assert result["dropped"] == {"unverified_quote": 1, "unknown_element": 1, "duplicate": 0, "total": 2}
    brand = next(f for f in result["findings"] if f["category"] == "brand_rule")
    assert (brand["severity"], brand["blocks_go"], brand["source"], brand["quote"]) == ("high", True, "deterministic_check", "cheapest")
    model = [f for f in result["findings"] if f["source"] == "model_assessment"]
    assert len(model) == 1 and model[0]["element_id"] == "c" and model[0]["severity"] == "low" and not model[0]["blocks_go"]
    assert result["findings"][0]["id"] == brand["id"] and result["counts"]["blocking_go"] == 1
    assert any("could not be verified" in lim for lim in result["limitations"])
    assert result["run_metadata"]["model_ids"] == ["test-model"] and result["run_metadata"]["usage"]["input_tokens"] == 10


async def test_a_risk_check_whose_model_fails_keeps_the_deterministic_findings_as_partial(seeded, client: httpx.AsyncClient, live) -> None:
    live.responders["risk-check-v1"] = lambda ctx: None
    project = await make_project(client, prohibited_terms=["cheapest"])
    campaign = await make_campaign(client, project["id"], {"headline": "The cheapest festive gifts"})
    result = await run_and_read(client, campaign["id"], "risk-checks", {"region_code": "IN-MH"})
    assert result["status"] == "partial" and result["error"]["stage"] == "assessing_risks" and "Deterministic checks were saved" in result["error"]["message"]
    assert [f["category"] for f in result["findings"]] == ["brand_rule"]


async def test_findings_are_filtered_and_only_people_change_their_status(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, ws = await demo_campaign(client)
    await add_region_claims(ws)
    risk = await run_and_read(client, campaign["id"], "risk-checks", {"region_code": "IN-MH", "elements": ELEMENTS, "scenes": SCENES})
    base = f"{API}/campaigns/{campaign['id']}/risk-checks/{risk['id']}"
    page = (await client.get(f"{base}/findings")).json()
    assert page["total"] == len(risk["findings"]) and [f["ordinal"] for f in page["items"]] == list(range(page["total"]))
    high = (await client.get(f"{base}/findings", params={"severity": "high"})).json()
    assert high["total"] == sum(1 for f in risk["findings"] if f["severity"] == "high")
    assert (await client.get(f"{base}/findings", params={"category": "children_safety"})).json()["total"] == 1
    assert (await client.get(f"{base}/findings", params={"status": "fixed"})).json()["total"] == 0
    assert (await client.get(f"{base}/findings", params={"severity": "critical"})).status_code == 422

    blocking = next(f for f in risk["findings"] if f["blocks_go"])
    patch = lambda fid, body: client.patch(f"{base}/findings/{fid}", json=body)  # noqa: E731
    assert (await patch(blocking["id"], {"status": "dismissed"})).status_code == 422  # a dismissal needs a reason
    assert (await patch(blocking["id"], {"status": "dismissed", "reason": "   "})).status_code == 422
    assert (await patch(blocking["id"], {"status": "bogus"})).status_code == 422
    assert (await patch(uuid4(), {"status": "fixed"})).status_code == 404
    accepted = (await patch(blocking["id"], {"status": "accepted", "reason": "Legal agrees."})).json()
    assert accepted["status"] == "accepted" and accepted["status_reason"] == "Legal agrees." and accepted["status_by"] and accepted["status_at"]
    assert (accepted["severity"], accepted["blocks_go"], accepted["severity_rules"]) == (blocking["severity"], True, blocking["severity_rules"])
    still = (await client.get(base)).json()["counts"]
    assert still["blocking_go"] == sum(1 for f in risk["findings"] if f["blocks_go"])  # accepted still blocks Go until it is fixed
    fixed = (await patch(blocking["id"], {"status": "fixed"})).json()
    dismissed_target = next(f for f in risk["findings"] if f["blocks_go"] and f["id"] != blocking["id"])
    dismissed = (await patch(dismissed_target["id"], {"status": "dismissed", "reason": "Substantiation file attached."})).json()
    assert fixed["status"] == "fixed" and dismissed["status"] == "dismissed" and dismissed["status_reason"] == "Substantiation file attached."
    counts = (await client.get(base)).json()["counts"]
    remaining = sum(1 for f in risk["findings"] if f["blocks_go"]) - 2
    assert counts["blocking_go"] == remaining and counts["by_status"]["fixed"] == 1 and counts["by_status"]["dismissed"] == 1
    reopened = (await patch(blocking["id"], {"status": "open"})).json()
    assert reopened["status"] == "open" and reopened["status_by"] is None and reopened["status_at"] is None
    assert [f["status"] for f in (await client.get(f"{base}/findings", params={"status": "dismissed"})).json()["items"]] == ["dismissed"]
    async with read_session() as s:
        audit = (await s.execute(select(m.AuditLog).where(m.AuditLog.action == "risk_finding.status")
                                 .order_by(m.AuditLog.created_at))).scalars().all()
    assert len(audit) == 4 and audit[0].detail["to"] == "accepted" and audit[0].actor_user_id is not None


async def test_ad_code_and_sampling_reference_endpoints(seeded, client: httpx.AsyncClient) -> None:
    index = (await client.get(f"{API}/ad-codes")).json()
    assert index["dataset"] == "asci-code-index" and len(index["entries"]) >= 40 and index["source"]["sha256"]
    assert "not legal advice" in " ".join(index["limitations"])
    entry = (await client.get(f"{API}/ad-codes/asci-3-2")).json()
    assert entry["clause"] == "3.2" and entry["excerpt"].startswith("Advertisements addressed to children") and entry["url"].endswith(f"#page={entry['pdf_page']}")
    assert (await client.get(f"{API}/ad-codes/asci-9-9")).status_code == 404
    options = (await client.get(f"{API}/audience-lab/sampling-options")).json()
    assert len(options["states"]) == 36 and {"religion", "caste", "health", "gender"} <= set(options["protected_traits"])
    assert options["city_tiers"] == ["tier1", "tier2", "tier3", "rural"] and options["age_bands"] == ["18-24", "25-34", "35-44", "45-54", "55+"]
    assert any(o["code"] == "mr" for o in options["languages"]) and "not statistically representative" in options["note"]
    assert (await client.get(f"{API}/ad-codes", headers={"Authorization": "Bearer "})).status_code in (401, 403)


async def test_risk_check_requests_are_validated(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    url = f"{API}/campaigns/{campaign['id']}/risk-checks"
    good = {"id": "a", "kind": "headline", "value": "Hello"}
    for body in (
        {"region_code": "IN-ZZ"}, {"region_code": "IN-MH", "elements": []}, {"region_code": "IN-MH", "elements": [good, good]},
        {"region_code": "IN-MH", "elements": [{**good, "kind": "banner"}]}, {"region_code": "IN-MH", "elements": [{**good, "bbox": [0, 0, 2, 1]}]},
        {"region_code": "IN-MH", "elements": [{**good, "bbox": [0.5, 0.5, 0.6, 0.6]}]}, {"region_code": "IN-MH", "elements": [{**good, "bbox": [0, 0, 1]}]},
        {"region_code": "IN-MH", "elements": [good], "scenes": [{"id": "s", "start_ms": 5, "end_ms": 1}]},
        {"region_code": "IN-MH", "elements": [good], "content_version_id": campaign["current_version"]["id"]},
        {"region_code": "IN-MH", "elements": [{**good, "value": "x" * 5001}]}, {"region_code": "IN-MH", "elements": [{**good, "extra": 1}]},
        {"region_code": "IN-MH", "elements": [good] * 61},
    ):
        assert (await client.post(url, json=body)).status_code == 422, body
    assert (await client.get(f"{url}")).json()["total"] == 0
