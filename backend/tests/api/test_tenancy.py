"""Identity and tenancy: users, personal workspaces, membership roles, cross-workspace denial, Firebase sign-in."""

from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.core.auth import dev_user_id
from app.db import models as m
from app.db.session import read_session, session
from tests.api.firebase_tokens import bearer
from tests.api.omnicult_support import API, CAROL, add_member, client_for, firebase_app, workspace_of  # noqa: F401
from tests.api.test_crud import CONTENT, make_campaign, make_project
from tests.conftest import BOB


async def test_first_request_creates_the_user_and_a_personal_workspace(client: httpx.AsyncClient) -> None:
    me = (await client.get(f"{API}/me")).json()
    assert me["id"] == str(dev_user_id("alice")) and me["is_anonymous"] is False
    assert [(w["kind"], w["role"]) for w in me["workspaces"]] == [("personal", "owner")]
    again = (await client.get(f"{API}/me")).json()
    assert again["workspaces"] == me["workspaces"]  # not created twice
    async with read_session() as s:
        assert await s.scalar(select(func.count(m.Workspace.id))) == 1


async def test_projects_belong_to_the_personal_workspace_by_default(client: httpx.AsyncClient) -> None:
    project = await make_project(client)
    me = (await client.get(f"{API}/me")).json()
    assert project["workspace_id"] == me["workspaces"][0]["id"]
    demo = (await client.post(f"{API}/projects/demo")).json()
    assert demo["workspace_id"] == project["workspace_id"]
    listed = (await client.get(f"{API}/projects")).json()
    assert {p["id"] for p in listed["items"]} == {project["id"], demo["id"]}


async def test_other_workspaces_cannot_reach_a_project_or_its_children(client: httpx.AsyncClient, client_for: Any) -> None:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    bob = client_for(BOB)
    assert (await bob.get(f"{API}/projects")).json()["items"] == []
    for method, path in (
        ("get", f"/projects/{project['id']}"),
        ("patch", f"/projects/{project['id']}"),
        ("delete", f"/projects/{project['id']}"),
        ("get", f"/projects/{project['id']}/campaigns"),
        ("get", f"/campaigns/{campaign['id']}"),
        ("get", f"/projects/{project['id']}/runs"),
    ):
        response = await getattr(bob, method)(f"{API}{path}", **({"json": {"name": "x"}} if method == "patch" else {}))
        assert response.status_code == 404, (method, path, response.text)
        assert response.json()["error"]["code"] == "NOT_FOUND"
    stolen = await bob.post(f"{API}/projects/{project['id']}/campaigns", json={
        "name": "x", "campaign_type": "advertisement", "original_content": CONTENT})
    assert stolen.status_code == 404
    assert (await client.get(f"{API}/projects/{project['id']}")).status_code == 200  # untouched


async def test_creating_a_project_in_another_workspace_is_refused(client: httpx.AsyncClient) -> None:
    bobs = await workspace_of("bob")
    response = await client.post(f"{API}/projects", json={"name": "x", "brand_name": "x", "workspace_id": str(bobs)})
    assert response.status_code == 404  # alice is not a member: the workspace is indistinguishable from a missing one
    unknown = await client.post(f"{API}/projects", json={"name": "x", "brand_name": "x", "workspace_id": str(uuid4())})
    assert unknown.status_code == 404


@pytest.mark.parametrize(
    ("role", "can_write"), [("owner", True), ("editor", True), ("reviewer", False), ("viewer", False)]
)
async def test_workspace_roles_decide_who_can_write(client: httpx.AsyncClient, client_for: Any, role: str, can_write: bool) -> None:
    project = await make_project(client)
    await add_member(UUID(project["workspace_id"]), "bob", role)
    bob = client_for(BOB)
    assert (await bob.get(f"{API}/projects/{project['id']}")).status_code == 200  # every role reads
    assert project["id"] in [p["id"] for p in (await bob.get(f"{API}/projects")).json()["items"]]
    patch = await bob.patch(f"{API}/projects/{project['id']}", json={"name": "Renamed"})
    campaign = await bob.post(f"{API}/projects/{project['id']}/campaigns", json={
        "name": "C", "campaign_type": "advertisement", "original_content": CONTENT})
    new_project = await bob.post(f"{API}/projects", json={
        "name": "B", "brand_name": "B", "workspace_id": project["workspace_id"]})
    if can_write:
        assert (patch.status_code, campaign.status_code, new_project.status_code) == (200, 201, 201)
    else:
        assert (patch.status_code, campaign.status_code, new_project.status_code) == (403, 403, 403)
        assert patch.json()["error"]["code"] == "FORBIDDEN"
        assert (await client.get(f"{API}/projects/{project['id']}")).json()["name"] == project["name"]


async def test_projects_without_a_workspace_stay_with_their_owner(client: httpx.AsyncClient, client_for: Any) -> None:
    """Rows from before the 0008 backfill have no workspace; the old owner rule still applies to them."""
    project = await make_project(client)
    async with session() as s, s.begin():
        row = await s.get(m.Project, UUID(project["id"]))
        assert row is not None
        row.workspace_id = None
    assert (await client.get(f"{API}/projects/{project['id']}")).status_code == 200
    assert (await client.patch(f"{API}/projects/{project['id']}", json={"name": "Still mine"})).status_code == 200
    assert project["id"] in [p["id"] for p in (await client.get(f"{API}/projects")).json()["items"]]
    bob = client_for(BOB)
    assert (await bob.get(f"{API}/projects/{project['id']}")).status_code == 404
    assert (await bob.get(f"{API}/projects")).json()["items"] == []


async def test_a_member_lists_projects_of_every_workspace_they_belong_to(client: httpx.AsyncClient, client_for: Any) -> None:
    carol = client_for(CAROL)
    team = await make_project(client)
    own = await make_project(carol)
    await add_member(UUID(team["workspace_id"]), "carol", "viewer")
    listed = {p["id"] for p in (await carol.get(f"{API}/projects")).json()["items"]}
    assert listed == {team["id"], own["id"]}


# --- Firebase sign-in ---------------------------------------------------------------------


async def test_firebase_user_is_created_on_first_login_and_reused(firebase_app: Any) -> None:
    transport = httpx.ASGITransport(app=firebase_app)
    headers = bearer("fb-uid-1", email="ada@example.com", name="Ada")
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        first = (await client.get(f"{API}/me")).json()
        second = (await client.get(f"{API}/me")).json()
    assert first["id"] == second["id"] and first["email"] == "ada@example.com" and first["display_name"] == "Ada"
    assert [w["role"] for w in first["workspaces"]] == ["owner"]
    async with read_session() as s:
        user = (await s.execute(select(m.User))).scalar_one()
        assert user.firebase_uid == "fb-uid-1" and str(user.id) == first["id"]  # an internal UUID, not the Firebase uid
        assert await s.scalar(select(func.count(m.Workspace.id))) == 1


async def test_firebase_users_are_separate_and_isolated(firebase_app: Any) -> None:
    transport = httpx.ASGITransport(app=firebase_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ada, grace = bearer("uid-ada", email="a@example.com"), bearer("uid-grace", email="g@example.com")
        project = (await client.post(f"{API}/projects", json={"name": "P", "brand_name": "B"}, headers=ada)).json()
        assert (await client.get(f"{API}/projects/{project['id']}", headers=ada)).status_code == 200
        assert (await client.get(f"{API}/projects/{project['id']}", headers=grace)).status_code == 404
        assert (await client.get(f"{API}/projects", headers=grace)).json()["items"] == []


async def test_anonymous_firebase_users_can_only_explore_the_demo(firebase_app: Any) -> None:
    transport = httpx.ASGITransport(app=firebase_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        visitor = bearer("uid-visitor", anonymous=True)
        me = (await client.get(f"{API}/me", headers=visitor)).json()
        assert me["is_anonymous"] is True
        live = await client.post(f"{API}/projects", json={"name": "P", "brand_name": "B"}, headers=visitor)
        assert live.status_code == 403 and live.json()["error"]["code"] == "FORBIDDEN"
        demo = await client.post(f"{API}/projects/demo", headers=visitor)
        assert demo.status_code == 201 and demo.json()["mode"] == "demo"
        assert (await client.get(f"{API}/projects/{demo.json()['id']}", headers=visitor)).status_code == 200
        # signing in with an account (same Firebase uid after linking) lifts the restriction and keeps the workspace
        upgraded = bearer("uid-visitor", email="v@example.com")
        assert (await client.get(f"{API}/me", headers=upgraded)).json()["is_anonymous"] is False
        assert (await client.post(f"{API}/projects", json={"name": "P", "brand_name": "B"}, headers=upgraded)).status_code == 201


async def test_a_bad_firebase_token_is_401(firebase_app: Any) -> None:
    transport = httpx.ASGITransport(app=firebase_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for header in ("Bearer dev-alice", "Bearer not.a.jwt"):
            response = await client.get(f"{API}/me", headers={"Authorization": header})
            assert response.status_code == 401, header
        expired = bearer("uid", exp=1)
        assert (await client.get(f"{API}/me", headers=expired)).status_code == 401
        wrong_audience = bearer("uid", aud="another-project")
        assert (await client.get(f"{API}/me", headers=wrong_audience)).status_code == 401


async def test_concurrent_first_requests_create_one_user(firebase_app: Any) -> None:
    import asyncio

    transport = httpx.ASGITransport(app=firebase_app)
    headers = bearer("uid-race", email="race@example.com")
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        responses = await asyncio.gather(*[client.get(f"{API}/me") for _ in range(5)])
    assert {r.status_code for r in responses} == {200}
    assert len({r.json()["id"] for r in responses}) == 1
    async with read_session() as s:
        assert await s.scalar(select(func.count(m.User.id))) == 1
        assert await s.scalar(select(func.count(m.Workspace.id))) == 1
