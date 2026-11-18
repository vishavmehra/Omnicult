"""Review Links: scoped, expiring, revocable, read-only links for people with no account.

The secret is shown once and stored only as a hash; every failure of a link is the same 404; a reviewer reaches the chosen
versions and nothing else; decisions are recorded against the version, audited, and never approve anything.
"""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.core.auth import dev_user_id
from app.core.config import get_settings
from app.core.ratelimit import SlidingWindow
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.services import review_links
from tests.api.delivery_support import KL, TN, add_asset, add_creative, add_version, campaign_of, review_headers
from tests.api.omnicult_support import API, add_member, client_for, seeded, workspace_of  # noqa: F401
from tests.conftest import BOB

REVIEW = f"{API}/review"


@pytest.fixture(autouse=True)
def fresh_limits() -> Iterator[None]:
    review_links._limiters.clear()
    yield
    review_links._limiters.clear()


async def make_link(client: httpx.AsyncClient, c: dict[str, Any], items: list[dict[str, str]], **body: Any) -> dict[str, Any]:
    response = await client.post(f"{c['base']}/review-links", json={"label": "Agency", "items": items} | body)
    assert response.status_code == 201, response.text
    return response.json()


def item(version_id: UUID, region: str = TN) -> dict[str, str]:
    return {"version_id": str(version_id), "region_code": region}


async def open_page(client: httpx.AsyncClient, secret: str) -> httpx.Response:
    return await client.get(REVIEW, headers=review_headers(secret))


async def decide(client: httpx.AsyncClient, secret: str, version_id: UUID | str, region: str = TN, decision: str = "approve", **extra: Any) -> httpx.Response:
    return await client.post(f"{REVIEW}/responses", headers=review_headers(secret),
                             json={"version_id": str(version_id), "region_code": region, "decision": decision} | extra)


# --- creating and storing ---------------------------------------------------------------------------------------------------


async def test_the_secret_is_shown_once_and_only_its_hash_is_stored(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await add_version(c)
    link = await make_link(client, c, [item(version)], note="Please read the Tamil lines.")
    secret = link["token"]
    assert len(secret) >= 40 and link["review_path"] == f"/review/{secret}" and link["token_hint"] == secret[-4:]
    assert link["status"] == "active" and link["items"][0]["version_label"] == "Tamil" and link["items"][0]["region_name"] == "Tamil Nadu"
    async with read_session() as s:
        row = (await s.execute(select(m.ReviewLink))).scalar_one()
        stored = [str(getattr(row, col.name)) for col in m.ReviewLink.__table__.columns]
    assert not any(secret in value for value in stored) and row.token_hash == review_links.hash_secret(secret)
    listed = (await client.get(f"{c['base']}/review-links")).json()
    assert listed["total"] == 1 and "token" not in listed["items"][0] and secret not in str(listed)
    assert timedelta(days=6) < (utcnow() - row.expires_at).__neg__() <= timedelta(days=7, seconds=5)  # the default expiry is a week


async def test_a_link_can_only_name_versions_of_its_own_campaign_and_known_regions(client: httpx.AsyncClient, seeded: Any) -> None:
    c, other = await campaign_of(client), await campaign_of(client)
    mine, theirs = await add_version(c), await add_version(other)
    base = f"{c['base']}/review-links"
    assert (await client.post(base, json={"label": "x", "items": [item(theirs)]})).status_code == 404
    assert (await client.post(base, json={"label": "x", "items": [item(uuid4())]})).status_code == 404
    assert (await client.post(base, json={"label": "x", "items": [item(mine, "IN-ZZ")]})).status_code == 404
    assert (await client.post(base, json={"label": "x", "items": []})).status_code == 422
    assert (await client.post(base, json={"label": "x", "items": [item(mine), item(mine)]})).status_code == 422
    assert (await client.post(base, json={"label": "x", "items": [item(mine)], "expires_in_days": 31})).status_code == 422


# --- what a reviewer sees ---------------------------------------------------------------------------------------------------


async def test_a_reviewer_sees_only_the_chosen_versions_as_plain_text(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    chosen, hidden = await add_version(c, "Tamil"), await add_version(c, "Kerala", KL, "ml")
    link = await make_link(client, c, [item(chosen)])
    page = (await open_page(client, link["token"])).json()
    assert page["link_label"] == "Agency" and page["mode"] == "live" and page["decisions"] == ["approve", "request_changes", "reject", "comment"]
    assert [i["version_id"] for i in page["items"]] == [str(chosen)] and str(hidden) not in str(page)
    elements = {e["id"]: e["text"] for e in page["items"][0]["elements"]}
    assert elements == {"headline": "Tamil headline", "cta": "Order now"}, "only text elements: no logo path, no ids of anything else"
    assert "readiness" not in str(page).lower() and "verdict" not in str(page).lower()
    assert "not verified" in page["identity_note"].lower() and "anonymous" in page["identity_note"].lower()


async def test_markup_in_copy_is_returned_as_text_and_never_executed_by_the_server(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await add_version(c, elements=[{"id": "headline", "kind": "headline", "value": "<img src=x onerror=alert(1)>"}])
    page = (await open_page(client, (await make_link(client, c, [item(version)]))["token"]))
    assert page.headers["content-type"].startswith("application/json")
    assert page.json()["items"][0]["elements"][0]["text"] == "<img src=x onerror=alert(1)>"


async def test_creative_files_are_shown_only_when_rights_are_confirmed_and_served_sandboxed(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await add_version(c)
    ok = await add_asset(c, filename="kolam.png", data=b"png-ok")
    unconfirmed = await add_asset(c, filename="draft.png", data=b"png-no", rights=False)
    elsewhere = await add_asset(c, filename="kerala.png", data=b"png-kl")
    shown = await add_creative(c, ok, label="Tamil key visual", region=TN)
    hidden = await add_creative(c, unconfirmed, label="Draft", region=TN)
    other_region = await add_creative(c, elsewhere, label="Kerala visual", region=KL)
    link = await make_link(client, c, [item(version)])
    page = (await open_page(client, link["token"])).json()
    assert [x["id"] for x in page["items"][0]["creatives"]] == [str(shown)]
    got = await client.get(f"{REVIEW}/creatives/{shown}", headers=review_headers(link["token"]))
    assert got.status_code == 200 and got.content == b"png-ok" and got.headers["content-type"] == "image/png"
    assert got.headers["content-security-policy"] == "default-src 'none'; sandbox" and got.headers["x-content-type-options"] == "nosniff"
    for blocked in (hidden, other_region, uuid4()):
        assert (await client.get(f"{REVIEW}/creatives/{blocked}", headers=review_headers(link["token"]))).status_code == 404


# --- decisions ---------------------------------------------------------------------------------------------------------------


async def test_a_decision_is_recorded_against_the_version_audited_and_never_approves(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await add_version(c)
    link = await make_link(client, c, [item(version)])
    named = await decide(client, link["token"], version, reviewer_name="  Regional head  ")
    anonymous = await decide(client, link["token"], version, decision="request_changes", comment="Make the delivery promise clearer.")
    assert named.status_code == anonymous.status_code == 201, named.text
    assert (named.json()["reviewer_kind"], anonymous.json()["reviewer_kind"]) == ("named", "anonymous")
    async with read_session() as s:
        rows = list((await s.execute(select(m.ReviewResponse).order_by(m.ReviewResponse.created_at))).scalars())
        audits = list((await s.execute(select(m.AuditLog).where(m.AuditLog.action == "review_link.response"))).scalars())
        approvals = await s.scalar(select(func.count()).select_from(m.Approval))
    assert [(r.decision, r.reviewer_name, r.reviewer_kind, r.version_id) for r in rows] == [
        ("approve", "Regional head", "named", version), ("request_changes", None, "anonymous", version)]
    assert len(audits) == 2 and all(a.actor_user_id is None and a.workspace_id == UUID(c["workspace_id"]) for a in audits)
    assert "Regional head" not in str(audits[0].detail) and "delivery promise" not in str([a.detail for a in audits]), "no name or comment in the audit detail"
    assert approvals == 0, "a stakeholder decision is not a Launch Room approval"
    responses = (await client.get(f"{c['base']}/review-responses")).json()
    assert responses["total"] == 2 and {x["decision"] for x in responses["items"]} == {"approve", "request_changes"}
    link_row = (await client.get(f"{c['base']}/review-links")).json()["items"][0]
    assert link_row["response_count"] == 2 and link_row["decisions"] == {"approve": 1, "request_changes": 1, "reject": 0, "comment": 0}


async def test_a_comment_is_needed_unless_the_reviewer_approves(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await add_version(c)
    secret = (await make_link(client, c, [item(version)]))["token"]
    for decision in ("request_changes", "reject", "comment"):
        assert (await decide(client, secret, version, decision=decision)).status_code == 422
    assert (await decide(client, secret, version, decision="comment", comment="Looks right.")).status_code == 201
    assert (await decide(client, secret, version, decision="shrug")).status_code == 422


async def test_a_reviewer_cannot_decide_outside_the_scope_of_the_link(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    chosen, other = await add_version(c), await add_version(c, "Kerala", KL, "ml")
    secret = (await make_link(client, c, [item(chosen)]))["token"]
    assert (await decide(client, secret, other, KL)).status_code == 404
    assert (await decide(client, secret, chosen, KL)).status_code == 404, "right version, wrong region"
    assert (await decide(client, secret, uuid4())).status_code == 404
    async with read_session() as s:
        assert await s.scalar(select(func.count()).select_from(m.ReviewResponse)) == 0


async def test_a_link_takes_a_bounded_number_of_responses(client: httpx.AsyncClient, seeded: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEW_MAX_RESPONSES_PER_LINK", "2")
    monkeypatch.setenv("REVIEW_RATE_PER_MINUTE", "600")
    get_settings.cache_clear()
    c = await campaign_of(client)
    version = await add_version(c)
    secret = (await make_link(client, c, [item(version)]))["token"]
    assert [(await decide(client, secret, version)).status_code for _ in range(3)] == [201, 201, 409]


# --- expiry, revocation, and what a link cannot do -----------------------------------------------------------------------


async def test_every_failure_of_a_link_is_the_same_404(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await add_version(c)
    expired = (await make_link(client, c, [item(version)]))["token"]
    revoked = (await make_link(client, c, [item(version)]))
    async with session() as s, s.begin():
        row = (await s.execute(select(m.ReviewLink).where(m.ReviewLink.token_hash == review_links.hash_secret(expired)))).scalar_one()
        row.expires_at = utcnow() - timedelta(seconds=1)
    assert (await client.post(f"{API}/review-links/{revoked['id']}/revoke")).status_code == 200
    bodies = []
    for headers in (review_headers(expired), review_headers(revoked["token"]), review_headers("x" * 43), {"Authorization": "Review short"},
                    {"Authorization": f"Bearer {expired}"}, {"Authorization": ""}):
        response = await client.get(REVIEW, headers=headers)
        assert response.status_code == 404, headers
        bodies.append(response.json()["error"]["message"])
    assert len(set(bodies)) == 1 and "expired or been revoked" in bodies[0]
    assert (await decide(client, expired, version)).status_code == 404 and (await decide(client, revoked["token"], version)).status_code == 404
    assert (await client.get(f"{c['base']}/review-links")).json()["items"][0]["status"] in ("revoked", "expired")


async def test_revoking_stops_the_link_at_once_and_keeps_its_decisions(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await add_version(c)
    link = await make_link(client, c, [item(version)])
    assert (await decide(client, link["token"], version)).status_code == 201
    revoked = await client.post(f"{API}/review-links/{link['id']}/revoke")
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked" and revoked.json()["response_count"] == 1
    first = revoked.json()["revoked_at"]
    assert (await open_page(client, link["token"])).status_code == 404
    assert (await client.post(f"{API}/review-links/{link['id']}/revoke")).json()["revoked_at"] == first, "revoking twice keeps the first revocation"
    assert (await client.get(f"{c['base']}/review-responses")).json()["total"] == 1


async def test_a_review_secret_opens_nothing_but_the_review_page(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await add_version(c)
    secret = (await make_link(client, c, [item(version)]))["token"]
    for path in (f"{c['base']}/readiness", f"{c['base']}/review-links", f"{c['base']}/versions", f"{API}/projects/{c['project']['id']}",
                 f"{c['base']}/region-plan", f"{c['base']}/asset-packs"):
        assert (await client.get(path, headers=review_headers(secret))).status_code == 401, path
    assert (await client.post(f"{c['base']}/review-links", headers=review_headers(secret),
                              json={"label": "x", "items": [item(version)]})).status_code == 401


async def test_roles_follow_the_workspace_rules(client_for: Any, client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await add_version(c)
    link = await make_link(client, c, [item(version)])
    await add_member(UUID(c["workspace_id"]), "bob", "viewer")
    bob = client_for(BOB)
    assert (await bob.get(f"{c['base']}/review-links")).status_code == 200, "any member reads"
    assert (await bob.get(f"{c['base']}/review-responses")).status_code == 200
    assert (await bob.post(f"{c['base']}/review-links", json={"label": "x", "items": [item(version)]})).status_code == 403
    assert (await bob.post(f"{API}/review-links/{link['id']}/revoke")).status_code == 403
    await add_member(UUID(c["workspace_id"]), "bob", "editor")
    assert (await bob.post(f"{c['base']}/review-links", json={"label": "x", "items": [item(version)]})).status_code == 201
    stranger = client_for({"Authorization": "Bearer dev-stranger"})
    assert (await stranger.get(f"{c['base']}/review-links")).status_code == 404
    assert (await stranger.post(f"{API}/review-links/{link['id']}/revoke")).status_code == 404


async def test_an_archived_project_takes_no_more_responses(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await add_version(c)
    secret = (await make_link(client, c, [item(version)]))["token"]
    async with session() as s, s.begin():
        (await s.get(m.Project, c["pid"])).status = "archived"
    assert (await decide(client, secret, version)).status_code == 409
    assert (await open_page(client, secret)).status_code == 200, "the page still reads"


# --- rate limiting -----------------------------------------------------------------------------------------------------------


async def test_the_public_endpoints_are_rate_limited_per_client_and_per_link(client: httpx.AsyncClient, seeded: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEW_RATE_PER_MINUTE", "4")
    get_settings.cache_clear()
    c = await campaign_of(client)
    version = await add_version(c)
    secret = (await make_link(client, c, [item(version)]))["token"]
    codes = [(await open_page(client, secret)).status_code for _ in range(6)]
    assert codes == [200, 200, 200, 200, 429, 429]
    limited = await open_page(client, "y" * 43)
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "RATE_LIMITED", "guessing is throttled by client address too"


def test_the_sliding_window_forgets_old_requests_and_bounds_its_memory() -> None:
    window = SlidingWindow(limit=2, window_seconds=10)
    assert [window.allow("a", now=t) for t in (0, 1, 2)] == [True, True, False]
    assert window.allow("a", now=10.5) is True and window.allow("b", now=2) is True
    small = SlidingWindow(limit=1, window_seconds=1000)
    for n in range(10_050):
        small.allow(f"k{n}", now=float(n))
    assert len(small._hits) <= 10_000


def test_reviewer_text_loses_control_characters_but_keeps_everything_else() -> None:
    assert review_links.clean("  Meera\x00\x07 R. க  ") == "Meera R. க"
    assert review_links.clean("\x00\x01") is None and review_links.clean(None) is None
    assert review_links.clean("a\nb") == "a\nb"
    assert dev_user_id("alice")  # the helper the support module relies on
