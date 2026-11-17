"""Search over claims and claim sources (fake embedder; no provider call), workspace isolation, filters, and the
document-source hook other streams use for scenes, findings and versions."""

from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from app.db import models as m
from app.db.session import session
from app.llm.embeddings import Embeddings, EmbeddingSpace
from app.retrieval import RetrievalService
from app.retrieval.service import SearchDocument
from app.schemas.common import StepTrace
from app.schemas.graph import GraphRef
from app.services import search as service
from tests.api.omnicult_support import client_for, draft, put_claims, seeded, source, workspace_of  # noqa: F401
from tests.api.proof_support import API
from tests.api.test_crud import make_project
from tests.conftest import BOB

VOCAB = ["pongal", "harvest", "onam", "kolam", "boat", "census", "festival", "scene", "rangoli", "risk"]


class FakeEmbedder:
    def __init__(self) -> None:
        self.space = EmbeddingSpace("fake", "fake-embed", len(VOCAB))
        self.texts: list[str] = []

    def is_configured(self) -> bool:
        return True

    async def embed(self, texts: list[str], **kwargs: Any) -> Embeddings:
        self.texts += texts
        vectors = [[float(text.lower().count(word)) for word in VOCAB] for text in texts]
        return Embeddings(vectors=vectors, space=self.space, trace=StepTrace(stage="s", agent="a", status="completed"))


@pytest.fixture
def embedder(monkeypatch: pytest.MonkeyPatch) -> FakeEmbedder:
    fake = FakeEmbedder()
    monkeypatch.setattr(service, "get_retrieval_service", lambda mode, settings, store: RetrievalService(fake, store))
    return fake


async def find(client: httpx.AsyncClient, project_id: str, q: str, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/projects/{project_id}/search", params={"q": q, **params})
    assert response.status_code == 200, response.text
    return response.json()


async def claims_for(ws: UUID) -> None:
    await put_claims(ws, [
        draft("Pongal", region="IN-TN", sources=[source("wikimedia", excerpt="Pongal is a harvest festival of Tamil Nadu with rangoli patterns.", title="Pongal article"),
                                                  source("tn-gov", source_type="curated_reference", title="TN culture handbook")],
              text="Pongal is the main harvest festival."),
        draft("Onam", region="IN-KL", attribute="main_festival", sources=[source("kl-gov", source_type="curated_reference", title="Kerala handbook")],
              text="Onam is celebrated with a boat race.", ),
        draft("Kolam", region="IN-TN", attribute="symbol", category="symbol", kind="interpretation", sources=[],
              text="Kolam patterns welcome guests."),
    ])


async def test_claims_are_searched_by_statement_with_kind_confidence_region_and_a_link(
    seeded: Any, client: httpx.AsyncClient, embedder: FakeEmbedder
) -> None:
    ws = await workspace_of("alice")
    await claims_for(ws)
    project_id = (await make_project(client))["id"]
    result = await find(client, project_id, "pongal harvest festival", kinds="claim")
    assert result["status"] == "ok" and result["embedding_model"] == "fake-embed"
    top = result["hits"][0]
    assert (top["kind"], top["region_code"], top["retrieval_mode"], top["evidence_type"], top["claim_type"]) == ("claim", "IN-TN", "cached", "provider_result", "observed")
    claim_id = top["id"]
    assert top["ref"] == {"resource": "claim", "id": claim_id, "url": f"{API}/workspaces/{ws}/claims/{claim_id}"}
    assert top["snippet"] == "Pongal is the main harvest festival." and top["title"] == "Major festival (IN-TN)"
    assert "of kind observed with moderate confidence and 2 sources" in top["explanation"] and "ranking signal" in top["explanation"]
    linked = await client.get(top["ref"]["url"])  # a hit links to the record it came from
    assert linked.status_code == 200 and linked.json()["value_text"] == top["snippet"] and len(linked.json()["sources"]) == 2
    kolam = (await find(client, project_id, "kolam patterns", kinds="claim"))["hits"][0]
    assert (kolam["claim_type"], kolam["evidence_type"]) == ("interpreted", "model_interpretation") and "of kind interpretation with low confidence and 0 sources" in kolam["explanation"]


async def test_claim_sources_are_searched_by_their_quoted_text_and_link_to_their_claim(
    seeded: Any, client: httpx.AsyncClient, embedder: FakeEmbedder
) -> None:
    ws = await workspace_of("alice")
    await claims_for(ws)
    project_id = (await make_project(client))["id"]
    hit = (await find(client, project_id, "rangoli patterns", kinds="claim_source"))["hits"][0]
    assert (hit["kind"], hit["title"], hit["region_code"]) == ("claim_source", "Pongal article", "IN-TN")
    assert hit["snippet"] == "Pongal is a harvest festival of Tamil Nadu with rangoli patterns." and "quoted text" in hit["explanation"]
    assert hit["ref"]["resource"] == "claim_source" and hit["ref"]["url"].startswith(f"{API}/workspaces/{ws}/claims/")
    no_quote = (await find(client, project_id, "culture handbook", kinds="claim_source"))["hits"]
    assert any("no quoted text" in h["explanation"] for h in no_quote)  # a source without a quote is searched by what it is cited for


async def test_region_and_kind_filters_apply(seeded: Any, client: httpx.AsyncClient, embedder: FakeEmbedder) -> None:
    ws = await workspace_of("alice")
    await claims_for(ws)
    project_id = (await make_project(client))["id"]
    kerala = (await find(client, project_id, "festival boat", kinds="claim", region_code="IN-KL"))["hits"]
    assert [h["region_code"] for h in kerala] == ["IN-KL"] and "boat race" in kerala[0]["snippet"]
    assert (await find(client, project_id, "festival", region_code="IN-WB"))["hits"] == []
    both = await find(client, project_id, "festival", kinds=["claim", "claim_source"])
    assert {h["kind"] for h in both["hits"]} == {"claim", "claim_source"}
    assert (await client.get(f"{API}/projects/{project_id}/search", params={"q": "x", "region_code": "tamil"})).status_code == 422


async def test_a_workspace_never_finds_another_workspaces_claims_but_does_find_shared_ones(
    seeded: Any, client: httpx.AsyncClient, client_for: Any, embedder: FakeEmbedder
) -> None:
    alice_ws, bob_ws = await workspace_of("alice"), await workspace_of("bob")
    await put_claims(alice_ws, [draft("Pongal", sources=[source("wikimedia")], text="Alice private pongal harvest note.")])
    await put_claims(bob_ws, [draft("Onam", region="IN-KL", sources=[source("wikimedia")], text="Bob private onam note.")])
    await put_claims(None, [draft("Kolam", attribute="symbol", category="symbol", sources=[source("wikimedia"), source("gov", source_type="curated_reference")],
                                  text="Shared kolam reference claim.")])
    alice_project = (await make_project(client))["id"]
    bob = client_for(BOB)
    bob_project = (await make_project(bob))["id"]
    mine = await find(client, alice_project, "pongal onam kolam note", kinds="claim")
    texts = {h["snippet"] for h in mine["hits"]}
    assert "Alice private pongal harvest note." in texts and "Shared kolam reference claim." in texts and "Bob private onam note." not in texts
    theirs = await find(bob, bob_project, "pongal onam kolam note", kinds="claim")
    texts = {h["snippet"] for h in theirs["hits"]}
    assert "Bob private onam note." in texts and "Shared kolam reference claim." in texts and "Alice private pongal harvest note." not in texts
    async with session() as s:
        rows = (await s.execute(select(m.Embedding).where(m.Embedding.source_kind == "claim"))).scalars().all()
    assert {r.text for r in rows if r.project_id == UUID(bob_project)}.isdisjoint({"Alice private pongal harvest note."})
    assert (await bob.get(f"{API}/projects/{alice_project}/search", params={"q": "pongal"})).status_code == 404


async def test_the_index_follows_claim_changes_without_re_embedding_unchanged_ones(
    seeded: Any, client: httpx.AsyncClient, embedder: FakeEmbedder
) -> None:
    ws = await workspace_of("alice")
    await claims_for(ws)
    project_id = (await make_project(client))["id"]
    await find(client, project_id, "pongal", kinds="claim")
    embedded = len(embedder.texts)
    await find(client, project_id, "onam", kinds="claim")
    assert len(embedder.texts) == embedded + 1  # only the query: claims and sources were unchanged
    async with session() as s, s.begin():  # a claim a reviewer rejected leaves the index
        row = (await s.execute(select(m.Claim).where(m.Claim.attribute == "main_festival"))).scalar_one()
        row.status = "rejected"
    after = await find(client, project_id, "onam boat", kinds="claim")
    assert all("boat race" not in h["snippet"] for h in after["hits"])


async def test_other_streams_add_scenes_findings_and_versions_through_the_document_source_hook(
    seeded: Any, client: httpx.AsyncClient, embedder: FakeEmbedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "DOCUMENT_SOURCES", [])

    @service.register_document_source
    async def scenes(s: Any, project: m.Project) -> list[SearchDocument]:
        return [SearchDocument(
            kind="scene", source_id="scene-1", title="Opening scene", text="A rangoli scene at dawn with a risk of misreading colours.",
            ref=GraphRef(resource="scene", id="scene-1", url=None), retrieval_mode="generated", region_code="IN-MH",
            note="Scene 1 of the video.")]

    project_id = (await make_project(client))["id"]
    found = await find(client, project_id, "rangoli scene", kinds="scene")
    assert [(h["kind"], h["id"], h["region_code"]) for h in found["hits"]] == [("scene", "scene-1", "IN-MH")]
    assert "Scene 1 of the video." in found["hits"][0]["explanation"]
    assert (await find(client, project_id, "rangoli scene", kinds="claim"))["hits"] == []
    assert (await client.get(f"{API}/projects/{project_id}/search", params={"q": "x", "kinds": "finding"})).status_code == 200
    assert (await client.get(f"{API}/projects/{project_id}/search", params={"q": "x", "kinds": "version"})).status_code == 200
    assert (await client.get(f"{API}/projects/{project_id}/search", params={"q": "x", "kinds": "nonsense"})).status_code == 422


async def test_search_is_unavailable_not_broken_when_embeddings_are_not_configured(seeded: Any, client: httpx.AsyncClient) -> None:
    ws = await workspace_of("alice")
    await claims_for(ws)
    project_id = (await make_project(client))["id"]
    result = await find(client, project_id, "pongal", kinds="claim")
    assert (result["status"], result["hits"]) == ("unavailable", []) and result["message"]
