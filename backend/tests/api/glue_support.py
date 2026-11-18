"""Stored records for the glue tests: what Creative Studio, Creative X-Ray, Audience Lab and Pulse leave behind, written
straight into the database so the readers (Proof sections, search sources, observation gathering) are tested without a
model, a network or a media pipeline."""

from typing import Any
from uuid import UUID, uuid4

import httpx

from app.db import models as m
from app.db.base import utcnow
from app.db.session import session
from app.schemas import audience as aud
from app.schemas.population import ReactionDistribution
from app.schemas.studies import DimensionResult, DimensionResults
from tests.api.proof_support import add_run

API = "/api/v1"
ELEMENTS = [
    {"id": "headline", "kind": "headline", "value": "Happy Diwali from Acme", "language": "en", "script": "Latn"},
    {"id": "cta", "kind": "cta", "value": "Shop now", "language": "en", "script": "Latn"},
]


async def root_version(
    client: httpx.AsyncClient, campaign_id: str, label: str = "Original", elements: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    response = await client.post(f"{API}/campaigns/{campaign_id}/versions", json={"elements": elements or ELEMENTS, "label": label})
    assert response.status_code == 201, response.text
    return response.json()


async def edit_version(client: httpx.AsyncClient, campaign_id: str, version_id: str, value: str = "Light up Diwali") -> dict[str, Any]:
    body = {"version_id": version_id, "reason": "A tighter headline.",
            "operation": {"kind": "replace_text", "edits": [{"element_id": "headline", "set": {"value": value}}]}}
    response = await client.post(f"{API}/campaigns/{campaign_id}/operations", json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


def transcreate_line(element_id: str = "headline", *, passed: bool = True, protected_ok: bool = True, prohibited: bool = False,
                     script_ok: bool = True, claim_ids: list[UUID] | None = None) -> dict[str, Any]:
    problems = [] if passed else ["Letters of another script appear: Deva; expected Taml."]
    return {
        "element_id": element_id, "kind": "headline", "source_text": "Happy Diwali from Acme", "regional_copy": "Acme Deepavali vazhthukkal",
        "back_translation": "Happy Deepavali from Acme", "explanation": "Deepavali is the Tamil name of the festival.",
        "claim_ids": [str(c) for c in claim_ids or []], "reasoning_type": "evidence_supported" if claim_ids else "model_interpretation",
        "preserved_terms": ["Acme"],
        "script_check": {"expected_script": "Taml", "ok": script_ok, "dominant_script": "Latn", "shares": {}, "foreign_scripts": [],
                         "min_share": 0.5, "message": "checked"},
        "term_checks": {"protected_preserved": protected_ok, "missing_in_copy": [] if protected_ok else ["Acme"],
                        "missing_in_back_translation": [], "prohibited_in_copy": ["cheap"] if prohibited else [],
                        "prohibited_in_back_translation": [], "preferred_translation_missing": [], "preserved_terms": ["Acme"]},
        "passed": passed, "problems": problems,
    }


async def add_transcreation(
    campaign_id: str, project_id: str, source_id: str, lines: list[dict[str, Any]], *, region: str = "IN-TN", language: str = "ta",
    claim_ids: list[UUID] | None = None,
) -> tuple[UUID, UUID]:
    """An applied `transcreate` operation and the AI version it produced. Returns (operation id, version id)."""
    node_id, op_id, now = uuid4(), uuid4(), utcnow()
    async with session() as s, s.begin():
        s.add(m.VersionNode(
            id=node_id, campaign_id=UUID(campaign_id), project_id=UUID(project_id), parent_id=UUID(source_id),
            label=f"Transcreation: Tamil ({region})", actor="ai", region_code=region, language=language, settings={},
            elements=ELEMENTS, operation_id=op_id, created_at=now))
        await s.flush()
        s.add(m.Operation(
            id=op_id, campaign_id=UUID(campaign_id), project_id=UUID(project_id), source_version_id=UUID(source_id),
            result_version_id=node_id, kind="transcreate", target_element_ids=["headline"],
            params={"region_code": region, "language": language, "lines": lines}, reason="Transcreated 1 line into Tamil.",
            claim_ids=[str(c) for c in claim_ids or []], actor="ai", status="applied", created_at=now))
    return op_id, node_id


async def add_creative(
    campaign_id: str, project_id: str, *, region: str | None = "IN-TN", label: str = "Diwali film", cultural: list[dict[str, Any]] | None = None,
) -> tuple[UUID, UUID]:
    """A creative with one analysed scene. Returns (creative id, scene id)."""
    asset_id, creative_id, scene_id = uuid4(), uuid4(), uuid4()
    run_id = await add_run(project_id, campaign_id, run_type="creative_xray")
    now = utcnow()
    payload = {
        "frame_ms": [0], "on_screen_text": [{"text": "Diwali sale", "frame_ms": 0}],
        "transcript": [{"id": "t1", "start_ms": 0, "end_ms": 2000, "text": "Light a lamp this Diwali", "source": "transcription", "language": "en"}],
        "people": ["a family"], "gestures": [], "setting": "a lit courtyard", "objects": ["diya"], "colours": ["orange"], "music_mood": None,
        "claims": [{"text": "Diwali sale", "source": "on_screen_text", "segment_id": None}],
        "cultural_observations": cultural if cultural is not None else [
            {"id": "o1", "text": "A rangoli is drawn at the door.", "category": "symbol", "evidence": ["f1"], "claim_ids": []}],
        "cultural_interpretations": [{"id": "i1", "text": "The rangoli signals welcome.", "based_on": ["o1"], "category": "symbol",
                                      "limitations": [], "claim_ids": []}],
        "provenance": {}, "limitations": [],
    }
    async with session() as s, s.begin():
        s.add(m.Asset(
            id=asset_id, project_id=UUID(project_id), kind="video", filename="film.mp4", content_type="video/mp4", size_bytes=3,
            sha256="0" * 64, storage_name=f"t/{asset_id}", rights_confirmed=True))
        await s.flush()
        s.add(m.CreativeAsset(
            id=creative_id, project_id=UUID(project_id), campaign_id=UUID(campaign_id), asset_id=asset_id, kind="video", label=label,
            region_code=region, language="en", latest_run_id=run_id, current_run_id=run_id, created_at=now, updated_at=now))
        await s.flush()
        s.add(m.CreativeScene(
            id=scene_id, project_id=UUID(project_id), creative_asset_id=creative_id, campaign_id=UUID(campaign_id), asset_id=asset_id,
            run_id=run_id, position=0, start_ms=0, end_ms=4000, payload=payload, created_at=now))
    return creative_id, scene_id


def quick_read_response(*, survival: str = "understood", sentiment: str = "positive", relevance: int = 4, concern: bool = False) -> dict[str, Any]:
    return aud.QuickReadResponse(
        first_reaction="Warm and festive.", sentiment=sentiment, message=aud.MessageUnderstanding(restated="A Diwali offer.", survival=survival),  # type: ignore[arg-type]
        positives=[], negatives=[], confusion=[],
        regional_concerns=[aud.GroundedPoint(text="The colours may read as mourning.", basis="interpretation", claim_ids=[], claim_kinds=[])] if concern else [],
        ratings={"clarity": 4, "cultural_relevance": relevance, "cultural_risk": 2}, follow_up_question="Is it clear?", quoted_passage=None,
    ).model_dump(mode="json")


def quick_read_summary(n: int, *, disagree: bool = False) -> dict[str, Any]:
    dimension = DimensionResult(
        dimension="cultural_relevance", score=50.0, higher_is_better=True, n=n, distribution=[1, 1, 1, 1, 1], spread=1.4, disagreement=disagree,
        definition="d", interpretation="i", limitations=[])
    return aud.QuickReadSummary(
        sentiment=ReactionDistribution(denominator=n, failed=0, counts={"positive": n}, rates={"positive": 1.0}),
        message_survival=aud.MessageSurvival(understood=n, partial=0, misunderstood=0, denominator=n, understood_rate=1.0, note="n"),
        dimension_results=DimensionResults(cultural_relevance=dimension), positives=[], negatives=[], confusion=[], regional_concerns=[],
        suggested_follow_ups=[],
    ).model_dump(mode="json")


async def add_quick_read(
    campaign_id: str, project_id: str, version_ref: str | None, responses: list[dict[str, Any]], *, region: str = "IN-TN",
    status: str = "completed", disagree: bool = False, mode: str = "live", model: str = "gemini-3.5-flash-lite", seed: int = 42,
) -> UUID:
    run_id, now = uuid4(), utcnow()
    claim = {"id": str(uuid4()), "region_code": region, "category": "festival", "attribute": "major_festival", "value_text": "Pongal",
             "kind": "observed", "confidence": "high"}
    steps = [{"stage": "generating_reactions", "agent": "quick_read", "status": "completed", "provider": "google", "model_id": model,
              "prompt_version": "quick-read.v1", "latency_ms": 10, "retries": 0, "fallback_used": False, "usage": None, "error_code": None}]
    async with session() as s, s.begin():
        s.add(m.AudienceRun(
            id=run_id, project_id=UUID(project_id), campaign_id=UUID(campaign_id), kind="quick_read", status=status, mode=mode,
            region_codes=[region], version_ref=version_ref, seed=seed, config={}, steps=steps,
            inputs={"region": {"code": region, "name": "Tamil Nadu"}, "claims": [claim], "evidence_strength": {region: "partial"},
                    "panel": {"requested_size": len(responses), "states": [region], "languages": ["ta"], "city_tiers": ["tier1"],
                              "age_bands": ["25-34"], "weights": None, "seed": seed, "sampling_version": "panel-v1"}},
            result={"summary": quick_read_summary(len(responses), disagree=disagree), "grounding": {"cited_claim_ids": [claim["id"]]}},
            limitations=["Small panel."], created_at=now, completed_at=now))
        await s.flush()
        for ordinal, response in enumerate(responses):
            s.add(m.PanelParticipant(
                id=uuid4(), run_id=run_id, ordinal=ordinal, state_code=region, state_name="Tamil Nadu", language="ta", language_name="Tamil",
                city_tier="tier1", age_band="25-34", traits={}, persona="25-34, Tamil, tier1", response=response))
    return run_id


async def add_risk_check(
    campaign_id: str, project_id: str, version_ref: str | None, findings: list[dict[str, Any]], *, region: str = "IN-TN", status: str = "completed",
) -> UUID:
    """`findings`: dicts with severity, category, status, source, blocks_go (the rest is filled in)."""
    run_id, now = uuid4(), utcnow()
    async with session() as s, s.begin():
        s.add(m.AudienceRun(
            id=run_id, project_id=UUID(project_id), campaign_id=UUID(campaign_id), kind="risk_check", status=status, mode="live",
            region_codes=[region], version_ref=version_ref, config={}, steps=[], inputs={"region": {"code": region, "name": "Tamil Nadu"}, "claims": []},
            result={"dropped": {}}, limitations=[], created_at=now, completed_at=now))
        await s.flush()
        for ordinal, f in enumerate(findings):
            s.add(m.RiskFindingRow(
                id=uuid4(), run_id=run_id, ordinal=ordinal, element_id="headline", category=f.get("category", "regional_sensitivity"),
                severity=f.get("severity", "medium"), blocks_go=f.get("blocks_go", False), confidence_label="limited",
                anchor={"scene_id": None, "start_ms": None, "end_ms": None, "bbox": None}, quote="Happy Diwali", quote_start=0, quote_end=12,
                verification="quote_verified", observation=f.get("observation", "The headline says Happy Diwali."),
                interpretation="It may read as generic in this region.", suggested_fix="Name the regional festival.",
                ad_codes=[{"id": "a1", "document": "ASCI Code", "clause": "Chapter I.4", "title": "t", "url": "u", "excerpt": "e"}],
                claim_ids=[], source=f.get("source", "model_assessment"), severity_rules=[], rules_version="risk-rules-v1",
                status=f.get("status", "open"), limitations=[], created_at=now))
    return run_id
