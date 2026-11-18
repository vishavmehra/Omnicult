"""Teams and roles: members, invites, role changes, leaving, last-owner protection, audit, settings and usage."""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.core.auth import dev_user_id
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from tests.api.firebase_tokens import bearer
from tests.api.omnicult_support import API, CAROL, add_member, client_for, firebase_app, seed, seeded, workspace_of  # noqa: F401
from tests.conftest import ALICE, BOB, auth

DAVE = auth("dave")


async def team(client: httpx.AsyncClient, name: str = "Studio") -> dict[str, Any]:
    response = await client.post(f"{API}/workspaces", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


async def members(client: httpx.AsyncClient, workspace_id: str) -> list[dict[str, Any]]:
    return (await client.get(f"{API}/workspaces/{workspace_id}/members")).json()["items"]


async def invite(client: httpx.AsyncClient, workspace_id: str, email: str = "bob@example.com", role: str = "editor") -> dict[str, Any]:
    response = await client.post(f"{API}/workspaces/{workspace_id}/invites", json={"email": email, "role": role})
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_new_team_workspace_has_its_creator_as_owner(client: httpx.AsyncClient) -> None:
    ws = await team(client)
    assert (ws["kind"], ws["role"], ws["member_count"], ws["owner_count"]) == ("team", "owner", 1, 1)
    listed = await members(client, ws["id"])
    assert [(x["role"], x["is_you"]) for x in listed] == [("owner", True)]
    me = (await client.get(f"{API}/me")).json()
    assert {w["id"] for w in me["workspaces"]} >= {ws["id"]}


NON_MEMBER_CALLS = (
    ("get", ""), ("patch", ""), ("get", "/members"), ("get", "/invites"), ("post", "/invites"), ("get", "/audit"),
    ("get", "/usage"), ("post", "/leave"), ("patch", f"/members/{uuid4()}"), ("delete", f"/members/{uuid4()}"),
    ("delete", f"/invites/{uuid4()}"),
)


@pytest.mark.parametrize(("method", "suffix"), NON_MEMBER_CALLS)
async def test_a_non_member_gets_404_everywhere(client: httpx.AsyncClient, client_for: Any, method: str, suffix: str) -> None:
    ws = await team(client)
    bodies = {"patch": {"role": "viewer"} if suffix else {"name": "x"}, "post": {"email": "a@b.co", "role": "viewer"}}
    body = {} if suffix == "/leave" or method not in bodies else {"json": bodies[method]}
    response = await getattr(client_for(BOB), method)(f"{API}/workspaces/{ws['id']}{suffix}", **body)
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(("role", "owner"), [("owner", True), ("editor", False), ("reviewer", False), ("viewer", False)])
async def test_role_matrix(client: httpx.AsyncClient, client_for: Any, role: str, owner: bool) -> None:
    ws = await team(client)
    await add_member(UUID(ws["id"]), "bob", role)
    bob = client_for(BOB)
    base = f"{API}/workspaces/{ws['id']}"
    for path in ("", "/members", "/usage"):  # every member can read
        assert (await bob.get(base + path)).status_code == 200, (role, path)
    assert (await bob.get(base)).json()["role"] == role
    other = next(x for x in await members(client, ws["id"]) if x["is_you"])  # alice's own membership
    writes = [
        await bob.patch(base, json={"name": "Renamed"}),
        await bob.post(base + "/invites", json={"email": "new@example.com", "role": "viewer"}),
        await bob.get(base + "/invites"), await bob.get(base + "/audit"),
        await bob.patch(f"{base}/members/{other['id']}", json={"role": "viewer"}),
        await bob.delete(f"{base}/members/{other['id']}"),
    ]
    codes = {r.status_code for r in writes}
    if owner:
        assert codes <= {200, 201, 204, 409}, [r.text for r in writes]  # alice is demoted, then removed
    else:
        assert codes == {403}, [(r.request.url.path, r.status_code) for r in writes]
        assert writes[0].json()["error"]["code"] == "FORBIDDEN"


async def test_anonymous_accounts_cannot_manage_teams(firebase_app: Any) -> None:
    transport = httpx.ASGITransport(app=firebase_app)
    anon = bearer("anon-1", anonymous=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=anon) as c:
        me = (await c.get(f"{API}/me")).json()
        own = me["workspaces"][0]["id"]
        assert (await c.get(f"{API}/workspaces/{own}")).status_code == 200  # may look at its own demo workspace
        for method, path, body in (
            ("post", "/workspaces", {"name": "x"}), ("patch", f"/workspaces/{own}", {"name": "x"}),
            ("post", f"/workspaces/{own}/invites", {"email": "a@b.co", "role": "viewer"}),
            ("get", f"/workspaces/{own}/invites", None), ("post", f"/workspaces/{own}/leave", None),
            ("post", "/invites/accept", {"code": "x" * 32}), ("post", "/invites/preview", {"code": "x" * 32}),
        ):
            response = await getattr(c, method)(API + path, **({"json": body} if body else {}))
            assert response.status_code == 403, (path, response.text)


async def test_invite_flow_is_single_use_and_the_code_is_shown_once(client: httpx.AsyncClient, client_for: Any) -> None:
    ws = await team(client)
    created = await invite(client, ws["id"], "Bob@Example.com", "reviewer")
    code = created["code"]
    assert created["emailed"] is False and created["invite"]["email"] == "bob@example.com"
    assert created["accept_path"] == f"/app/settings/join#code={code}"
    listed = (await client.get(f"{API}/workspaces/{ws['id']}/invites")).json()["items"]
    assert [i["status"] for i in listed] == ["pending"] and code not in str(listed)
    async with read_session() as s:  # only the hash is stored
        row = (await s.execute(select(m.WorkspaceInvite))).scalar_one()
    assert row.code_hash != code and code not in {str(v) for v in vars(row).values()}

    bob = client_for(BOB)
    preview = (await bob.post(f"{API}/invites/preview", json={"code": code})).json()
    assert (preview["workspace_name"], preview["role"], preview["already_member"]) == ("Studio", "reviewer", False)
    assert (await bob.get(f"{API}/workspaces/{ws['id']}")).status_code == 404  # not a member yet
    joined = await bob.post(f"{API}/invites/accept", json={"code": code})
    assert joined.status_code == 200 and (joined.json()["role"], joined.json()["member_count"]) == ("reviewer", 2)
    assert (await bob.get(f"{API}/workspaces/{ws['id']}")).json()["role"] == "reviewer"
    again = await client_for(CAROL).post(f"{API}/invites/accept", json={"code": code})
    assert again.status_code == 404  # used
    assert (await bob.post(f"{API}/invites/accept", json={"code": "z" * 32})).status_code == 404  # unknown
    assert (await client.get(f"{API}/workspaces/{ws['id']}/invites")).json()["items"][0]["status"] == "accepted"


async def test_an_invite_for_another_address_is_refused(client: httpx.AsyncClient, client_for: Any) -> None:
    ws = await team(client)
    code = (await invite(client, ws["id"], "bob@example.com"))["code"]
    bob = client_for(BOB)
    await bob.get(f"{API}/me")
    async with session() as s, s.begin():
        (await s.get(m.User, dev_user_id("bob"))).email = "someone.else@example.com"  # type: ignore[union-attr]
    assert (await bob.post(f"{API}/invites/preview", json={"code": code})).json()["email_matches_account"] is False
    refused = await bob.post(f"{API}/invites/accept", json={"code": code})
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "FORBIDDEN"
    async with session() as s, s.begin():
        (await s.get(m.User, dev_user_id("bob"))).email = "BOB@example.com"  # type: ignore[union-attr]
    assert (await bob.post(f"{API}/invites/accept", json={"code": code})).status_code == 200  # case-insensitive match


async def test_expired_and_revoked_invites_do_not_work_and_free_the_address(client: httpx.AsyncClient, client_for: Any) -> None:
    ws = await team(client)
    first = await invite(client, ws["id"])
    dup = await client.post(f"{API}/workspaces/{ws['id']}/invites", json={"email": "bob@example.com", "role": "viewer"})
    assert dup.status_code == 409
    async with session() as s, s.begin():
        row = (await s.execute(select(m.WorkspaceInvite))).scalar_one()
        row.expires_at = utcnow() - timedelta(minutes=1)
    bob = client_for(BOB)
    assert (await bob.post(f"{API}/invites/accept", json={"code": first["code"]})).status_code == 404
    listed = (await client.get(f"{API}/workspaces/{ws['id']}/invites")).json()["items"]
    assert listed[0]["status"] == "expired"
    assert (await client.delete(f"{API}/workspaces/{ws['id']}/invites/{first['invite']['id']}")).status_code == 409
    second = await invite(client, ws["id"])  # an expired invite does not block a new one
    assert (await client.delete(f"{API}/workspaces/{ws['id']}/invites/{second['invite']['id']}")).status_code == 204
    assert (await bob.post(f"{API}/invites/accept", json={"code": second["code"]})).status_code == 404
    third = await invite(client, ws["id"])
    assert (await bob.post(f"{API}/invites/accept", json={"code": third["code"]})).status_code == 200


async def test_invites_refuse_existing_members_and_bad_input(client: httpx.AsyncClient, client_for: Any) -> None:
    ws = await team(client)
    await add_member(UUID(ws["id"]), "bob", "viewer")
    async with session() as s, s.begin():
        (await s.get(m.User, dev_user_id("bob"))).email = "bob@example.com"  # type: ignore[union-attr]
    assert (await client.post(f"{API}/workspaces/{ws['id']}/invites", json={"email": "BOB@example.com", "role": "editor"})).status_code == 409
    for body in ({"email": "not-an-email", "role": "viewer"}, {"email": "a@b.co", "role": "admin"}, {"email": "a@b.co", "extra": 1}):
        assert (await client.post(f"{API}/workspaces/{ws['id']}/invites", json=body)).status_code == 422
    existing = await client_for(BOB).post(f"{API}/invites/accept", json={"code": (await invite(client, ws["id"], "other@example.com"))["code"]})
    assert existing.status_code == 409  # already a member


async def test_roles_change_and_the_last_owner_is_protected(client: httpx.AsyncClient, client_for: Any) -> None:
    ws = await team(client)
    base = f"{API}/workspaces/{ws['id']}"
    me = (await members(client, ws["id"]))[0]
    for call in (client.patch(f"{base}/members/{me['id']}", json={"role": "editor"}), client.delete(f"{base}/members/{me['id']}"),
                 client.post(f"{base}/leave")):
        response = await call
        assert response.status_code == 409 and "at least one owner" in response.json()["error"]["message"]
    await add_member(UUID(ws["id"]), "bob", "editor")
    bob_member = next(x for x in await members(client, ws["id"]) if not x["is_you"])
    promoted = await client.patch(f"{base}/members/{bob_member['id']}", json={"role": "owner"})
    assert promoted.status_code == 200 and promoted.json()["role"] == "owner"
    assert (await client.patch(f"{base}/members/{me['id']}", json={"role": "viewer"})).status_code == 200  # two owners now
    assert (await client.get(base)).json()["role"] == "viewer"
    assert (await client_for(BOB).patch(f"{base}/members/{me['id']}", json={"role": "owner"})).status_code == 200
    assert (await client.patch(f"{base}/members/{uuid4()}", json={"role": "owner"})).status_code == 404  # an owner again


async def test_members_leave_and_owners_remove(client: httpx.AsyncClient, client_for: Any) -> None:
    ws = await team(client)
    base = f"{API}/workspaces/{ws['id']}"
    await add_member(UUID(ws["id"]), "bob", "editor")
    await add_member(UUID(ws["id"]), "carol", "viewer")
    bob = client_for(BOB)
    assert (await bob.post(f"{base}/leave")).status_code == 204
    assert (await bob.get(base)).status_code == 404 and len(await members(client, ws["id"])) == 2
    carol = next(x for x in await members(client, ws["id"]) if x["role"] == "viewer")
    assert (await client.delete(f"{base}/members/{carol['id']}")).status_code == 204
    assert (await client_for(CAROL).get(base)).status_code == 404
    assert (await client.delete(f"{base}/members/{carol['id']}")).status_code == 404


async def test_the_owner_of_a_personal_workspace_cannot_leave_or_be_demoted(client: httpx.AsyncClient, client_for: Any) -> None:
    own = (await client.get(f"{API}/me")).json()["workspaces"][0]
    assert own["kind"] == "personal"
    await add_member(UUID(own["id"]), "bob", "owner")
    mine = next(x for x in await members(client, own["id"]) if x["is_you"])
    for call in (client.post(f"{API}/workspaces/{own['id']}/leave"),
                 client_for(BOB).patch(f"{API}/workspaces/{own['id']}/members/{mine['id']}", json={"role": "viewer"}),
                 client_for(BOB).delete(f"{API}/workspaces/{own['id']}/members/{mine['id']}")):
        assert (await call).status_code == 409


async def test_membership_changes_are_audited_with_ids_only(client: httpx.AsyncClient, client_for: Any) -> None:
    ws = await team(client)
    base = f"{API}/workspaces/{ws['id']}"
    code = (await invite(client, ws["id"], "bob@example.com", "viewer"))["code"]
    await client_for(BOB).post(f"{API}/invites/accept", json={"code": code})
    bob_member = next(x for x in await members(client, ws["id"]) if not x["is_you"])
    await client.patch(f"{base}/members/{bob_member['id']}", json={"role": "editor"})
    await client.delete(f"{base}/members/{bob_member['id']}")
    await client.patch(base, json={"name": "Renamed"})
    page = (await client.get(f"{base}/audit")).json()
    actions = [e["action"] for e in page["items"]]
    assert actions == ["workspace.renamed", "member.removed", "member.role_changed", "member.joined", "invite.created", "workspace.created"]
    changed = page["items"][2]
    assert (changed["role"], changed["previous_role"], changed["target"]["user_id"]) == ("editor", "viewer", str(dev_user_id("bob")))
    assert page["items"][4]["invite_email"] == "bob@example.com" and page["total"] == 6
    async with read_session() as s:
        details = [r.detail for r in (await s.execute(select(m.AuditLog).where(m.AuditLog.workspace_id == UUID(ws["id"])))).scalars()]
    assert "bob@example.com" not in str(details) and code not in str(details)  # ids and roles only
    assert (await client_for(BOB).get(f"{base}/audit")).status_code == 404  # removed: no longer a member


async def test_workspace_settings_name_and_default_regions(client: httpx.AsyncClient, seeded: Any) -> None:
    ws = await team(client)
    base = f"{API}/workspaces/{ws['id']}"
    updated = await client.patch(base, json={"name": "  Aamod  ", "default_region_codes": ["IN-MH", "IN-TN", "IN-MH"]})
    assert updated.status_code == 200
    body = updated.json()
    assert (body["name"], body["default_region_codes"]) == ("Aamod", ["IN-MH", "IN-TN"]) and body["settings_updated_at"]
    assert (await client.get(base)).json()["default_region_codes"] == ["IN-MH", "IN-TN"]
    unknown = await client.patch(base, json={"default_region_codes": ["IN-XX"]})
    assert unknown.status_code == 422 and "IN-XX" in str(unknown.json())
    assert (await client.patch(base, json={"name": "   "})).status_code == 422
    assert (await client.patch(base, json={"unknown": 1})).status_code == 422
    assert (await client.patch(base, json={"default_region_codes": []})).json()["default_region_codes"] == []


async def test_usage_is_aggregated_from_recorded_calls_and_labelled_as_estimates(client: httpx.AsyncClient, client_for: Any) -> None:
    ws = await team(client)
    base = f"{API}/workspaces/{ws['id']}/usage"
    empty = (await client.get(base)).json()
    assert (empty["calls"], empty["estimated_cost_usd"], empty["actual_cost_usd"], empty["by_model"]) == (0, 0, None, [])
    wid = UUID(ws["id"])
    old = utcnow() - timedelta(days=60)
    async with session() as s, s.begin():
        for cap, model, cost, status, at in (
            ("text", "gemini-3.8-flash", 0.01, "ok", utcnow()), ("text", "gemini-3.8-flash", 0.02, "error", utcnow()),
            ("embeddings", "gemini-embedding", 0.001, "ok", utcnow()), ("text", "gemini-3.8-flash", 5.0, "ok", old),
        ):
            s.add(m.AiUsageEvent(id=uuid4(), workspace_id=wid, capability=cap, provider="google", model=model, input_tokens=100,
                                 output_tokens=10, thinking_tokens=1, estimated_cost_usd=cost, status=status, created_at=at))
        s.add(m.AiUsageEvent(id=uuid4(), workspace_id=(await workspace_of("bob")), capability="text", provider="google", model="x",
                             estimated_cost_usd=9.0, created_at=utcnow()))  # another workspace never counts
    usage = (await client.get(base)).json()
    assert (usage["calls"], usage["failed_calls"], usage["input_tokens"], usage["estimated_cost_usd"]) == (3, 1, 300, 0.031)
    assert [(r["key"], r["calls"]) for r in usage["by_capability"]] == [("text", 2), ("embeddings", 1)]
    assert usage["by_model"][0]["key"] == "google / gemini-3.8-flash" and usage["actual_cost_usd"] is None
    assert any("estimates" in n for n in usage["notes"]) and usage["price_table_version"]
    assert (await client.get(base, params={"days": 90})).json()["calls"] == 4
    assert (await client.get(base, params={"days": 0})).status_code == 422
    assert (await client_for(BOB).get(base)).status_code == 404
