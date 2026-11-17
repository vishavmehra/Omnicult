"""Region profiles, the Evidence Meter and conflicts over HTTP, including cross-workspace and role checks."""

from datetime import date
from typing import Any, get_args
from uuid import UUID

import httpx
from sqlalchemy import select

from app.core.auth import dev_user_id
from app.db import models as m
from app.db.session import read_session
from app.schemas.claims import ClaimCategory
from tests.api.firebase_tokens import bearer
from tests.api.omnicult_support import (  # noqa: F401
    API,
    CAROL,
    add_member,
    client_for,
    draft,
    firebase_app,
    put_claims,
    seeded,
    source,
    workspace_of,
)
from tests.conftest import BOB

TODAY = date.today()
CATEGORIES = list(get_args(ClaimCategory))


def fresh(group: str, **kwargs: Any) -> Any:
    return source(group, TODAY, **kwargs)


def pair(group_a: str = "wikimedia", group_b: str = "gov") -> list[Any]:
    return [fresh(group_a), fresh(group_b, source_type="curated_reference")]


async def profile(client: httpx.AsyncClient, workspace_id: UUID, code: str = "IN-TN") -> dict[str, Any]:
    response = await client.get(f"{API}/workspaces/{workspace_id}/regions/{code}/profile")
    assert response.status_code == 200, response.text
    return response.json()


async def disagreement(workspace_id: UUID | None) -> None:
    await put_claims(workspace_id, [
        draft(0.89, attribute="language_share", category="language", sources=[source("census", date(2011, 3, 1), source_type="census_2011")]),
        draft(0.81, attribute="language_share", category="language", sources=pair()),
    ])


async def test_a_region_without_claims_is_weak_and_lists_every_category(seeded: Any, client: httpx.AsyncClient) -> None:
    ws = await workspace_of("alice")
    body = await profile(client, ws)
    assert [c["category"] for c in body["categories"]] == CATEGORIES and all(c["claims"] == [] for c in body["categories"])
    meter = body["meter"]
    assert meter["strength"] == "weak" and meter["strength_reasons"] == ["No claims are recorded for this region yet."]
    assert (meter["sources"], meter["claims"], meter["supported_claims"], meter["open_conflicts"]) == (0, 0, 0, 0)
    assert meter["categories_total"] == 14 and meter["categories_covered"] == 0
    assert meter["freshness"] == {"newest_source_date": None, "oldest_source_date": None, "median_age_days": None, "fresh_source_share": None}
    assert body["region"]["code"] == "IN-TN" and body["workspace_id"] == str(ws) and body["mode"] == "live"
    assert (await client.get(f"{API}/workspaces/{ws}/regions/IN-TN/evidence-meter")).json() == meter


async def test_every_claim_shows_its_five_tags(seeded: Any, client: httpx.AsyncClient) -> None:
    ws = await workspace_of("alice")
    await put_claims(ws, [draft("Pongal", sources=pair(), text="Pongal is the main harvest festival of Tamil Nadu.")])
    body = await profile(client, ws)
    festival = next(c for c in body["categories"] if c["category"] == "festival")["claims"]
    assert len(festival) == 1
    claim = festival[0]
    assert claim["value_text"] == "Pongal is the main harvest festival of Tamil Nadu." and claim["shared"] is False
    assert claim["kind"] == "observed" and claim["confidence"] == "moderate" and claim["effective_confidence"] == "moderate"
    assert claim["scope"] == {"country": "IN", "region_code": "IN-TN", "city_tier": None, "language": None, "period": None}
    assert claim["published_at"] is None and claim["retrieved_at"].startswith("2026-11-17")
    assert {s["independence_group"] for s in claim["sources"]} == {"wikimedia", "gov"}
    assert all(s["retrieved_at"] and s["source_identifier"] and s["published_at"] for s in claim["sources"])
    assert claim["confidence_reason"] and claim["stale"] is False and claim["conflict_ids"] == []


async def test_the_profile_shows_shared_claims_and_only_the_callers_own(seeded: Any, client: httpx.AsyncClient, client_for: Any) -> None:
    alice, bob = await workspace_of("alice"), await workspace_of("bob")
    await put_claims(None, [draft("Kolam", attribute="symbol", category="symbol", sources=pair())])
    await put_claims(alice, [draft("Alice-only note", attribute="custom_note", category="custom", sources=[fresh("brand", source_type="brand_upload")])])
    await put_claims(bob, [draft("Bob-only note", attribute="custom_note", category="custom", sources=[fresh("brand", source_type="brand_upload")])])
    mine = await profile(client, alice)
    values = {c["value_text"] for cat in mine["categories"] for c in cat["claims"]}
    assert values == {"symbol is Kolam", "custom_note is Alice-only note"}
    shared = next(c for cat in mine["categories"] for c in cat["claims"] if c["attribute"] == "symbol")
    assert shared["shared"] is True
    theirs = await profile(client_for(BOB), bob)
    assert {c["value_text"] for cat in theirs["categories"] for c in cat["claims"]} == {"symbol is Kolam", "custom_note is Bob-only note"}


async def test_other_workspaces_are_invisible_on_every_evidence_endpoint(seeded: Any, client: httpx.AsyncClient, client_for: Any) -> None:
    alice = await workspace_of("alice")
    await disagreement(alice)
    async with read_session() as s:
        conflict_id = (await s.execute(select(m.Conflict.id))).scalar_one()
    bob = client_for(BOB)
    paths = (
        ("get", f"/workspaces/{alice}/regions/IN-TN/profile"),
        ("get", f"/workspaces/{alice}/regions/IN-TN/evidence-meter"),
        ("get", f"/workspaces/{alice}/conflicts"),
        ("post", f"/workspaces/{alice}/conflicts/{conflict_id}/resolve"),
    )
    for method, path in paths:
        response = await getattr(bob, method)(f"{API}{path}", **({"json": {"decision": "accept"}} if method == "post" else {}))
        assert response.status_code == 404, (path, response.text)
    # naming a workspace the caller owns with another workspace's conflict id does not reach it either
    bobs = await workspace_of("bob")
    leak = await bob.post(f"{API}/workspaces/{bobs}/conflicts/{conflict_id}/resolve", json={"decision": "accept"})
    assert leak.status_code == 404
    async with read_session() as s:
        assert (await s.execute(select(m.Conflict.status))).scalar_one() == "open"  # untouched


async def test_unknown_region_and_malformed_codes(seeded: Any, client: httpx.AsyncClient) -> None:
    ws = await workspace_of("alice")
    assert (await client.get(f"{API}/workspaces/{ws}/regions/IN-ZZ/profile")).status_code == 404
    assert (await client.get(f"{API}/workspaces/{ws}/regions/tamil/profile")).status_code == 422
    assert (await client.get(f"{API}/workspaces/{ws}/conflicts", params={"region_code": "IN-ZZ"})).status_code == 404


async def test_meter_counts_sources_support_coverage_and_review(seeded: Any, client: httpx.AsyncClient) -> None:
    ws = await workspace_of("alice")
    old = source("census", date(2011, 3, 1), source_type="census_2011")
    await put_claims(ws, [
        draft("Pongal", sources=pair()),
        draft("Tamil", attribute="main_language", category="language", sources=[old]),
        draft("Kolam", attribute="symbol", category="symbol", kind="interpretation", sources=[]),
        draft("Sambar", attribute="staple", category="food", sources=[fresh("wikimedia")]),
    ])
    meter = (await client.get(f"{API}/workspaces/{ws}/regions/IN-TN/evidence-meter")).json()
    assert meter["claims"] == 4 and meter["supported_claims"] == 3  # the interpretation is not supported
    assert meter["sources"] == 3 and meter["stale_claims"] == 1  # wikimedia backs two claims but is one source
    assert meter["needs_review_claims"] == 1  # the interpretation
    assert meter["confidence"] == {"low": 3, "moderate": 1, "high": 0}
    coverage = {c["category"]: (c["claims"], c["supported_claims"]) for c in meter["coverage"]}
    assert coverage["festival"] == (1, 1) and coverage["symbol"] == (1, 0) and coverage["humour"] == (0, 0)
    assert meter["categories_covered"] == 3
    freshness = meter["freshness"]
    assert freshness["oldest_source_date"] == "2011-03-01" and freshness["newest_source_date"] == TODAY.isoformat()
    assert 0 < freshness["fresh_source_share"] < 1
    assert meter["strength"] == "weak" and any("supported claims" in r for r in meter["strength_reasons"])


async def test_a_well_evidenced_region_is_solid_and_an_unresolved_conflict_keeps_it_partial(seeded: Any, client: httpx.AsyncClient) -> None:
    ws = await workspace_of("alice")
    categories = ["festival", "food", "symbol", "colour", "family", "custom"]
    await put_claims(ws, [
        draft(f"value-{i}", attribute=f"attr_{i}", category=categories[i % 6], sources=pair(f"a{i}", f"b{i}"))
        for i in range(16)
    ])
    meter = (await client.get(f"{API}/workspaces/{ws}/regions/IN-TN/evidence-meter")).json()
    assert (meter["strength"], meter["strength_reasons"]) == ("solid", [])
    await disagreement(ws)
    meter = (await client.get(f"{API}/workspaces/{ws}/regions/IN-TN/evidence-meter")).json()
    assert meter["open_conflicts"] == 1 and meter["strength"] == "partial"
    assert any("unresolved conflict" in r for r in meter["strength_reasons"])


# --- conflicts ----------------------------------------------------------------------------


async def test_conflict_card_shows_both_values_sources_dates_scope_and_the_value_in_use(seeded: Any, client: httpx.AsyncClient) -> None:
    ws = await workspace_of("alice")
    await disagreement(ws)
    page = (await client.get(f"{API}/workspaces/{ws}/conflicts")).json()
    assert page["total"] == 1
    card = page["items"][0]
    assert card["status"] == "open" and card["region_code"] == "IN-TN" and card["resolutions"] == []
    a, b = card["claim_a"], card["claim_b"]
    assert {a["value"], b["value"]} == {0.89, 0.81}
    used = a if card["current_selection"] == "a" else b
    assert used["value"] == 0.81 and "higher confidence" in card["selection_reason"]
    for side in (a, b):  # both sides carry source, dates, scope and kind
        assert side["sources"] and side["scope"]["region_code"] == "IN-TN" and side["kind"] == "observed"
        assert side["retrieved_at"] and side["conflict_ids"] == [card["id"]]
    census = next(side for side in (a, b) if side["value"] == 0.89)
    assert census["sources"][0]["published_at"] == "2011-03-01" and census["stale"] is True
    # an unresolved conflict lowers the confidence of the claims that depend on it
    assert used["confidence"] == "moderate" and used["effective_confidence"] == "low"
    assert census["confidence"] == "low" and census["effective_confidence"] == "low"
    filtered = (await client.get(f"{API}/workspaces/{ws}/conflicts", params={"region_code": "IN-KL"})).json()
    assert filtered["items"] == []
    assert (await client.get(f"{API}/workspaces/{ws}/conflicts", params={"status": "resolved"})).json()["total"] == 0


async def test_reviewer_decisions_are_recorded_with_user_and_time(seeded: Any, client: httpx.AsyncClient) -> None:
    ws = await workspace_of("alice")
    await disagreement(ws)
    card = (await client.get(f"{API}/workspaces/{ws}/conflicts")).json()["items"][0]
    url = f"{API}/workspaces/{ws}/conflicts/{card['id']}/resolve"

    switched = (await client.post(url, json={"decision": "switch", "note": "Native reviewer prefers the census figure."})).json()
    assert switched["status"] == "resolved" and switched["current_selection"] != card["current_selection"]
    assert "Switched by a reviewer" in switched["selection_reason"]
    census = next(c for c in (switched["claim_a"], switched["claim_b"]) if c["value"] == 0.89)
    used = switched["claim_a"] if switched["current_selection"] == "a" else switched["claim_b"]
    assert used["value"] == 0.89 and census["effective_confidence"] == census["confidence"]  # resolved: no downgrade
    [decision] = switched["resolutions"]
    assert decision["decision"] == "switch" and decision["decided_by"] == str(dev_user_id("alice"))
    assert decision["note"] == "Native reviewer prefers the census figure." and decision["decided_at"]

    review = (await client.post(url, json={"decision": "request_review"})).json()
    assert review["status"] == "review_requested" and review["current_selection"] == switched["current_selection"]
    meter = (await client.get(f"{API}/workspaces/{ws}/regions/IN-TN/evidence-meter")).json()
    assert meter["open_conflicts"] == 1 and meter["needs_review_claims"] == 2  # both claims wait for a native review

    accepted = (await client.post(url, json={"decision": "accept"})).json()
    assert accepted["status"] == "resolved" and accepted["current_selection"] == review["current_selection"]
    assert [r["decision"] for r in accepted["resolutions"]] == ["switch", "request_review", "accept"]  # history is kept
    assert (await client.get(f"{API}/workspaces/{ws}/conflicts", params={"status": "resolved"})).json()["total"] == 1
    meter = (await client.get(f"{API}/workspaces/{ws}/regions/IN-TN/evidence-meter")).json()
    assert meter["open_conflicts"] == 0 and meter["needs_review_claims"] == 0
    async with read_session() as s:
        actions = (await s.execute(select(m.AuditLog.action, m.AuditLog.actor_user_id, m.AuditLog.workspace_id))).all()
    assert sorted(a for a, _, _ in actions) == ["conflict.accept", "conflict.request_review", "conflict.switch"]
    assert {(u, w) for _, u, w in actions} == {(dev_user_id("alice"), ws)}
    assert (await client.post(url, json={"decision": "delete"})).status_code == 422
    assert (await client.post(f"{API}/workspaces/{ws}/conflicts/{UUID(int=1)}/resolve", json={"decision": "accept"})).status_code == 404


async def test_both_claims_survive_every_decision(seeded: Any, client: httpx.AsyncClient) -> None:
    from tests.api.omnicult_support import all_claims

    ws = await workspace_of("alice")
    await disagreement(ws)
    card = (await client.get(f"{API}/workspaces/{ws}/conflicts")).json()["items"][0]
    await client.post(f"{API}/workspaces/{ws}/conflicts/{card['id']}/resolve", json={"decision": "switch"})
    assert sorted(c.value for c in await all_claims()) == [0.81, 0.89]  # a conflict is never silently removed


async def test_resolution_needs_a_reviewing_role(seeded: Any, client: httpx.AsyncClient, client_for: Any) -> None:
    ws = await workspace_of("alice")
    await disagreement(ws)
    card = (await client.get(f"{API}/workspaces/{ws}/conflicts")).json()["items"][0]
    url = f"{API}/workspaces/{ws}/conflicts/{card['id']}/resolve"
    await add_member(ws, "bob", "viewer")
    bob = client_for(BOB)
    assert (await bob.get(f"{API}/workspaces/{ws}/conflicts")).status_code == 200  # a viewer reads
    assert (await bob.get(f"{API}/workspaces/{ws}/regions/IN-TN/profile")).status_code == 200
    denied = await bob.post(url, json={"decision": "accept"})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "FORBIDDEN"
    await add_member(ws, "bob", "reviewer")
    assert (await bob.post(url, json={"decision": "request_review"})).status_code == 200
    await add_member(ws, "carol", "editor")
    assert (await client_for(CAROL).post(url, json={"decision": "accept"})).status_code == 200


async def test_anonymous_users_cannot_resolve_conflicts_but_can_read(firebase_app: Any) -> None:
    from app.db.session import session
    from app.reference.seed import seed_reference_data

    async with session() as s, s.begin():
        await seed_reference_data(s)
    transport = httpx.ASGITransport(app=firebase_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        visitor = bearer("uid-visitor", anonymous=True)
        me = (await client.get(f"{API}/me", headers=visitor)).json()
        ws = UUID(me["workspaces"][0]["id"])
        await disagreement(ws)
        assert (await client.get(f"{API}/workspaces/{ws}/regions/IN-TN/profile", headers=visitor)).status_code == 200
        card = (await client.get(f"{API}/workspaces/{ws}/conflicts", headers=visitor)).json()["items"][0]
        denied = await client.post(f"{API}/workspaces/{ws}/conflicts/{card['id']}/resolve", json={"decision": "accept"}, headers=visitor)
        assert denied.status_code == 403
        signed_in = bearer("uid-visitor", email="v@example.com")
        assert (await client.post(f"{API}/workspaces/{ws}/conflicts/{card['id']}/resolve", json={"decision": "accept"}, headers=signed_in)).status_code == 200


async def test_shared_claims_that_disagree_are_surfaced_to_every_workspace(seeded: Any, client: httpx.AsyncClient, client_for: Any) -> None:
    await disagreement(None)  # the seed loader records no conflicts; workspaces discover them when they look
    alice, bob = await workspace_of("alice"), await workspace_of("bob")
    mine = (await client.get(f"{API}/workspaces/{alice}/conflicts")).json()
    theirs = (await client_for(BOB).get(f"{API}/workspaces/{bob}/conflicts")).json()
    assert mine["total"] == theirs["total"] == 1 and mine["items"][0]["id"] != theirs["items"][0]["id"]
    # resolving in one workspace changes nothing for the other
    await client.post(f"{API}/workspaces/{alice}/conflicts/{mine['items'][0]['id']}/resolve", json={"decision": "switch"})
    again = (await client_for(BOB).get(f"{API}/workspaces/{bob}/conflicts")).json()["items"][0]
    assert again["status"] == "open" and again["resolutions"] == []
    async with read_session() as s:
        assert len((await s.execute(select(m.Claim))).scalars().all()) == 2  # the shared claims were not touched
