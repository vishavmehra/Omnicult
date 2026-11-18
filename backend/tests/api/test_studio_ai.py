"""Tweak Chips and Transcreate in a demo project with the REAL workflows and the fixture LLM provider (no network).

Custom model outputs (a model that drops a protected term, cites a claim it was never given, writes the wrong script)
replace the fixture responders for one test, through the fixture provider's own responder table."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from app.db import models as m
from app.db.session import read_session
from app.fixtures.demo_llm import RESPONDERS
from tests.api.omnicult_support import draft, put_claims, seeded, source, workspace_of  # noqa: F401
from tests.api.offline import offline  # noqa: F401  (blocks outbound HTTP and subprocesses)
from tests.conftest import wait_for_run

API = "/api/v1"
DEMO_ELEMENTS = [
    {"id": "logo", "kind": "logo", "value": "asset:logo-1"},
    {"id": "headline", "kind": "headline", "value": "Happy Diwali", "language": "en", "script": "Latn"},
    {"id": "tagline", "kind": "tagline", "value": "Brighten your home this festive season", "language": "en", "script": "Latn"},
    {"id": "cta", "kind": "cta", "value": "Shop now", "language": "en", "script": "Latn"},
]
NORTHSTAR = [
    {"id": "headline", "kind": "headline", "value": "Happy Diwali from Northstar", "language": "en", "script": "Latn"},
    {"id": "cta", "kind": "cta", "value": "Shop now", "language": "en", "script": "Latn"},
]
FESTIVAL = "Diwali is the main festival season in Maharashtra."


@pytest.fixture(autouse=True)
def no_network(offline: Any) -> Any:  # noqa: F811
    return offline


async def demo_studio(client: httpx.AsyncClient, elements: list[dict[str, Any]] = DEMO_ELEMENTS, claims: bool = True) -> tuple[str, dict[str, Any]]:
    """A demo project (fixture mode), its campaign, a root version, and (by default) a festival claim for IN-MH."""
    project = (await client.post(f"{API}/projects/demo")).json()
    campaign = (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()["items"][0]
    cid = campaign["id"]
    if claims:
        await put_claims(await workspace_of("alice"), [
            draft("Diwali", region="IN-MH", category="festival", sources=[source("wikimedia")], text=FESTIVAL),
        ], mode="demo")
    root = (await client.post(f"{API}/campaigns/{cid}/versions", json={"elements": elements, "region_code": "IN-MH", "language": "en"})).json()
    return cid, root


async def claim_ids() -> list[str]:
    async with read_session() as s:
        return [str(i) for i in (await s.execute(select(m.Claim.id).where(m.Claim.mode == "demo"))).scalars()]


def element_values(version: dict[str, Any]) -> dict[str, Any]:
    return {e["id"]: e["value"] for e in version["elements"]}


def respond(monkeypatch: pytest.MonkeyPatch, prompt_version: str, responder: Callable[[dict[str, Any]], Any]) -> list[dict[str, Any]]:
    """Replace one fixture responder; the returned list collects the context each call received."""
    seen: list[dict[str, Any]] = []

    def wrapped(ctx: Any) -> Any:
        seen.append(dict(ctx))
        return responder(dict(ctx))

    monkeypatch.setitem(RESPONDERS, prompt_version, wrapped)
    return seen


def lines_responder(table: dict[str, tuple[str, str]], claims: list[str] | None = None) -> Callable[[dict[str, Any]], Any]:
    """source text -> (regional copy, back-translation); lines missing from the table are not returned."""
    def responder(ctx: dict[str, Any]) -> Any:
        return {"lines": [
            {"line": handle, "regional_copy": table[line["text"]][0], "back_translation": table[line["text"]][1],
             "explanation": "Test adaptation.", "claims": claims or [], "preserved_terms": []}
            for handle, line in ctx["lines"].items() if line["text"] in table]}
    return responder


async def transcreate(client: httpx.AsyncClient, cid: str, body: dict[str, Any], **headers: str) -> dict[str, Any]:
    response = await client.post(f"{API}/campaigns/{cid}/transcreate", json=body, headers={**dict(client.headers), **headers})
    assert response.status_code == 202, response.text
    return await wait_for_run(client, response.json()["run_id"], timeout=60)


async def operation_of(client: httpx.AsyncClient, cid: str, kind: str = "transcreate", status: str = "applied") -> dict[str, Any]:
    page = (await client.get(f"{API}/campaigns/{cid}/operations", params={"kind": kind, "status": status})).json()
    assert page["total"] == 1, page
    return page["items"][0]


# --- Tweak Chips ----------------------------------------------------------------------------------------


async def test_tweak_chips_are_proposed_from_region_claims_and_applied_through_the_engine(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, root = await demo_studio(client)
    generated = await client.post(f"{API}/campaigns/{cid}/chips/generate", json={"version_id": root["id"], "element_id": "cta", "region_code": "IN-MH"})
    assert generated.status_code == 201, generated.text
    body = generated.json()
    assert body["dropped"] == 0 and len(body["chips"]) == 1
    chip = body["chips"][0]
    assert chip["title"] == "Make the call to action festive" and chip["element_id"] == "cta" and chip["operation_type"] == "replace_text"
    assert chip["change"] == {"value": "Shop the festive range", "from_text": None, "to_text": None}
    assert chip["claim_ids"] == await claim_ids() and chip["reason"] and chip["expected_effect"]
    assert chip["reversible"] is True and chip["status"] == "proposed" and chip["provider"] == "fixture"
    assert chip["prompt_version"] == "tweak-chips-v1" and chip["params"]["region_code"] == "IN-MH"
    assert (await client.get(f"{API}/campaigns/{cid}/chips", params={"element_id": "cta"})).json()["total"] == 1
    applied = await client.post(f"{API}/campaigns/{cid}/chips/{chip['id']}/apply")
    assert applied.status_code == 201, applied.text
    result = applied.json()
    version, operation = result["version"], result["operation"]
    assert version["parent_id"] == root["id"] and element_values(version)["cta"] == "Shop the festive range"
    assert element_values(version)["headline"] == "Happy Diwali" and element_values(root)["cta"] == "Shop now"
    assert operation["kind"] == "apply_chip" and operation["actor"] == "ai" and operation["claim_ids"] == chip["claim_ids"]
    assert operation["prompt_version"] == "tweak-chips-v1" and operation["params"]["chip_id"] == chip["id"] and operation["reason"] == chip["reason"]
    assert result["chip"]["status"] == "applied" and result["chip"]["applied_version_id"] == version["id"] and result["chip"]["applied_operation_id"] == operation["id"]
    assert (await client.post(f"{API}/campaigns/{cid}/chips/{chip['id']}/apply")).status_code == 409  # applied once
    undo = await client.post(f"{API}/campaigns/{cid}/versions/{root['id']}/restore")  # undo = restore the original as a new version
    assert undo.status_code == 201 and element_values(undo.json()["version"])["cta"] == "Shop now"


async def test_a_chip_whose_claim_ids_do_not_exist_is_dropped_in_code(seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cid, root = await demo_studio(client)

    def chips(ctx: dict[str, Any]) -> Any:
        make = lambda title, text, claims: {"title": title, "operation_type": "replace_text", "new_value": text, "reason": "r",  # noqa: E731
                                            "claims": claims, "expected_effect": "e"}
        return {"chips": [make("Real claim", "Shop the festive range", ["C1"]), make("Invented claim", "Shop festive deals", ["C7"]),
                          make("No claim", "Shop festive offers", []), make("Half invented", "Buy festive gifts", ["C1", "C2"])]}

    seen = respond(monkeypatch, "tweak-chips-v1", chips)
    body = (await client.post(f"{API}/campaigns/{cid}/chips/generate", json={"version_id": root["id"], "element_id": "cta", "region_code": "IN-MH"})).json()
    assert [c["title"] for c in body["chips"]] == ["Real claim"] and body["dropped"] == 3 and body["chips"][0]["claim_ids"] == await claim_ids()
    assert body["notes"] and "not supplied" in body["notes"][0]
    assert all("id" not in c for c in seen[0]["claims"])  # the model saw handles, never database ids
    stored = (await client.get(f"{API}/campaigns/{cid}/chips")).json()
    assert stored["total"] == 1  # dropped proposals are not persisted


async def test_chips_that_break_a_glossary_rule_are_dropped_and_swap_chips_apply(seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cid, root = await demo_studio(client, NORTHSTAR)

    def chips(ctx: dict[str, Any]) -> Any:
        base = {"reason": "r", "claims": ["C1"], "expected_effect": "e"}
        return {"chips": [
            {"title": "Drop the brand", "operation_type": "replace_text", "new_value": "Happy Diwali", **base},
            {"title": "Cheap", "operation_type": "replace_text", "new_value": "Cheap Diwali from Northstar", **base},
            {"title": "Different festival", "operation_type": "swap_reference", "from_text": "Diwali", "to_text": "Dussehra", **base}]}

    respond(monkeypatch, "tweak-chips-v1", chips)
    body = (await client.post(f"{API}/campaigns/{cid}/chips/generate", json={"version_id": root["id"], "element_id": "headline", "region_code": "IN-MH"})).json()
    assert [c["title"] for c in body["chips"]] == ["Different festival"] and body["dropped"] == 2
    assert body["chips"][0]["change"] == {"value": None, "from_text": "Diwali", "to_text": "Dussehra"}
    applied = (await client.post(f"{API}/campaigns/{cid}/chips/{body['chips'][0]['id']}/apply")).json()
    assert element_values(applied["version"])["headline"] == "Happy Dussehra from Northstar" and applied["operation"]["params"]["operation_type"] == "swap_reference"


async def test_no_claims_means_no_chips(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, root = await demo_studio(client, claims=False)
    body = (await client.post(f"{API}/campaigns/{cid}/chips/generate", json={"version_id": root["id"], "element_id": "cta", "region_code": "IN-MH"})).json()
    assert body["chips"] == [] and any("No claims are recorded" in n for n in body["notes"])


async def test_locked_elements_get_no_chips_and_a_chip_cannot_be_applied_after_its_element_is_locked(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, root = await demo_studio(client)
    chip = (await client.post(f"{API}/campaigns/{cid}/chips/generate", json={"version_id": root["id"], "element_id": "cta", "region_code": "IN-MH"})).json()["chips"][0]
    await client.put(f"{API}/campaigns/{cid}/locks/cta", json={"reason": "Approved CTA"})
    refused = await client.post(f"{API}/campaigns/{cid}/chips/{chip['id']}/apply")
    assert refused.status_code == 409 and "Locked element" in refused.json()["error"]["message"]
    assert (await client.get(f"{API}/campaigns/{cid}/versions")).json()["total"] == 1
    assert (await client.get(f"{API}/campaigns/{cid}/chips", params={"status": "proposed"})).json()["total"] == 1  # still proposed
    rejected = await operation_of(client, cid, "apply_chip", "rejected")
    assert rejected["rejection"]["code"] == "LOCKED" and rejected["actor"] == "ai" and rejected["target_element_ids"] == ["cta"]
    again = await client.post(f"{API}/campaigns/{cid}/chips/generate", json={"version_id": root["id"], "element_id": "cta", "region_code": "IN-MH"})
    assert again.status_code == 409 and "locked" in again.json()["error"]["message"]
    await client.delete(f"{API}/campaigns/{cid}/locks/cta")
    assert (await client.post(f"{API}/campaigns/{cid}/chips/{chip['id']}/apply")).status_code == 201


async def test_chip_requests_are_validated(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, root = await demo_studio(client)
    url, base = f"{API}/campaigns/{cid}/chips/generate", {"version_id": root["id"], "element_id": "cta", "region_code": "IN-MH"}
    assert (await client.post(url, json=base | {"element_id": "nope"})).status_code == 404
    assert (await client.post(url, json=base | {"element_id": "logo"})).status_code == 409  # a logo is never tweaked by a model
    assert (await client.post(url, json=base | {"region_code": "IN-ZZ"})).status_code == 422
    assert (await client.post(url, json=base | {"region_code": "india"})).status_code == 422
    assert (await client.post(url, json=base | {"max_chips": 0})).status_code == 422
    assert (await client.post(url, json=base | {"version_id": "00000000-0000-0000-0000-000000000000"})).status_code == 404
    unknown_text = await client.post(f"{API}/campaigns/{cid}/operations", json={
        "version_id": root["id"], "reason": "r", "operation": {"kind": "replace_text", "edits": [{"element_id": "cta", "set": {"value": "An unknown line"}}]}})
    followed = await client.post(url, json=base)  # the fixture knows "Shop now" only; an edited line has no fixture
    assert unknown_text.status_code == 201 and followed.status_code == 201
    edited = unknown_text.json()["version"]["id"]
    failure = await client.post(url, json=base | {"version_id": edited})
    assert failure.status_code == 502 and failure.json()["error"]["code"] == "PROVIDER_ERROR"  # no fixture: reported, not invented
    assert (await client.get(f"{API}/campaigns/{cid}/chips")).json()["total"] == 1


async def test_chips_on_a_live_project_need_a_configured_provider(seeded: Any, client: httpx.AsyncClient) -> None:
    from tests.api.test_crud import make_campaign, make_project

    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    root = (await client.post(f"{API}/campaigns/{campaign['id']}/versions", json={})).json()
    response = await client.post(f"{API}/campaigns/{campaign['id']}/chips/generate", json={
        "version_id": root["id"], "element_id": "headline", "region_code": "IN-MH"})
    assert response.status_code == 503 and response.json()["error"]["code"] == "PROVIDER_NOT_CONFIGURED"
    blocked = await client.post(f"{API}/campaigns/{campaign['id']}/transcreate", json={"region_code": "IN-MH", "language": "mr"})
    assert blocked.status_code == 503 and blocked.json()["error"]["code"] == "PROVIDER_NOT_CONFIGURED"


# --- Transcreate ----------------------------------------------------------------------------------------


async def test_transcreate_creates_a_new_version_with_back_translation_claims_and_checks(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, root = await demo_studio(client)
    run = await transcreate(client, cid, {"region_code": "IN-MH", "language": "mr"})
    assert run["status"] == "completed" and run["mode"] == "demo" and run["run_type"] == "transcreate"
    assert run["result"]["resource"] == "version" and run["progress"]["stage"] == "completed"
    version = (await client.get(run["result"]["url"])).json()
    assert version["parent_id"] == root["id"] and (version["region_code"], version["language"]) == ("IN-MH", "mr")
    values = element_values(version)
    assert values["headline"] == "शुभ दिवाळी!" and values["cta"] == "आत्ताच खरेदी करा" and values["tagline"] == "या सणासुदीत तुमचं घर उजळवा"
    assert values["logo"] == "asset:logo-1"  # only text elements are transcreated
    by_id = {e["id"]: e for e in version["elements"]}
    assert (by_id["headline"]["language"], by_id["headline"]["script"]) == ("mr", "Deva") and by_id["logo"]["language"] is None
    assert element_values(root)["headline"] == "Happy Diwali"  # the original is untouched
    assert version["settings"]["tone"] == {"formality": 50, "code_mixing": 50, "urban_rural": 50, "playfulness": 50, "energy": 50}
    assert version["settings"]["generation"]["prompt_version"] == "transcreate-lines-v1" and version["settings"]["generation"]["provider"] == "fixture"
    operation = await operation_of(client, cid)
    assert operation["actor"] == "ai" and operation["result_version_id"] == version["id"] and operation["prompt_version"] == "transcreate-lines-v1"
    assert sorted(operation["target_element_ids"]) == ["cta", "headline", "tagline"] and operation["claim_ids"] == await claim_ids()
    lines = {line["element_id"]: line for line in operation["params"]["lines"]}
    headline = lines["headline"]
    assert headline["regional_copy"] == "शुभ दिवाळी!" and headline["back_translation"] == "Happy Diwali!" and headline["source_text"] == "Happy Diwali"
    assert headline["explanation"] and headline["passed"] is True and headline["problems"] == []
    assert headline["claim_ids"] == await claim_ids() and headline["reasoning_type"] == "evidence_supported"
    assert headline["script_check"]["ok"] is True and headline["script_check"]["expected_script"] == "Deva"
    assert headline["term_checks"]["protected_preserved"] is True
    assert lines["cta"]["claim_ids"] == [] and lines["cta"]["reasoning_type"] == "model_interpretation"  # no claim, so no evidence label
    assert any("not independent verification" in text for text in (await _limitations(client, run)))


async def _limitations(client: httpx.AsyncClient, run: dict[str, Any]) -> list[str]:
    async with read_session() as s:
        row = await s.get(m.AgentRun, UUID(run["id"]))
        assert row is not None and row.result is not None
        return row.result["limitations"]


async def test_tone_dials_change_the_generation_call_and_the_result(seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cid, root = await demo_studio(client)
    original = RESPONDERS["transcreate-lines-v1"]
    seen = respond(monkeypatch, "transcreate-lines-v1", original)
    casual_tone = {"formality": 10, "code_mixing": 50, "urban_rural": 50, "playfulness": 50, "energy": 50}
    formal_tone = casual_tone | {"formality": 90, "energy": 80}
    base = {"region_code": "IN-MH", "language": "mr", "element_ids": ["headline"], "version_id": root["id"]}
    casual = await transcreate(client, cid, base | {"tone": casual_tone})
    formal = await transcreate(client, cid, base | {"tone": formal_tone})
    assert [r["status"] for r in (casual, formal)] == ["completed", "completed"]
    assert len(seen) == 2 and seen[0]["tone"] == casual_tone and seen[1]["tone"] == formal_tone
    assert seen[0]["tone_directives"] != seen[1]["tone_directives"]  # the dials became different prompt directives
    assert "casual" in seen[0]["tone_directives"][0] and "formal, respectful" in seen[1]["tone_directives"][0]
    low, high = [(await client.get(r["result"]["url"])).json() for r in (casual, formal)]
    assert element_values(low)["headline"] == "शुभ दिवाळी!" and element_values(high)["headline"] == "आपणा सर्वांना दिवाळीच्या हार्दिक शुभेच्छा"
    assert (low["settings"]["tone"], high["settings"]["tone"]) == (casual_tone, formal_tone)  # persisted with each version
    diff = (await client.get(f"{API}/campaigns/{cid}/versions/{low['id']}/diff/{high['id']}")).json()
    assert {c["field"] for c in diff["settings_changes"]} == {"tone.formality", "tone.energy"}  # tone settings compare across versions
    assert [c["element_id"] for c in diff["changed"]] == ["headline"]


async def test_transcreate_honours_an_idempotency_key(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, _ = await demo_studio(client)
    body = {"region_code": "IN-MH", "language": "mr", "element_ids": ["cta"]}
    first = await client.post(f"{API}/campaigns/{cid}/transcreate", json=body, headers={**dict(client.headers), "Idempotency-Key": "studio-1"})
    second = await client.post(f"{API}/campaigns/{cid}/transcreate", json=body, headers={**dict(client.headers), "Idempotency-Key": "studio-1"})
    assert first.status_code == second.status_code == 202 and first.json()["run_id"] == second.json()["run_id"]
    run = await wait_for_run(client, first.json()["run_id"], timeout=60)
    assert run["status"] == "completed" and (await client.get(f"{API}/campaigns/{cid}/versions")).json()["total"] == 2  # one run, one version


async def test_the_run_records_the_claims_glossary_and_tone_it_was_given(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, _ = await demo_studio(client)
    await client.post(f"{API}/campaigns/{cid}/glossary", json={"term": "Northstar", "language": "mr", "script": "Deva", "approved_spelling": "नॉर्थस्टार", "protected": True})
    await client.post(f"{API}/campaigns/{cid}/glossary", json={"term": "Northstar", "language": "ta", "protected": True})  # another language: not given
    run = await transcreate(client, cid, {"region_code": "IN-MH", "language": "mr", "element_ids": ["headline"], "tone": {"formality": 30}})
    async with read_session() as s:
        row = await s.get(m.AgentRun, UUID(run["id"]))
    assert row is not None and row.inputs["tone"]["formality"] == 30 and row.inputs["language_name"] == "Marathi" and row.inputs["script"] == "Deva"
    assert [(g["term"], g["language"]) for g in row.inputs["glossary"]] == [("Northstar", "mr")]
    assert [c["statement"] for c in row.inputs["claims"]] == [FESTIVAL] and row.inputs["lines"][0]["text"] == "Happy Diwali"


async def test_a_line_that_loses_a_protected_term_is_not_applied(seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cid, root = await demo_studio(client, NORTHSTAR)
    respond(monkeypatch, "transcreate-lines-v1", lines_responder({
        "Happy Diwali from Northstar": ("शुभ दिवाळी", "Happy Diwali"),  # the brand name is gone from both texts
        "Shop now": ("आत्ताच खरेदी करा", "Shop right now")}))
    run = await transcreate(client, cid, {"region_code": "IN-MH", "language": "mr"})
    assert run["status"] == "partial"  # one line applied, one refused by the checks
    version = (await client.get(run["result"]["url"])).json()
    assert element_values(version)["headline"] == "Happy Diwali from Northstar"  # unchanged: protected term check failed
    assert element_values(version)["cta"] == "आत्ताच खरेदी करा"
    lines = {line["element_id"]: line for line in (await operation_of(client, cid))["params"]["lines"]}
    headline = lines["headline"]
    assert headline["passed"] is False and headline["term_checks"]["missing_in_copy"] == ["Northstar"]
    assert headline["term_checks"]["missing_in_back_translation"] == ["Northstar"] and headline["regional_copy"] == "शुभ दिवाळी"  # kept for review
    assert any("Northstar" in problem for problem in headline["problems"]) and lines["cta"]["passed"] is True


async def test_the_back_translation_is_checked_too(seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cid, _ = await demo_studio(client, NORTHSTAR)
    respond(monkeypatch, "transcreate-lines-v1", lines_responder({
        "Happy Diwali from Northstar": ("Northstar कडून शुभ दिवाळी", "Happy Diwali from North Star"),  # altered in the back-translation
        "Shop now": ("आत्ताच स्वस्त खरेदी करा", "Shop cheap right now")}))  # a prohibited brand term ("cheap") in the back-translation
    run = await transcreate(client, cid, {"region_code": "IN-MH", "language": "mr"})
    assert run["status"] == "failed" and run["result"] is None and run["error"]["code"] == "RUN_FAILED"
    assert "No line passed" in run["error"]["message"]
    rejected = await operation_of(client, cid, "transcreate", "rejected")
    lines = {line["element_id"]: line for line in rejected["params"]["lines"]}
    assert lines["headline"]["term_checks"]["missing_in_back_translation"] == ["Northstar"] and lines["headline"]["term_checks"]["missing_in_copy"] == []
    assert lines["cta"]["term_checks"]["prohibited_in_back_translation"] == ["cheap"] and lines["cta"]["term_checks"]["prohibited_in_copy"] == []
    assert rejected["rejection"]["code"] == "CHECKS_FAILED" and rejected["result_version_id"] is None
    assert (await client.get(f"{API}/campaigns/{cid}/versions")).json()["total"] == 1  # no version was created


async def test_glossary_spellings_and_prohibited_alternatives_are_enforced(seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cid, root = await demo_studio(client, NORTHSTAR)
    await client.post(f"{API}/campaigns/{cid}/glossary", json={
        "term": "Northstar", "language": "mr", "script": "Deva", "approved_spelling": "नॉर्थस्टार", "protected": True, "prohibited_alternatives": ["नॉर्थ स्टार"]})
    table = {"Happy Diwali from Northstar": ("नॉर्थस्टार कडून शुभ दिवाळी", "Happy Diwali from Northstar"), "Shop now": ("आत्ताच खरेदी करा", "Shop right now")}
    respond(monkeypatch, "transcreate-lines-v1", lines_responder(table))
    ok = await transcreate(client, cid, {"region_code": "IN-MH", "language": "mr"})
    assert ok["status"] == "completed"
    headline = {line["element_id"]: line for line in (await operation_of(client, cid))["params"]["lines"]}["headline"]
    assert headline["preserved_terms"] == ["नॉर्थस्टार"]  # the approved spelling, verified in the copy by code
    respond(monkeypatch, "transcreate-lines-v1", lines_responder(table | {"Happy Diwali from Northstar": ("Northstar कडून शुभ दिवाळी", "Happy Diwali from Northstar")}))
    latin = await transcreate(client, cid, {"region_code": "IN-MH", "language": "mr", "element_ids": ["headline"], "version_id": root["id"]})
    assert latin["status"] == "failed"  # the Latin spelling is not the brand-approved one for Marathi
    respond(monkeypatch, "transcreate-lines-v1", lines_responder(table | {"Happy Diwali from Northstar": ("नॉर्थ स्टार कडून शुभ दिवाळी", "Happy Diwali from Northstar")}))
    banned = await transcreate(client, cid, {"region_code": "IN-MH", "language": "mr", "element_ids": ["headline"], "version_id": root["id"]})
    assert banned["status"] == "failed"
    rejected = (await client.get(f"{API}/campaigns/{cid}/operations", params={"status": "rejected"})).json()["items"]
    assert len(rejected) == 2
    problems = " ".join(p for o in rejected for line in o["params"]["lines"] for p in line["problems"])
    assert "Protected term missing" in problems and "Prohibited term in the regional copy" in problems


async def test_the_script_is_checked_and_code_mixing_relaxes_the_share(seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cid, _ = await demo_studio(client)
    respond(monkeypatch, "transcreate-lines-v1", lines_responder({"Happy Diwali": ("இனிய தீபாவளி", "Happy Diwali")}))  # Tamil copy for a Marathi request
    wrong = await transcreate(client, cid, {"region_code": "IN-MH", "language": "mr", "element_ids": ["headline"]})
    assert wrong["status"] == "failed"
    line = (await operation_of(client, cid, "transcreate", "rejected"))["params"]["lines"][0]
    assert line["script_check"]["ok"] is False and line["script_check"]["foreign_scripts"] == ["Taml"] and line["script_check"]["expected_script"] == "Deva"
    mixed = {"Happy Diwali": ("शुभ दिवाळी Diwali offer", "Happy Diwali offer")}  # about 45% Devanagari letters
    respond(monkeypatch, "transcreate-lines-v1", lines_responder(mixed))
    pure = await transcreate(client, cid, {"region_code": "IN-MH", "language": "mr", "element_ids": ["headline"], "tone": {"code_mixing": 0}})
    code_mixed = await transcreate(client, cid, {"region_code": "IN-MH", "language": "mr", "element_ids": ["headline"], "tone": {"code_mixing": 100}})
    assert (pure["status"], code_mixed["status"]) == ("failed", "completed")  # mostly-English copy is allowed only when code-mixing is asked for


async def test_unknown_claim_handles_are_dropped_and_not_trusted(seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cid, _ = await demo_studio(client)
    respond(monkeypatch, "transcreate-lines-v1", lines_responder({"Happy Diwali": ("शुभ दिवाळी!", "Happy Diwali!")}, claims=["C1", "C9"]))
    run = await transcreate(client, cid, {"region_code": "IN-MH", "language": "mr", "element_ids": ["headline"]})
    assert run["status"] == "completed"
    line = (await operation_of(client, cid))["params"]["lines"][0]
    assert line["claim_ids"] == await claim_ids()  # C9 was never supplied: dropped; C1 resolved to the real claim id
    assert any("did not match" in text for text in await _limitations(client, run))


async def test_a_lock_set_while_the_run_is_working_refuses_the_whole_operation(seeded: Any, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.workflows as workflows

    cid, root = await demo_studio(client)
    real = workflows.run_transcreate

    async def locking(*args: Any, **kwargs: Any) -> Any:
        await client.put(f"{API}/campaigns/{cid}/locks/headline")  # the user locks the headline mid-run
        return await real(*args, **kwargs)

    monkeypatch.setattr(workflows, "run_transcreate", locking)
    run = await transcreate(client, cid, {"region_code": "IN-MH", "language": "mr"})
    assert run["status"] == "failed" and run["error"]["code"] == "CONFLICT" and "Locked element" in run["error"]["message"]
    assert (await client.get(f"{API}/campaigns/{cid}/versions")).json()["total"] == 1  # nothing was applied, not even the unlocked lines
    rejected = await operation_of(client, cid, "transcreate", "rejected")
    assert rejected["rejection"]["code"] == "LOCKED" and rejected["rejection"]["element_ids"] == ["headline"]
    assert len(rejected["params"]["lines"]) == 3 and element_values(root)["headline"] == "Happy Diwali"  # the lines stay available for review


async def test_transcreate_requests_are_validated(seeded: Any, client: httpx.AsyncClient) -> None:
    project = (await client.post(f"{API}/projects/demo")).json()
    cid = (await client.get(f"{API}/projects/{project['id']}/campaigns")).json()["items"][0]["id"]
    url, base = f"{API}/campaigns/{cid}/transcreate", {"region_code": "IN-MH", "language": "mr"}
    assert (await client.post(url, json=base)).status_code == 409  # no version yet
    root = (await client.post(f"{API}/campaigns/{cid}/versions", json={"elements": DEMO_ELEMENTS})).json()
    assert (await client.post(url, json=base | {"language": "xx"})).json()["error"]["details"][0]["field"] == "language"
    assert (await client.post(url, json=base | {"region_code": "IN-ZZ"})).json()["error"]["details"][0]["field"] == "region_code"
    assert (await client.post(url, json=base | {"element_ids": ["nope"]})).status_code == 409
    assert (await client.post(url, json=base | {"element_ids": ["logo"]})).status_code == 409  # not a text element
    assert (await client.post(url, json=base | {"element_ids": ["cta", "cta"]})).status_code == 422
    assert (await client.post(url, json=base | {"tone": {"energy": 120}})).status_code == 422
    assert (await client.post(url, json=base | {"version_id": "00000000-0000-0000-0000-000000000000"})).status_code == 404
    await client.put(f"{API}/campaigns/{cid}/locks/headline")
    locked = await client.post(url, json=base | {"element_ids": ["headline"]})
    assert locked.status_code == 409 and locked.json()["error"]["details"][0]["field"] == "element_ids.0"
    for element in ("tagline", "cta"):
        await client.put(f"{API}/campaigns/{cid}/locks/{element}")
    nothing = await client.post(url, json=base | {"version_id": root["id"]})
    assert nothing.status_code == 409 and "no unlocked text element" in nothing.json()["error"]["message"]


async def test_the_fixture_never_invents_a_translation(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, _ = await demo_studio(client, [{"id": "headline", "kind": "headline", "value": "A line the fixtures do not know", "language": "en", "script": "Latn"}])
    run = await transcreate(client, cid, {"region_code": "IN-MH", "language": "mr"})
    assert run["status"] == "failed" and run["error"]["code"] == "PROVIDER_ERROR" and run["result"] is None
    assert (await client.get(f"{API}/campaigns/{cid}/versions")).json()["total"] == 1
