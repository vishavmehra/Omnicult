"""Evidence Map: claim, source, conflict and region nodes, drawn only from stored links."""

from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import delete, select

from app.db import models as m
from app.db.session import read_session, session
from tests.api.omnicult_support import add_member, client_for, draft, put_claims, seeded, source, workspace_of  # noqa: F401
from tests.api.proof_support import API, campaign_with_regions, tamil_nadu_claims
from tests.conftest import BOB

PERSISTED_FIELDS = {
    "claim_sources.claim_id", "claims.region_id", "conflicts.claim_a_id", "conflicts.claim_b_id", "conflicts.region_id",
    "proof_reports.content.referenced_claim_ids", "proof_reports.content.referenced_conflict_ids",
}


async def graph(client: httpx.AsyncClient, project_id: str, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/projects/{project_id}/evidence-graph", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def of_kind(g: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [n for n in g["nodes"] if n["kind"] == kind]


async def test_claims_sources_conflicts_and_regions_are_drawn_from_stored_rows(seeded: Any, client: httpx.AsyncClient) -> None:
    setup = await campaign_with_regions(client, ("IN-TN",))
    await tamil_nadu_claims(setup["workspace_id"])
    g = await graph(client, setup["project"]["id"], campaign_id=setup["campaign"]["id"])
    claims, sources, conflicts, regions = (of_kind(g, k) for k in ("claim", "claim_source", "conflict", "region"))
    assert len(claims) == 5 and len(conflicts) == 1 and [r["id"] for r in regions] == ["region:IN-TN"]  # Kerala is not a target
    pongal = next(n for n in claims if n["label"] == "Pongal is the main harvest festival.")
    assert (pongal["claim_type"], pongal["retrieval_mode"], pongal["confidence"], pongal["evidence_type"]) == ("observed", "cached", "moderate", None)
    assert pongal["ref"] == {"resource": "claim", "id": pongal["id"].split(":")[1], "url": f"{API}/workspaces/{setup['workspace_id']}/claims/{pongal['id'].split(':')[1]}"}
    assert next(n for n in claims if n["label"].startswith("Kolam"))["claim_type"] == "interpreted"
    nodes = {n["id"] for n in g["nodes"]}
    for edge in g["edges"]:
        assert edge["source"] in nodes and edge["target"] in nodes and edge["provenance"]
    relations = {(e["relation"], e["provenance"]) for e in g["edges"]}
    assert {("supported_by", "claim_sources.claim_id"), ("applies_to", "claims.region_id"), ("conflicts_with", "conflicts.claim_a_id"),
            ("conflicts_with", "conflicts.claim_b_id"), ("applies_to", "conflicts.region_id")} <= relations
    supported = [e for e in g["edges"] if e["relation"] == "supported_by"]
    assert len(supported) == len(sources) == 6 and all(e["source"].startswith("claim:") and e["target"].startswith("source:") for e in supported)


async def test_every_edge_is_backed_by_a_stored_row_and_nothing_is_inferred(seeded: Any, client: httpx.AsyncClient) -> None:
    setup = await campaign_with_regions(client, ("IN-TN",))
    ws = setup["workspace_id"]
    await tamil_nadu_claims(ws)
    g = await graph(client, setup["project"]["id"], campaign_id=setup["campaign"]["id"])
    claim_edges = [e for e in g["edges"] if e["relation"] in ("supported_by", "applies_to", "conflicts_with")]
    assert claim_edges and {e["provenance"] for e in claim_edges} <= PERSISTED_FIELDS  # each names the stored column behind it
    in_view = {UUID(n["id"].split(":")[1]) for n in of_kind(g, "claim")}  # the Kerala claim is not in this campaign's view
    async with read_session() as s:
        stored_sources = {(src.claim_id, src.id) for src in (await s.execute(select(m.ClaimSource))).scalars() if src.claim_id in in_view}
        stored_conflicts = {(c.id, c.claim_a_id, c.claim_b_id) for c in (await s.execute(select(m.Conflict))).scalars() if c.claim_a_id in in_view}
    drawn_sources = {(UUID(e["source"].split(":")[1]), UUID(e["target"].split(":")[1])) for e in g["edges"] if e["relation"] == "supported_by"}
    assert drawn_sources == stored_sources
    drawn_conflicts = {(UUID(e["source"].split(":")[1]), UUID(e["target"].split(":")[1])) for e in g["edges"] if e["relation"] == "conflicts_with"}
    assert drawn_conflicts == {(cid, claim) for cid, a, b in stored_conflicts for claim in (a, b)}
    # remove the stored conflict: the two claims still disagree, but no conflict node or link is drawn
    async with session() as s, s.begin():
        await s.execute(delete(m.ConflictResolution))
        await s.execute(delete(m.Conflict))
    again = await graph(client, setup["project"]["id"], campaign_id=setup["campaign"]["id"])
    assert of_kind(again, "conflict") == [] and not [e for e in again["edges"] if e["relation"] == "conflicts_with"]
    assert len(of_kind(again, "claim")) == 5  # both disagreeing claims are still there


async def test_claims_appear_only_when_a_region_or_a_campaign_with_regions_is_selected(seeded: Any, client: httpx.AsyncClient) -> None:
    setup = await campaign_with_regions(client, ("IN-TN",))
    await tamil_nadu_claims(setup["workspace_id"])
    project_id = setup["project"]["id"]
    plain = await graph(client, project_id)
    assert not [n for n in plain["nodes"] if n["kind"] in ("claim", "claim_source", "conflict", "region")]
    assert any("when a region_code is given" in x for x in plain["limitations"])
    by_region = await graph(client, project_id, region_code="IN-KL")
    assert [n["label"] for n in of_kind(by_region, "claim")] == ["Onam is the main harvest festival."]
    assert any("Claims shown for region IN-KL only" in x for x in by_region["limitations"])
    from tests.api.test_crud import make_campaign

    no_regions = await make_campaign(client, project_id)  # a campaign with no target regions draws no claims
    assert not of_kind(await graph(client, project_id, campaign_id=no_regions["id"]), "claim")
    assert (await client.get(f"{API}/projects/{project_id}/evidence-graph", params={"region_code": "tamil"})).status_code == 422


async def test_a_report_links_to_the_claims_and_conflicts_it_shows(seeded: Any, client: httpx.AsyncClient) -> None:
    setup = await campaign_with_regions(client, ("IN-TN",))
    await tamil_nadu_claims(setup["workspace_id"])
    report = (await client.post(f"{API}/campaigns/{setup['campaign']['id']}/proof-reports", json={})).json()
    g = await graph(client, setup["project"]["id"], campaign_id=setup["campaign"]["id"])
    node = next(n for n in g["nodes"] if n["id"] == f"report:{report['id']}")
    assert node["kind"] == "report" and node["ref"]["url"] == f"{API}/proof-reports/{report['id']}"
    cited = {e["target"] for e in g["edges"] if e["source"] == node["id"] and e["relation"] == "references"}
    assert {f"claim:{c}" for c in report["referenced_claim_ids"] if f"claim:{c}" in {n["id"] for n in g["nodes"]}} <= cited
    assert {f"conflict:{c}" for c in report["referenced_conflict_ids"]} <= cited and cited
    provenance = {e["provenance"] for e in g["edges"] if e["source"] == node["id"]}
    assert provenance <= {"proof_reports.content.referenced_claim_ids", "proof_reports.content.referenced_conflict_ids"}


async def test_the_map_never_shows_another_workspaces_claims(seeded: Any, client: httpx.AsyncClient, client_for: Any) -> None:
    setup = await campaign_with_regions(client, ("IN-TN",))
    bob_ws = await workspace_of("bob")
    await put_claims(bob_ws, [draft("Bob secret", sources=[source("wikimedia")], text="Bob secret festival claim.")])
    await put_claims(setup["workspace_id"], [draft("Pongal", sources=[source("wikimedia")], text="Alice festival claim.")])
    await put_claims(None, [draft("Kolam", attribute="symbol", category="symbol", sources=[source("wikimedia"), source("gov", source_type="curated_reference")],
                                  text="Shared reference claim.")])
    g = await graph(client, setup["project"]["id"], region_code="IN-TN")
    assert {n["label"] for n in of_kind(g, "claim")} == {"Alice festival claim.", "Shared reference claim."}
    bob = client_for(BOB)
    assert (await bob.get(f"{API}/projects/{setup['project']['id']}/evidence-graph", params={"region_code": "IN-TN"})).status_code == 404
    await add_member(setup["workspace_id"], "bob", "viewer")
    assert {n["label"] for n in of_kind(await graph(bob, setup["project"]["id"], region_code="IN-TN"), "claim")} == {"Alice festival claim.", "Shared reference claim."}


async def test_a_node_cap_drops_claim_nodes_and_the_links_touching_them(seeded: Any, client: httpx.AsyncClient) -> None:
    setup = await campaign_with_regions(client, ("IN-TN",))
    await tamil_nadu_claims(setup["workspace_id"])
    g = await graph(client, setup["project"]["id"], campaign_id=setup["campaign"]["id"], limit=10)
    assert g["truncated"] is True and len(g["nodes"]) == 10
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])
    assert any("Capped at 10 nodes" in x for x in g["limitations"])
