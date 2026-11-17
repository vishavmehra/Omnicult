"""Creative Studio over HTTP: the version tree, operations, locks, restore and diff, Brand Glossary, roles and
cross-workspace denial. (Tweak Chips and Transcreate: test_studio_ai.py.)"""

from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import select

from app.db import models as m
from app.db.session import read_session
from tests.api.omnicult_support import add_member, client_for, draft, put_claims, seeded, source, workspace_of  # noqa: F401
from tests.api.test_crud import make_campaign, make_project
from tests.conftest import BOB

API = "/api/v1"
ELEMENTS = [
    {"id": "logo", "kind": "logo", "value": "asset:logo-1", "bbox": [0.05, 0.05, 0.2, 0.1]},
    {"id": "tagline", "kind": "tagline", "value": "Light up Diwali", "language": "en", "script": "Latn"},
    {"id": "headline", "kind": "headline", "value": "Happy Diwali from Acme", "language": "en", "script": "Latn"},
    {"id": "cta", "kind": "cta", "value": "Shop now", "language": "en", "script": "Latn"},
]


def edit(element_id: str, value: str, kind: str = "replace_text") -> dict[str, Any]:
    return {"kind": kind, "edits": [{"element_id": element_id, "set": {"value": value}}]}


async def studio(client: httpx.AsyncClient) -> tuple[str, dict[str, Any]]:
    """A live project with a campaign and a root version made from ELEMENTS. Returns (campaign id, root version)."""
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    response = await client.post(f"{API}/campaigns/{campaign['id']}/versions", json={"elements": ELEMENTS, "label": "Original"})
    assert response.status_code == 201, response.text
    return campaign["id"], response.json()


async def apply(client: httpx.AsyncClient, cid: str, version_id: str, operation: dict[str, Any], **extra: Any) -> httpx.Response:
    body = {"version_id": version_id, "operation": operation, "reason": "Test change."} | extra
    return await client.post(f"{API}/campaigns/{cid}/operations", json=body)


async def total(client: httpx.AsyncClient, url: str, **params: Any) -> int:
    response = await client.get(url, params=params)
    assert response.status_code == 200, response.text
    return response.json()["total"]


# --- the version tree --------------------------------------------------------------------------


async def test_a_root_version_is_made_from_the_campaign_copy_or_explicit_elements(seeded: Any, client: httpx.AsyncClient) -> None:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    cid = campaign["id"]
    assert (await client.get(f"{API}/campaigns/{cid}/versions")).json()["total"] == 0
    derived = await client.post(f"{API}/campaigns/{cid}/versions", json={})
    assert derived.status_code == 201, derived.text
    root = derived.json()
    assert root["parent_id"] is None and root["operation_id"] is None and root["actor"] == "user" and root["label"] == "Original"
    assert [(e["id"], e["kind"], e["value"], e["language"], e["script"]) for e in root["elements"]] == [
        ("headline", "headline", "Find your trail", "en", "Latn"), ("body", "body", "Gear for weekends.", "en", "Latn"),
        ("cta", "cta", "Shop", "en", "Latn")]
    explicit = (await client.post(f"{API}/campaigns/{cid}/versions", json={"elements": ELEMENTS, "region_code": "IN-MH", "language": "en"})).json()
    assert explicit["element_count"] == 4 and explicit["region_code"] == "IN-MH" and explicit["parent_id"] is None
    listed = (await client.get(f"{API}/campaigns/{cid}/versions")).json()
    assert listed["total"] == 2 and [v["id"] for v in listed["items"]] == [root["id"], explicit["id"]]
    assert "elements" not in listed["items"][0] and (await client.get(f"{API}/campaigns/{cid}/versions/{explicit['id']}")).json() == explicit
    duplicate_ids = await client.post(f"{API}/campaigns/{cid}/versions", json={"elements": [ELEMENTS[0], ELEMENTS[0]]})
    assert duplicate_ids.status_code == 422
    too_big = await client.post(f"{API}/campaigns/{cid}/versions", json={"elements": [{"id": "body", "kind": "body", "value": "x" * 20_001}]})
    assert too_big.status_code == 422
    assert (await client.get(f"{API}/campaigns/{cid}/versions/{uuid4()}")).status_code == 404


async def test_an_operation_creates_a_new_version_and_never_mutates_the_source(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, root = await studio(client)
    await put_claims(await workspace_of("alice"), [draft("Diwali", region="IN-MH", sources=[source("wikimedia")])])
    async with read_session() as s:
        claim_id = str((await s.execute(select(m.Claim.id))).scalars().first())
    response = await apply(client, cid, root["id"], edit("headline", "Shubh Diwali from Acme"), claim_ids=[claim_id], label="Marathi greeting")
    assert response.status_code == 201, response.text
    result = response.json()
    child, operation = result["version"], result["operation"]
    assert child["parent_id"] == root["id"] and child["label"] == "Marathi greeting" and child["operation_id"] == operation["id"]
    assert {e["id"]: e["value"] for e in child["elements"]}["headline"] == "Shubh Diwali from Acme"
    assert operation["kind"] == "replace_text" and operation["status"] == "applied" and operation["actor"] == "user"
    assert operation["source_version_id"] == root["id"] and operation["result_version_id"] == child["id"]
    assert operation["target_element_ids"] == ["headline"] and operation["claim_ids"] == [claim_id] and operation["reason"] == "Test change."
    assert (await client.get(f"{API}/campaigns/{cid}/versions/{root['id']}")).json() == root  # the original is untouched
    assert (await client.get(f"{API}/campaigns/{cid}/operations/{operation['id']}")).json() == operation
    assert (await client.get(f"{API}/campaigns/{cid}/operations", params={"version_id": root["id"]})).json()["total"] == 1
    # a second operation on the SAME source makes a sibling branch; the tree keeps both
    branch = (await apply(client, cid, root["id"], edit("headline", "Diwali greetings from Acme"))).json()["version"]
    assert branch["parent_id"] == root["id"] and branch["id"] != child["id"]
    assert await total(client, f"{API}/campaigns/{cid}/versions") == 3


async def test_claim_ids_on_an_operation_must_exist(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, root = await studio(client)
    response = await apply(client, cid, root["id"], edit("headline", "Changed"), claim_ids=[str(uuid4())])
    assert response.status_code == 422 and response.json()["error"]["details"][0]["field"] == "claim_ids.0"
    assert await total(client, f"{API}/campaigns/{cid}/versions") == 1


async def test_swap_settings_and_tone_operations_are_versioned(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, root = await studio(client)
    swapped = (await apply(client, cid, root["id"], {"kind": "swap_reference", "element_id": "tagline", "from_text": "Diwali", "to_text": "Pongal"})).json()
    assert {e["id"]: e["value"] for e in swapped["version"]["elements"]}["tagline"] == "Light up Pongal"
    assert swapped["operation"]["params"] == {"element_id": "tagline", "from_text": "Diwali", "to_text": "Pongal"}
    missing = await apply(client, cid, root["id"], {"kind": "swap_reference", "element_id": "tagline", "from_text": "Holi", "to_text": "x"})
    assert missing.status_code == 409 and "does not appear" in missing.json()["error"]["message"]
    moved = (await apply(client, cid, root["id"], {"kind": "change_setting", "region_code": "IN-TN", "language": "ta"})).json()["version"]
    assert (moved["region_code"], moved["language"]) == ("IN-TN", "ta") and moved["elements"] == root["elements"]
    tone = {"formality": 90, "code_mixing": 10, "urban_rural": 40, "playfulness": 60, "energy": 70}
    toned = (await apply(client, cid, root["id"], {"kind": "tone_shift", "tone": tone})).json()["version"]
    assert toned["settings"]["tone"] == tone
    diff = (await client.get(f"{API}/campaigns/{cid}/versions/{root['id']}/diff/{toned['id']}")).json()
    assert {c["field"] for c in diff["settings_changes"]} == {f"tone.{d}" for d in tone} and diff["changed"] == []
    for bad in ({"kind": "swap_reference", "element_id": "tagline", "from_text": "x"}, {"kind": "change_setting"}, {"kind": "tone_shift", "tone": {"formality": 101}}, {"kind": "restore"}):
        assert (await apply(client, cid, root["id"], bad)).status_code == 422


async def test_an_invalid_operation_is_refused_and_recorded_without_a_version(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, root = await studio(client)
    for operation in (edit("nope", "x"), edit("logo", "x"), edit("headline", "Happy Diwali from Acme"), edit("headline", "   ")):
        response = await apply(client, cid, root["id"], operation)
        assert response.status_code == 409 and response.json()["error"]["code"] == "CONFLICT", operation
    assert await total(client, f"{API}/campaigns/{cid}/versions") == 1
    refused = (await client.get(f"{API}/campaigns/{cid}/operations", params={"status": "rejected"})).json()
    assert refused["total"] == 4 and all(o["rejection"]["code"] == "INVALID" and o["result_version_id"] is None for o in refused["items"])


# --- locks ------------------------------------------------------------------------------------------


async def test_locked_elements_refuse_operations_and_the_refusal_is_recorded(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, root = await studio(client)
    for element in ("logo", "tagline"):
        locked = await client.put(f"{API}/campaigns/{cid}/locks/{element}", json={"reason": "Brand rule"})
        assert locked.status_code == 200 and locked.json()["reason"] == "Brand rule" and locked.json()["released_at"] is None
    first = (await client.put(f"{API}/campaigns/{cid}/locks/logo")).json()  # idempotent: the existing lock comes back
    assert first["reason"] == "Brand rule" and await total(client, f"{API}/campaigns/{cid}/locks") == 2
    for operation in (edit("tagline", "Changed tagline"), {"kind": "manual_edit", "edits": [{"element_id": "logo", "set": {"bbox": [0, 0, 0.5, 0.5]}}]},
                      {"kind": "swap_reference", "element_id": "tagline", "from_text": "Diwali", "to_text": "Holi"}):
        response = await apply(client, cid, root["id"], operation)
        assert response.status_code == 409 and "Locked element" in response.json()["error"]["message"], operation
    mixed = await apply(client, cid, root["id"], {"kind": "manual_edit", "edits": [
        {"element_id": "headline", "set": {"value": "Fine"}}, {"element_id": "logo", "set": {"value": "asset:other"}}]})
    assert mixed.status_code == 409  # one locked target refuses the whole operation: headline was not changed either
    assert await total(client, f"{API}/campaigns/{cid}/versions") == 1
    refused = (await client.get(f"{API}/campaigns/{cid}/operations", params={"status": "rejected"})).json()
    assert refused["total"] == 4 and {o["rejection"]["code"] for o in refused["items"]} == {"LOCKED"}
    assert {tuple(o["rejection"]["element_ids"]) for o in refused["items"]} == {("tagline",), ("logo",)}
    ok = await apply(client, cid, root["id"], edit("headline", "Fine"))  # unlocked elements are not affected
    assert ok.status_code == 201
    released = (await client.delete(f"{API}/campaigns/{cid}/locks/tagline")).json()
    assert released["released_at"] and released["released_by"]
    assert (await apply(client, cid, root["id"], edit("tagline", "Changed tagline"))).status_code == 201
    assert (await client.delete(f"{API}/campaigns/{cid}/locks/tagline")).status_code == 404
    assert await total(client, f"{API}/campaigns/{cid}/locks") == 1
    assert await total(client, f"{API}/campaigns/{cid}/locks", include_released=True) == 2  # the history is kept
    assert (await client.put(f"{API}/campaigns/{cid}/locks/nonexistent")).status_code == 409


async def test_a_new_version_records_the_locks_in_force_when_it_was_made(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, root = await studio(client)
    await client.put(f"{API}/campaigns/{cid}/locks/logo")
    child = (await apply(client, cid, root["id"], edit("headline", "Changed"))).json()["version"]
    assert {e["id"] for e in child["elements"] if e["locked"]} == {"logo"} and not any(e["locked"] for e in root["elements"])


# --- restore and diff ------------------------------------------------------------------------------


async def test_restore_creates_a_new_version_copying_an_ancestor(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, root = await studio(client)
    v1 = (await apply(client, cid, root["id"], edit("headline", "Version one"))).json()["version"]
    v2 = (await apply(client, cid, v1["id"], edit("cta", "Buy today"))).json()["version"]
    restored = await client.post(f"{API}/campaigns/{cid}/versions/{root['id']}/restore", json={"reason": "Back to the original."})
    assert restored.status_code == 201, restored.text
    node, operation = restored.json()["version"], restored.json()["operation"]
    assert node["parent_id"] == v2["id"] and node["id"] not in (root["id"], v1["id"], v2["id"])  # a NEW node continues from the newest
    assert node["elements"] == root["elements"] and operation["kind"] == "restore" and operation["params"] == {"restored_version_id": root["id"]}
    assert sorted(operation["target_element_ids"]) == ["cta", "headline"]
    for version in (root, v1, v2):  # no earlier version changed
        assert (await client.get(f"{API}/campaigns/{cid}/versions/{version['id']}")).json() == version
    onto = await client.post(f"{API}/campaigns/{cid}/versions/{v2['id']}/restore", json={"onto_version_id": root["id"]})
    assert onto.json()["version"]["parent_id"] == root["id"] and {e["id"]: e["value"] for e in onto.json()["version"]["elements"]}["cta"] == "Buy today"
    same = await client.post(f"{API}/campaigns/{cid}/versions/{node['id']}/restore", json={"onto_version_id": node["id"]})
    assert same.status_code == 409  # nothing would change


async def test_restore_is_refused_when_it_would_change_a_locked_element(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, root = await studio(client)
    v1 = (await apply(client, cid, root["id"], edit("tagline", "Lights of Diwali"))).json()["version"]
    await client.put(f"{API}/campaigns/{cid}/locks/tagline")
    refused = await client.post(f"{API}/campaigns/{cid}/versions/{root['id']}/restore")
    assert refused.status_code == 409 and "tagline" in refused.json()["error"]["message"]
    assert await total(client, f"{API}/campaigns/{cid}/versions") == 2
    rejected = (await client.get(f"{API}/campaigns/{cid}/operations", params={"status": "rejected", "kind": "restore"})).json()
    assert rejected["total"] == 1 and rejected["items"][0]["source_version_id"] == v1["id"]
    await client.delete(f"{API}/campaigns/{cid}/locks/tagline")
    assert (await client.post(f"{API}/campaigns/{cid}/versions/{root['id']}/restore")).status_code == 201


async def test_the_diff_between_any_two_versions_lists_changed_preserved_added_and_removed(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, root = await studio(client)
    v1 = (await apply(client, cid, root["id"], edit("headline", "Shubh Diwali from Acme"))).json()["version"]
    v2 = (await apply(client, cid, v1["id"], {"kind": "swap_reference", "element_id": "tagline", "from_text": "Diwali", "to_text": "Pongal"})).json()["version"]
    diff = (await client.get(f"{API}/campaigns/{cid}/versions/{root['id']}/diff/{v2['id']}")).json()
    assert (diff["from_id"], diff["to_id"]) == (root["id"], v2["id"]) and diff["added"] == [] and diff["removed"] == []
    changed = {c["element_id"]: c for c in diff["changed"]}
    assert set(changed) == {"headline", "tagline"} and sorted(diff["preserved"]) == ["cta", "logo"]
    assert changed["tagline"]["fields"] == [{"field": "value", "before": "Light up Diwali", "after": "Light up Pongal"}]
    forward = (await client.get(f"{API}/campaigns/{cid}/versions/{v1['id']}/diff/{v2['id']}")).json()
    assert [c["element_id"] for c in forward["changed"]] == ["tagline"] and sorted(forward["preserved"]) == ["cta", "headline", "logo"]
    other_root = (await client.post(f"{API}/campaigns/{cid}/versions", json={"elements": ELEMENTS[:2] + [
        {"id": "caption", "kind": "caption", "value": "Festive offer"}]})).json()
    unrelated = (await client.get(f"{API}/campaigns/{cid}/versions/{root['id']}/diff/{other_root['id']}")).json()
    assert [e["id"] for e in unrelated["added"]] == ["caption"] and [e["id"] for e in unrelated["removed"]] == ["headline", "cta"]
    assert (await client.get(f"{API}/campaigns/{cid}/versions/{root['id']}/diff/{uuid4()}")).status_code == 404


# --- Brand Glossary ----------------------------------------------------------------------------------


async def test_glossary_entries_are_created_listed_edited_and_deleted(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, _ = await studio(client)
    body = {"term": "Acme", "language": "mr", "script": "Deva", "approved_spelling": "एक्मी", "pronunciation": "ek-mee",
            "protected": True, "prohibited_alternatives": ["अक्मी", "अक्मी"], "notes": "Brand name."}
    created = await client.post(f"{API}/campaigns/{cid}/glossary", json=body)
    assert created.status_code == 201, created.text
    term = created.json()
    assert term["approved_spelling"] == "एक्मी" and term["prohibited_alternatives"] == ["अक्मी"] and term["never_translate"] is False
    await client.post(f"{API}/campaigns/{cid}/glossary", json={"term": "Acme", "never_translate": True})  # language defaults to *
    await client.post(f"{API}/campaigns/{cid}/glossary", json={"term": "sale", "language": "ta", "preferred_translation": "தள்ளுபடி"})
    assert (await client.post(f"{API}/campaigns/{cid}/glossary", json=body)).status_code == 409  # one entry per term and language
    assert (await client.post(f"{API}/campaigns/{cid}/glossary", json=body | {"term": "ACME"})).status_code == 409  # case-insensitive
    assert await total(client, f"{API}/campaigns/{cid}/glossary") == 3
    mr = (await client.get(f"{API}/campaigns/{cid}/glossary", params={"language": "mr"})).json()
    assert [t["language"] for t in mr["items"]] == ["*", "mr"]  # its own entries plus the all-languages ones
    assert (await client.get(f"{API}/campaigns/{cid}/glossary/{term['id']}")).json() == term
    patched = (await client.patch(f"{API}/campaigns/{cid}/glossary/{term['id']}", json={"pronunciation": "ek-mi", "protected": False})).json()
    assert patched["pronunciation"] == "ek-mi" and patched["protected"] is False and patched["term"] == "Acme" and patched["updated_at"] >= term["updated_at"]
    assert (await client.patch(f"{API}/campaigns/{cid}/glossary/{term['id']}", json={"protected": None})).status_code == 422
    assert (await client.patch(f"{API}/campaigns/{cid}/glossary/{term['id']}", json={"term": "Other"})).status_code == 422  # identity is fixed
    assert (await client.delete(f"{API}/campaigns/{cid}/glossary/{term['id']}")).status_code == 204
    assert (await client.get(f"{API}/campaigns/{cid}/glossary/{term['id']}")).status_code == 404
    assert (await client.delete(f"{API}/campaigns/{cid}/glossary/{term['id']}")).status_code == 404


async def test_glossary_validates_language_script_and_spelling(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, _ = await studio(client)
    url = f"{API}/campaigns/{cid}/glossary"
    base = {"term": "Acme", "language": "mr", "script": "Deva", "approved_spelling": "एक्मी"}
    assert (await client.post(url, json=base | {"language": "xx"})).json()["error"]["details"][0]["field"] == "language"
    wrong = await client.post(url, json=base | {"approved_spelling": "இனிய"})  # Tamil letters declared as Devanagari
    assert wrong.status_code == 422 and wrong.json()["error"]["details"][0]["field"] == "approved_spelling"
    assert (await client.post(url, json={"term": "Acme", "approved_spelling": "एक्मी"})).status_code == 422  # no script given
    assert (await client.post(url, json=base | {"language": "english"})).status_code == 422
    assert (await client.post(url, json=base)).status_code == 201


# --- access ---------------------------------------------------------------------------------------------


async def test_another_workspace_cannot_reach_any_studio_endpoint(seeded: Any, client: httpx.AsyncClient) -> None:
    cid, root = await studio(client)
    term = (await client.post(f"{API}/campaigns/{cid}/glossary", json={"term": "Acme"})).json()
    operation = (await apply(client, cid, root["id"], edit("headline", "Changed"))).json()["operation"]
    c = f"{API}/campaigns/{cid}"
    requests = [
        ("GET", f"{c}/versions", None), ("POST", f"{c}/versions", {}), ("GET", f"{c}/versions/{root['id']}", None),
        ("GET", f"{c}/versions/{root['id']}/diff/{root['id']}", None), ("POST", f"{c}/versions/{root['id']}/restore", {}),
        ("POST", f"{c}/operations", {"version_id": root["id"], "reason": "x", "operation": edit("headline", "Hacked")}),
        ("GET", f"{c}/operations", None), ("GET", f"{c}/operations/{operation['id']}", None),
        ("GET", f"{c}/locks", None), ("PUT", f"{c}/locks/headline", {}), ("DELETE", f"{c}/locks/headline", None),
        ("POST", f"{c}/chips/generate", {"version_id": root["id"], "element_id": "headline", "region_code": "IN-MH"}),
        ("GET", f"{c}/chips", None), ("POST", f"{c}/chips/{uuid4()}/apply", {}),
        ("POST", f"{c}/transcreate", {"region_code": "IN-MH", "language": "mr"}),
        ("GET", f"{c}/glossary", None), ("POST", f"{c}/glossary", {"term": "x"}), ("GET", f"{c}/glossary/{term['id']}", None),
        ("PATCH", f"{c}/glossary/{term['id']}", {"notes": "x"}), ("DELETE", f"{c}/glossary/{term['id']}", None),
    ]
    for method, url, body in requests:
        response = await client.request(method, url, headers=BOB, json=body)
        assert response.status_code == 404, (method, url, response.status_code, response.text)
    assert await total(client, f"{c}/operations") == 1 and await total(client, f"{c}/glossary") == 1  # nothing Bob sent took effect


async def test_roles_decide_who_can_change_a_creative(seeded: Any, client: httpx.AsyncClient, client_for: Any) -> None:
    cid, root = await studio(client)
    workspace = await workspace_of("alice")
    await add_member(workspace, "viewer-vic", "viewer")
    await add_member(workspace, "reviewer-rae", "reviewer")
    await add_member(workspace, "editor-ed", "editor")
    c = f"{API}/campaigns/{cid}"
    writes = [
        ("POST", f"{c}/operations", {"version_id": root["id"], "reason": "x", "operation": edit("headline", "Changed")}),
        ("POST", f"{c}/versions/{root['id']}/restore", {}), ("PUT", f"{c}/locks/headline", {}),
        ("POST", f"{c}/glossary", {"term": "Acme"}), ("POST", f"{c}/transcreate", {"region_code": "IN-MH", "language": "mr"}),
        ("POST", f"{c}/chips/generate", {"version_id": root["id"], "element_id": "headline", "region_code": "IN-MH"}),
    ]
    for label in ("viewer-vic", "reviewer-rae"):
        member = client_for({"Authorization": f"Bearer dev-{label}"})
        assert (await member.get(f"{c}/versions")).json()["total"] == 1  # members read
        assert (await member.get(f"{c}/versions/{root['id']}")).status_code == 200
        for method, url, body in writes:
            response = await member.request(method, url, json=body)
            assert response.status_code == 403, (label, method, url, response.status_code)
    editor = client_for({"Authorization": "Bearer dev-editor-ed"})
    done = await editor.post(f"{c}/operations", json=writes[0][2])
    assert done.status_code == 201 and done.json()["operation"]["actor_user_id"] is not None
    assert (await editor.put(f"{c}/locks/logo")).status_code == 200


async def test_archived_projects_are_read_only_for_the_studio(seeded: Any, client: httpx.AsyncClient) -> None:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    cid = campaign["id"]
    root = (await client.post(f"{API}/campaigns/{cid}/versions", json={"elements": ELEMENTS})).json()
    assert (await client.delete(f"{API}/projects/{project['id']}")).status_code == 204
    assert (await client.get(f"{API}/campaigns/{cid}/versions/{root['id']}")).status_code == 200
    assert (await apply(client, cid, root["id"], edit("headline", "Changed"))).status_code == 409
    assert (await client.put(f"{API}/campaigns/{cid}/locks/logo")).status_code == 409
