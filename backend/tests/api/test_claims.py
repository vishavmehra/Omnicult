"""Claim persistence: drafts become claims with computed confidence, repeated retrievals merge, conflicts are recorded,
and the Evidence Meter is honest about weak regions."""

from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.core.auth import dev_user_id
from app.db import models as m
from app.db.session import read_session
from tests.api.omnicult_support import (  # noqa: F401
    NOW,
    all_claims,
    draft,
    put_claims,
    seed,
    seeded,
    source,
    workspace_of,
)


async def test_a_draft_becomes_a_claim_with_its_sources_and_computed_confidence(seeded: Any) -> None:
    ws = await workspace_of("alice")
    result = await put_claims(ws, [draft("Pongal", sources=[source("wikimedia")])])
    assert (result.created, result.updated, result.rejected, result.conflicts_opened) == (1, 0, [], 0)
    claim = (await all_claims())[0]
    assert claim.workspace_id == ws and claim.kind == "observed" and claim.status == "active" and claim.mode == "live"
    assert claim.value == "Pongal" and claim.scope["region_code"] == "IN-TN" and claim.category == "festival"
    assert claim.confidence == "low" and "One source" in claim.confidence_reason
    async with read_session() as s:
        region = await s.scalar(select(m.Region.id).where(m.Region.code == "IN-TN"))
        assert claim.region_id == region
        sources = (await s.execute(select(m.ClaimSource))).scalars().all()
    assert [(x.source_type, x.independence_group, x.published_at) for x in sources] == [("wikidata", "wikimedia", date(2026, 1, 1))]


async def test_confidence_is_computed_from_sources_and_follows_new_ones(seeded: Any) -> None:
    ws = await workspace_of("alice")
    await put_claims(ws, [draft("Pongal", sources=[source("wikimedia")])])
    await put_claims(ws, [draft("Pongal", sources=[source("wikimedia", source_type="wikipedia", identifier="en:Pongal")])])
    assert (await all_claims())[0].confidence == "low"  # same independence group: still one source
    await put_claims(ws, [draft("Pongal", sources=[source("tamil-nadu-gov", source_type="curated_reference")])])
    claim = (await all_claims())[0]
    assert claim.confidence == "moderate" and "wikimedia" in claim.confidence_reason
    await put_claims(ws, [draft("Pongal", sources=[source("native-reviewers", source_type="reviewer", identifier="rev-1")])])
    assert (await all_claims())[0].confidence == "high"
    async with read_session() as s:
        assert await s.scalar(select(func.count(m.ClaimSource.id))) == 4  # sources accumulate on one claim


async def test_a_repeated_retrieval_does_not_duplicate_the_claim_or_its_source(seeded: Any) -> None:
    ws = await workspace_of("alice")
    again = draft("Pongal", sources=[source("wikimedia")], text="Pongal is the harvest festival.")
    first = await put_claims(ws, [again])
    second = await put_claims(ws, [again])
    assert (first.created, second.created, second.updated) == (1, 0, 1)
    assert len(await all_claims()) == 1
    async with read_session() as s:
        assert await s.scalar(select(func.count(m.ClaimSource.id))) == 1
    # the same statement with equivalent formatting is the same claim; a different one is not
    await put_claims(ws, [draft("  pongal ", sources=[source("wikimedia")])])
    assert len(await all_claims()) == 1
    await put_claims(ws, [draft("Onam", sources=[source("wikimedia")])])
    assert len(await all_claims()) == 2


async def test_model_output_cannot_claim_confidence(seeded: Any) -> None:
    ws = await workspace_of("alice")
    await put_claims(ws, [
        draft("Pongal is auspicious", kind="interpretation", sources=[]),
        draft("Kolam", attribute="symbol", category="symbol", kind="interpretation",
              sources=[source("google", source_type="gemini_grounding"), source("wikimedia")]),
    ])
    assert {c.confidence for c in await all_claims()} == {"low"}  # an interpretation never exceeds Low


async def test_invalid_drafts_are_reported_not_stored(seeded: Any) -> None:
    ws = await workspace_of("alice")
    result = await put_claims(ws, [
        draft("Pongal", sources=[]),  # observed without a source
        draft("Onam", sources=[source("wikimedia")], text="  "),
        draft("Vishu", sources=[source("wikimedia")]),
    ])
    assert [index for index, _ in result.rejected] == [0, 1]
    assert result.created == 1 and [c.value for c in await all_claims()] == ["Vishu"]


async def test_disagreeing_claims_are_both_kept_and_recorded_as_a_conflict(seeded: Any) -> None:
    ws = await workspace_of("alice")
    result = await put_claims(ws, [
        draft(0.89, attribute="language_share", category="language", sources=[source("census", date(2011, 3, 1), source_type="census_2011")]),
        draft(0.81, attribute="language_share", category="language", sources=[source("wikimedia"), source("survey", source_type="curated_reference")]),
    ])
    assert result.created == 2 and result.conflicts_opened == 1
    assert len(await all_claims()) == 2
    async with read_session() as s:
        conflict = (await s.execute(select(m.Conflict))).scalar_one()
    assert conflict.status == "open" and conflict.workspace_id == ws
    assert "language_share" in conflict.reason and "0.89" in conflict.reason and "0.81" in conflict.reason
    # the better-evidenced value (two independent fresh sources, Moderate) is the one in use, with the reason shown
    chosen = (await all_claims())
    used = next(c for c in chosen if c.id == (conflict.claim_a_id if conflict.current_selection == "a" else conflict.claim_b_id))
    assert used.value == 0.81 and "higher confidence" in conflict.selection_reason
    again = await put_claims(ws, [draft(0.81, attribute="language_share", category="language", sources=[source("wikimedia")])])
    assert again.conflicts_opened == 0  # recorded once


async def test_a_workspace_claim_can_conflict_with_a_shared_claim_but_only_for_that_workspace(seeded: Any) -> None:
    alice, bob = await workspace_of("alice"), await workspace_of("bob")
    shared = draft("Pongal", sources=[source("wikimedia"), source("gov", source_type="curated_reference")])
    await put_claims(None, [shared])
    mine = await put_claims(alice, [draft("Puthandu", sources=[source("brand", source_type="brand_upload")])])
    assert mine.conflicts_opened == 1
    none = await put_claims(bob, [draft("Onam", attribute="major_food", category="food", sources=[source("wikimedia")])])
    assert none.conflicts_opened == 0
    async with read_session() as s:
        workspaces = (await s.execute(select(m.Conflict.workspace_id))).scalars().all()
        shared_row = (await s.execute(select(m.Claim).where(m.Claim.workspace_id.is_(None)))).scalar_one()
    assert workspaces == [alice] and shared_row.value == "Pongal"


async def test_the_same_statement_owned_by_two_workspaces_is_two_claims(seeded: Any) -> None:
    alice, bob = await workspace_of("alice"), await workspace_of("bob")
    for ws in (alice, bob, None):
        await put_claims(ws, [draft("Pongal", sources=[source("wikimedia")])])
    assert sorted(str(c.workspace_id) for c in await all_claims()) == sorted([str(alice), str(bob), "None"])


async def test_demo_fixture_claims_stay_apart_from_live_ones(seeded: Any) -> None:
    ws = await workspace_of("alice")
    await put_claims(ws, [draft("Pongal", sources=[source("wikimedia")])], mode="live")
    await put_claims(ws, [draft("Onam", sources=[source("wikimedia")])], mode="demo")
    assert {c.mode: c.value for c in await all_claims()} == {"live": "Pongal", "demo": "Onam"}
    async with read_session() as s:
        assert await s.scalar(select(func.count(m.Conflict.id))) == 0  # different modes never conflict


async def test_expiry_and_stale_claims_are_reported(seeded: Any) -> None:
    from app.services.claims import build_region_profile

    ws = await workspace_of("alice")
    old = source("census", date(2011, 3, 1), source_type="census_2011")
    await put_claims(ws, [
        draft("Tamil", attribute="main_language", category="language", sources=[old]),
        draft("Kolam", attribute="symbol", category="symbol", sources=[source("wikimedia"), source("gov", source_type="curated_reference")]),
    ])
    profile = await build_region_profile(dev_user_id("alice"), ws, "IN-TN", now=NOW)
    stale = {c.attribute: c.stale for cat in profile.categories for c in cat.claims}
    assert stale == {"main_language": True, "symbol": False}
    assert profile.meter.stale_claims == 1 and profile.meter.freshness.oldest_source_date == date(2011, 3, 1)
    assert NOW.year == 2026  # the fixtures are anchored to a fixed date
