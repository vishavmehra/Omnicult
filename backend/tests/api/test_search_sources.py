"""Search over creative scenes, Risk Check findings and Creative Studio versions, registered through the document-source
hook (fake embedder; no provider call). Only the current X-Ray analysis is searchable, other projects' records never
appear, and demo projects are not indexed."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.db import models as m
from app.db.session import session
from app.services import search as service
from app.services import search_sources
from tests.api.glue_support import add_creative, add_risk_check, root_version
from tests.api.omnicult_support import seeded  # noqa: F401
from tests.api.proof_support import add_run
from tests.api.test_crud import make_campaign, make_project
from tests.api.test_search_claims import FakeEmbedder, embedder, find  # noqa: F401

PONGAL = [{"id": "headline", "kind": "headline", "value": "Pongal harvest festival offers", "language": "en", "script": "Latn"}]


async def project_with_records(client: httpx.AsyncClient) -> dict[str, Any]:
    project = await make_project(client)
    campaign = await make_campaign(client, project["id"])
    cid, pid = campaign["id"], project["id"]
    version = await root_version(client, cid, "Pongal original", PONGAL)
    creative, scene = await add_creative(cid, pid)
    run = await add_risk_check(cid, pid, version["id"], [{"severity": "medium", "observation": "A festival risk in the headline."}])
    return {"pid": pid, "cid": cid, "version": version, "creative": creative, "scene": scene, "run": run}


async def test_scenes_findings_and_versions_are_found_by_kind_with_their_labels_and_links(
    seeded: Any, client: httpx.AsyncClient, embedder: FakeEmbedder
) -> None:
    p = await project_with_records(client)
    scene = (await find(client, p["pid"], "rangoli scene", kinds="scene"))["hits"]
    assert [(h["kind"], h["id"], h["region_code"]) for h in scene] == [("scene", str(p["scene"]), "IN-TN")]
    assert scene[0]["ref"]["url"] == f"/api/v1/creatives/{p['creative']}/scenes/{p['scene']}" and scene[0]["title"].startswith("Diwali film: scene 1")
    assert (scene[0]["evidence_type"], scene[0]["claim_type"], scene[0]["retrieval_mode"]) == ("model_interpretation", "interpreted", "generated")
    assert "Partly model-generated" in scene[0]["explanation"]
    finding = (await find(client, p["pid"], "festival risk", kinds="finding"))["hits"]
    assert [h["kind"] for h in finding] == ["finding"] and finding[0]["region_code"] == "IN-TN"
    assert finding[0]["ref"]["url"] == f"/api/v1/campaigns/{p['cid']}/risk-checks/{p['run']}/findings"
    assert (finding[0]["evidence_type"], finding[0]["claim_type"]) == ("model_interpretation", "interpreted")
    assert "not legal advice" in finding[0]["explanation"]
    version = (await find(client, p["pid"], "pongal harvest festival", kinds="version"))["hits"]
    assert [(h["kind"], h["title"], h["id"]) for h in version] == [("version", "Pongal original", p["version"]["id"])]
    assert version[0]["ref"]["url"] == f"/api/v1/campaigns/{p['cid']}/versions/{p['version']['id']}"
    assert (version[0]["evidence_type"], version[0]["claim_type"], version[0]["retrieval_mode"]) == ("user_input", None, "user_input")
    assert {h["kind"] for h in (await find(client, p["pid"], "festival scene risk pongal rangoli"))["hits"]} >= {"scene", "finding", "version"}


async def test_unchanged_records_are_not_embedded_again_and_a_replaced_analysis_leaves_the_index(
    seeded: Any, client: httpx.AsyncClient, embedder: FakeEmbedder
) -> None:
    p = await project_with_records(client)
    assert (await find(client, p["pid"], "rangoli scene", kinds="scene"))["hits"]
    embedded = len(embedder.texts)
    await find(client, p["pid"], "festival risk", kinds="finding")
    assert len(embedder.texts) == embedded + 1  # only the query: scenes, findings and versions were unchanged
    newer = await add_run(p["pid"], p["cid"], run_type="creative_xray")  # a re-analysis that produced no scenes yet is not current
    async with session() as s, s.begin():
        creative = await s.get(m.CreativeAsset, p["creative"])
        assert creative is not None
        creative.current_run_id = newer
    assert (await find(client, p["pid"], "rangoli scene", kinds="scene"))["hits"] == []


async def test_other_projects_records_never_appear(seeded: Any, client: httpx.AsyncClient, embedder: FakeEmbedder) -> None:
    mine = await project_with_records(client)
    theirs = await project_with_records(client)
    ids = {h["id"] for h in (await find(client, mine["pid"], "rangoli scene festival risk pongal"))["hits"]}
    assert {str(mine["scene"]), mine["version"]["id"]} <= ids
    assert not ({str(theirs["scene"]), theirs["version"]["id"]} & ids)


@pytest.mark.parametrize("source", [search_sources.scene_documents, search_sources.finding_documents, search_sources.version_documents])
async def test_a_demo_project_is_never_indexed(seeded: Any, client: httpx.AsyncClient, source: Any) -> None:
    p = await project_with_records(client)
    async with session() as s:
        assert await source(s, SimpleNamespace(mode="demo", id=UUID(p["pid"]))) == []  # type: ignore[arg-type]
        assert await source(s, SimpleNamespace(mode="live", id=UUID(p["pid"]))) != []  # type: ignore[arg-type]


def test_the_three_sources_are_registered_once() -> None:
    registered = [fn for fn in service.DOCUMENT_SOURCES if fn.__module__ == search_sources.__name__]
    assert [fn.__name__ for fn in registered] == ["scene_documents", "finding_documents", "version_documents"]
