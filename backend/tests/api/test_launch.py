"""Launch Room endpoints: score comparison, readiness verdicts with history, approvals, roles and tenancy."""

from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from tests.api.firebase_tokens import bearer
from tests.api.launch_support import conflict, finding, observations_json, quick_read, risk
from tests.api.omnicult_support import API, add_member, client_for, firebase_app, seed, seeded  # noqa: F401
from tests.api.test_crud import make_campaign, make_project
from tests.conftest import BOB

TN, MH = "IN-TN", "IN-MH"


async def campaign_of(client: httpx.AsyncClient) -> dict[str, Any]:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    return {"project": project, "id": campaign["id"], "workspace_id": project["workspace_id"], "base": f"{API}/campaigns/{campaign['id']}"}


async def new_version(c: dict[str, Any]) -> UUID:
    """A Creative Studio version of the campaign: a verdict or an approval must point at one."""
    node = m.VersionNode(
        id=uuid4(), campaign_id=UUID(c["id"]), project_id=UUID(c["project"]["id"]), label="Original", actor="user", settings={},
        elements=[{"id": "headline", "kind": "headline", "value": "Happy Diwali"}], created_at=utcnow())
    async with session() as s, s.begin():
        s.add(node)
    return node.id


def readiness_body(version_id: UUID | None = None, region: str = TN, **changes: Any) -> dict[str, Any]:
    return {"region_code": region, "version_id": str(version_id or uuid4()), "observations": observations_json(**changes)}


def compare_body(region: str = TN, **second: Any) -> dict[str, Any]:
    return {"region_code": region, "versions": [
        {"version_id": str(uuid4()), "label": "Original", "observations": observations_json()},
        {"version_id": str(uuid4()), "label": "Tamil", "observations": observations_json(**second)},
    ]}


def approval_body(version_id: UUID | str, decision: str = "approve", region: str = TN, **extra: Any) -> dict[str, Any]:
    return {"region_code": region, "version_id": str(version_id), "decision": decision, "reason": "Reviewed with the regional lead.", **extra}


# --- Compare and Score ------------------------------------------------------------------------------


async def test_compare_scores_returns_explainable_cards_a_ranking_and_the_methodology(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    response = await client.post(f"{c['base']}/scores/compare", json=compare_body(quick_read=quick_read(understood=4, relevant=4).model_dump(mode="json")))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["scoring_version"] == "mvp-2" and result["region_code"] == TN
    assert [x["label"] for x in result["cards"]] == ["Original", "Tamil"]
    first = result["cards"][0]
    assert [d["dimension"] for d in first["dimensions"]] == [
        "message_clarity", "brand_fidelity", "cultural_relevance", "sensitivity_risk", "objective_consistency"]
    clarity = first["dimensions"][0]
    assert clarity["rule_ids"] and clarity["inputs_used"][0]["signal"] == "quick_read.understood_share" and clarity["explanation"]
    assert [x["label"] for x in result["ranking"]] == ["Original", "Tamil"] and result["meaningful_margin"] is True
    assert result["comparability"]["comparable"] is True
    assert {r["rule_id"] for r in result["methodology"]["rules"]} >= {"M1_quick_read_understanding", "A2_overall_weighted_utility"}
    async with read_session() as s:  # computing a comparison stores nothing
        assert await s.scalar(select(func.count(m.ReadinessVerdict.id))) == 0


async def test_compare_discloses_a_difference_in_model(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    body = compare_body()
    body["versions"][0]["observations"]["provenance"] = {"model_id": "model-a", "prompt_version": "p1"}
    body["versions"][1]["observations"]["provenance"] = {"model_id": "model-b", "prompt_version": "p1"}
    comparability = (await client.post(f"{c['base']}/scores/compare", json=body)).json()["comparability"]
    assert comparability["same_model"] is False and comparability["same_prompt_version"] is True and comparability["comparable"] is False
    assert any("model differs" in n and "model-a" in n and "model-b" in n for n in comparability["notes"])


async def test_compare_validates_input_and_the_region(client: httpx.AsyncClient, client_for: Any, seeded: Any) -> None:
    c = await campaign_of(client)
    one = compare_body()
    one["versions"] = one["versions"][:1]
    assert (await client.post(f"{c['base']}/scores/compare", json=one)).status_code == 422
    five = compare_body()
    five["versions"] = [{"version_id": str(uuid4()), "label": str(i), "observations": observations_json()} for i in range(5)]
    assert (await client.post(f"{c['base']}/scores/compare", json=five)).status_code == 422
    unknown = await client.post(f"{c['base']}/scores/compare", json=compare_body(region="IN-ZZ"))
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "NOT_FOUND"
    bad_counts = compare_body()
    bad_counts["versions"][0]["observations"]["quick_read"]["understood"] = 11
    assert (await client.post(f"{c['base']}/scores/compare", json=bad_counts)).status_code == 422
    signed_out = await client_for({}).post(f"{c['base']}/scores/compare", json=compare_body())
    assert signed_out.status_code == 401


# --- readiness --------------------------------------------------------------------------------------


async def test_computing_readiness_stores_a_verdict_bound_to_the_exact_version(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version_id = await new_version(c)
    response = await client.post(f"{c['base']}/readiness", json=readiness_body(version_id, region=MH))
    assert response.status_code == 201, response.text
    verdict = response.json()
    assert (verdict["verdict"], verdict["region_code"], verdict["version_id"]) == ("go", MH, str(version_id))
    assert verdict["region_name"] == "Maharashtra" and verdict["mode"] == "live" and verdict["is_latest"] is True
    assert verdict["rule_version"] == "ready-1" and verdict["rules_applied"] == ["G0_no_blocking_rule"]
    assert verdict["main_reason"] and verdict["next_action"] and verdict["confidence_limitations"]
    assert verdict["computed_by"] and len(verdict["input_fingerprint"]) == 64 and verdict["score"]["overall"] is not None
    async with read_session() as s:
        row = (await s.execute(select(m.ReadinessVerdict))).scalar_one()
        assert row.version_id == version_id and row.inputs["quick_read"]["synthetic"] is True and row.rule_version == "ready-1"
        assert await s.scalar(select(func.count(m.Approval.id))) == 0  # a verdict never approves anything


async def test_a_problem_version_gets_fix_or_rethink_with_a_reason_and_an_action(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    blocked = (await client.post(f"{c['base']}/readiness", json=readiness_body(
        await new_version(c), risk_check=risk(finding("f1", "low", blocks_go=True)).model_dump(mode="json")))).json()
    assert blocked["verdict"] == "fix" and blocked["highest_priority_issue"]["rule_id"] == "FX1_blocking_finding_unresolved"
    assert blocked["risk"]["blocking"] == 1 and "f1" in blocked["main_reason"]
    failed = (await client.post(f"{c['base']}/readiness", json=readiness_body(
        await new_version(c), quick_read=quick_read(understood=1).model_dump(mode="json")))).json()
    assert failed["verdict"] == "rethink" and failed["highest_priority_issue"]["rule_id"] == "RT1_message_not_understood"


async def test_identical_inputs_return_the_stored_verdict_and_changed_inputs_add_history(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version_id = await new_version(c)
    first = await client.post(f"{c['base']}/readiness", json=readiness_body(version_id))
    again = await client.post(f"{c['base']}/readiness", json=readiness_body(version_id))
    assert (first.status_code, again.status_code) == (201, 200) and again.json()["id"] == first.json()["id"]
    changed = await client.post(f"{c['base']}/readiness", json=readiness_body(
        version_id, risk_check=risk(finding("h1", "high")).model_dump(mode="json")))
    assert changed.status_code == 201 and changed.json()["verdict"] == "fix" and changed.json()["id"] != first.json()["id"]
    history = (await client.get(f"{c['base']}/readiness/history", params={"version_id": str(version_id)})).json()
    assert history["total"] == 2
    assert [(x["verdict"], x["is_latest"]) for x in history["items"]] == [("fix", True), ("go", False)]  # newest first


async def test_the_board_groups_verdicts_by_region_and_version_with_history_and_decisions(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    v1, v2 = await new_version(c), await new_version(c)
    await client.post(f"{c['base']}/readiness", json=readiness_body(v1, TN))
    await client.post(f"{c['base']}/readiness", json=readiness_body(v1, TN, risk_check=risk(finding("h1", "high")).model_dump(mode="json")))
    await client.post(f"{c['base']}/readiness", json=readiness_body(v2, TN))
    await client.post(f"{c['base']}/readiness", json=readiness_body(v1, MH))
    await client.post(f"{c['base']}/approvals", json=approval_body(v2, "approve", TN))
    board = (await client.get(f"{c['base']}/readiness")).json()
    assert board["campaign_id"] == c["id"] and "recommendation" in board["note"]
    assert [r["region_code"] for r in board["regions"]] == [MH, TN]  # by region name
    tn = board["regions"][1]["versions"]
    by_version = {x["verdict"]["version_id"]: x for x in tn}
    assert set(by_version) == {str(v1), str(v2)}
    assert (by_version[str(v1)]["verdict"]["verdict"], by_version[str(v1)]["history_count"]) == ("fix", 2)  # newest of two
    assert by_version[str(v1)]["latest_approval"] is None
    assert (by_version[str(v2)]["verdict"]["verdict"], by_version[str(v2)]["history_count"]) == ("go", 1)
    assert by_version[str(v2)]["latest_approval"]["decision"] == "approve"
    assert board["regions"][0]["versions"][0]["history_count"] == 1


async def test_history_filters_by_region_and_version_and_paginates(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await new_version(c)
    for i in range(3):
        await client.post(f"{c['base']}/readiness", json=readiness_body(version, TN, quick_read=quick_read(understood=5 + i).model_dump(mode="json")))
    await client.post(f"{c['base']}/readiness", json=readiness_body(await new_version(c), MH))
    everything = (await client.get(f"{c['base']}/readiness/history")).json()
    assert everything["total"] == 4
    page = (await client.get(f"{c['base']}/readiness/history", params={"region_code": TN, "limit": 2, "offset": 1})).json()
    assert (page["total"], len(page["items"]), page["limit"], page["offset"]) == (3, 2, 2, 1)
    assert (await client.get(f"{c['base']}/readiness/history", params={"region_code": MH})).json()["total"] == 1
    assert (await client.get(f"{c['base']}/readiness/history", params={"region_code": "IN-ZZ"})).status_code == 404
    assert (await client.get(f"{c['base']}/readiness/history", params={"region_code": "bad"})).status_code == 422


async def test_the_rules_are_served_as_documentation(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    rules = (await client.get(f"{c['base']}/readiness/rules")).json()
    assert rules["rule_version"] == "ready-1" and rules["scoring_version"] == "mvp-2" and len(rules["rules"]) == 20
    assert {r["effect"] for r in rules["rules"]} == {"fix", "rethink"} and set(rules["verdict_meanings"]) == {"go", "fix", "rethink"}
    assert rules["thresholds"]["min_panel"] == 5


async def test_demo_projects_mark_their_verdicts_as_demo(client: httpx.AsyncClient, seeded: Any) -> None:
    demo = (await client.post(f"{API}/projects/demo")).json()
    campaign = (await client.get(f"{API}/projects/{demo['id']}/campaigns")).json()["items"][0]
    demo_version = await new_version({"id": campaign["id"], "project": demo})
    verdict = (await client.post(f"{API}/campaigns/{campaign['id']}/readiness", json=readiness_body(demo_version))).json()
    assert verdict["mode"] == "demo"
    approval = (await client.post(f"{API}/campaigns/{campaign['id']}/approvals", json=approval_body(verdict["version_id"]))).json()
    assert approval["mode"] == "demo"


# --- approvals --------------------------------------------------------------------------------------


async def test_an_approval_records_the_person_the_reason_and_the_recommendation_in_force(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await new_version(c)
    verdict = (await client.post(f"{c['base']}/readiness", json=readiness_body(version))).json()
    response = await client.post(f"{c['base']}/approvals", json=approval_body(version))
    assert response.status_code == 201, response.text
    approval = response.json()
    assert approval["decision"] == "approve" and approval["reason"] == "Reviewed with the regional lead."
    assert approval["decided_by"] == str((await client.get(f"{API}/me")).json()["id"]) and approval["decided_at"]
    assert approval["readiness_verdict_id"] == verdict["id"] and approval["verdict_at_decision"] == "go"
    assert approval["overrides_recommendation"] is False and approval["region_code"] == TN and approval["version_id"] == str(version)


async def test_approving_against_a_fix_or_without_a_verdict_is_allowed_and_flagged(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    fix_version, bare_version = await new_version(c), await new_version(c)
    await client.post(f"{c['base']}/readiness", json=readiness_body(fix_version, risk_check=risk(finding("h1", "high")).model_dump(mode="json")))
    over_fix = (await client.post(f"{c['base']}/approvals", json=approval_body(fix_version))).json()
    assert over_fix["verdict_at_decision"] == "fix" and over_fix["overrides_recommendation"] is True
    unreviewed = (await client.post(f"{c['base']}/approvals", json=approval_body(bare_version))).json()
    assert unreviewed["verdict_at_decision"] is None and unreviewed["readiness_verdict_id"] is None
    assert unreviewed["overrides_recommendation"] is True
    rejected = (await client.post(f"{c['base']}/approvals", json=approval_body(fix_version, "reject"))).json()
    assert rejected["decision"] == "reject" and rejected["overrides_recommendation"] is False  # only an approval can override
    changes = (await client.post(f"{c['base']}/approvals", json=approval_body(fix_version, "request_changes"))).json()
    assert changes["decision"] == "request_changes"


async def test_the_verdict_an_approval_cites_must_match_the_campaign_region_and_version(client: httpx.AsyncClient, seeded: Any) -> None:
    c, other = await campaign_of(client), await campaign_of(client)
    version = await new_version(c)
    mine = (await client.post(f"{c['base']}/readiness", json=readiness_body(version))).json()
    theirs = (await client.post(f"{other['base']}/readiness", json=readiness_body(await new_version(other)))).json()
    for wrong in (approval_body(version, region=MH, readiness_verdict_id=mine["id"]),
                  approval_body(await new_version(c), readiness_verdict_id=mine["id"]),
                  approval_body(version, readiness_verdict_id=theirs["id"]),
                  approval_body(version, readiness_verdict_id=str(uuid4()))):
        response = await client.post(f"{c['base']}/approvals", json=wrong)
        assert response.status_code == 409 and response.json()["error"]["code"] == "CONFLICT", wrong
    assert (await client.post(f"{c['base']}/approvals", json=approval_body(version, readiness_verdict_id=mine["id"]))).status_code == 201


async def test_an_approval_needs_a_reason_a_known_decision_and_region(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await new_version(c)
    assert (await client.post(f"{c['base']}/approvals", json=approval_body(version) | {"reason": ""})).status_code == 422
    assert (await client.post(f"{c['base']}/approvals", json={k: v for k, v in approval_body(version).items() if k != "reason"})).status_code == 422
    assert (await client.post(f"{c['base']}/approvals", json=approval_body(version, "maybe"))).status_code == 422
    assert (await client.post(f"{c['base']}/approvals", json=approval_body(version, region="IN-ZZ"))).status_code == 404
    assert (await client.post(f"{c['base']}/approvals", json=approval_body(version) | {"decided_by": str(uuid4())})).status_code == 422  # the caller cannot name the approver


async def test_approvals_list_newest_first_with_filters(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    v1, v2 = await new_version(c), await new_version(c)
    await client.post(f"{c['base']}/approvals", json=approval_body(v1, "request_changes"))
    await client.post(f"{c['base']}/approvals", json=approval_body(v1, "approve"))
    await client.post(f"{c['base']}/approvals", json=approval_body(v2, "reject", MH))
    everything = (await client.get(f"{c['base']}/approvals")).json()
    assert everything["total"] == 3 and [x["decision"] for x in everything["items"]] == ["reject", "approve", "request_changes"]
    assert (await client.get(f"{c['base']}/approvals", params={"version_id": str(v1)})).json()["total"] == 2
    only_mh = (await client.get(f"{c['base']}/approvals", params={"region_code": MH})).json()
    assert [x["version_id"] for x in only_mh["items"]] == [str(v2)]
    assert len((await client.get(f"{c['base']}/approvals", params={"limit": 1, "offset": 1})).json()["items"]) == 1
    board_decision = (await client.get(f"{c['base']}/readiness")).json()
    assert board_decision["regions"] == []  # approvals alone do not create board rows; verdicts do


# --- roles ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("role", "allowed"), [("owner", True), ("editor", True), ("reviewer", True), ("viewer", False)])
async def test_only_owners_editors_and_reviewers_can_record_an_approval(
    client: httpx.AsyncClient, client_for: Any, seeded: Any, role: str, allowed: bool
) -> None:
    c = await campaign_of(client)
    await add_member(UUID(c["workspace_id"]), "bob", role)
    bob = client_for(BOB)
    response = await bob.post(f"{c['base']}/approvals", json=approval_body(await new_version(c)))
    if allowed:
        assert response.status_code == 201 and response.json()["decided_by"] != ""
        assert response.json()["decided_by_name"] is None or isinstance(response.json()["decided_by_name"], str)
    else:
        assert response.status_code == 403 and response.json()["error"]["code"] == "FORBIDDEN"
    async with read_session() as s:
        assert await s.scalar(select(func.count(m.Approval.id))) == (1 if allowed else 0)
    # every role can read
    for path in ("/approvals", "/readiness", "/readiness/history", "/readiness/rules"):
        assert (await bob.get(f"{c['base']}{path}")).status_code == 200, (role, path)


@pytest.mark.parametrize(("role", "allowed"), [("owner", True), ("editor", True), ("reviewer", False), ("viewer", False)])
async def test_only_owners_and_editors_can_compute_and_store_a_verdict(
    client: httpx.AsyncClient, client_for: Any, seeded: Any, role: str, allowed: bool
) -> None:
    c = await campaign_of(client)
    await add_member(UUID(c["workspace_id"]), "bob", role)
    bob = client_for(BOB)
    response = await bob.post(f"{c['base']}/readiness", json=readiness_body(await new_version(c)))
    assert response.status_code == (201 if allowed else 403)
    compare = await bob.post(f"{c['base']}/scores/compare", json=compare_body())
    assert compare.status_code == 200  # comparing stores nothing, so every role can do it


async def test_other_workspaces_cannot_reach_any_launch_room_endpoint(client: httpx.AsyncClient, client_for: Any, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await new_version(c)
    await client.post(f"{c['base']}/readiness", json=readiness_body(version))
    await client.post(f"{c['base']}/approvals", json=approval_body(version))
    bob = client_for(BOB)
    requests = [
        ("post", "/scores/compare", compare_body()),
        ("post", "/readiness", readiness_body()),
        ("get", "/readiness", None),
        ("get", "/readiness/history", None),
        ("get", "/readiness/rules", None),
        ("post", "/approvals", approval_body(version)),
        ("get", "/approvals", None),
    ]
    for method, path, body in requests:
        response = await getattr(bob, method)(f"{c['base']}{path}", **({"json": body} if body is not None else {}))
        assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND", (method, path)
    async with read_session() as s:  # nothing was written for bob and alice's records are untouched
        assert await s.scalar(select(func.count(m.ReadinessVerdict.id))) == 1
        assert await s.scalar(select(func.count(m.Approval.id))) == 1
    assert (await client.get(f"{c['base']}/approvals")).json()["total"] == 1


async def test_an_unknown_campaign_is_a_404(client: httpx.AsyncClient, seeded: Any) -> None:
    ghost = f"{API}/campaigns/{uuid4()}"
    assert (await client.get(f"{ghost}/readiness")).status_code == 404
    assert (await client.post(f"{ghost}/approvals", json=approval_body(uuid4()))).status_code == 404


async def test_an_archived_project_is_read_only_for_verdicts_and_approvals(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await new_version(c)
    await client.post(f"{c['base']}/readiness", json=readiness_body(version))
    assert (await client.delete(f"{API}/projects/{c['project']['id']}")).status_code == 204
    assert (await client.post(f"{c['base']}/readiness", json=readiness_body())).status_code == 409
    assert (await client.post(f"{c['base']}/approvals", json=approval_body(version))).status_code == 409
    assert (await client.get(f"{c['base']}/readiness")).status_code == 200


async def test_anonymous_visitors_cannot_record_an_approval(firebase_app: Any) -> None:
    await seed()
    transport = httpx.ASGITransport(app=firebase_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        visitor = bearer("uid-visitor", anonymous=True)
        demo = (await client.post(f"{API}/projects/demo", headers=visitor)).json()
        campaign = (await client.get(f"{API}/projects/{demo['id']}/campaigns", headers=visitor)).json()["items"][0]
        base = f"{API}/campaigns/{campaign['id']}"
        assert (await client.get(f"{base}/readiness", headers=visitor)).status_code == 200
        response = await client.post(f"{base}/approvals", json=approval_body(uuid4()), headers=visitor)
        assert response.status_code == 403 and response.json()["error"]["code"] == "FORBIDDEN"


async def test_important_operations_are_audited(client: httpx.AsyncClient, seeded: Any) -> None:
    c = await campaign_of(client)
    version = await new_version(c)
    await client.post(f"{c['base']}/readiness", json=readiness_body(version))
    await client.post(f"{c['base']}/approvals", json=approval_body(version, "reject"))
    async with read_session() as s:
        rows = (await s.execute(select(m.AuditLog).order_by(m.AuditLog.created_at))).scalars().all()
    actions = {r.action: r for r in rows}
    assert {"readiness.compute", "approval.reject"} <= set(actions)
    assert actions["approval.reject"].actor_user_id is not None and actions["approval.reject"].detail["region"] == TN
    assert "reason" not in actions["approval.reject"].detail  # free text stays out of the audit trail
