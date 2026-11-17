"""Wikidata adapter against exchanges recorded from the live service (tests/fixtures/culture): resolution and provenance."""

import httpx
import pytest

from app.integrations.culture.adapters.wikidata import SCRIPT_CODES, WikidataSource
from tests.unit.culture.culture_helpers import UA, load_recording, replay_client, scripted_client


async def resolve(name: str):
    call = load_recording(name)["call"]
    async with replay_client(name) as client:
        return await WikidataSource(user_agent=UA, client=client).resolve_entity(
            call["query"], language=call["language"], region_code=call["region_code"])


async def signals(name: str):
    call = load_recording(name)["call"]
    async with replay_client(name) as client:
        return await WikidataSource(user_agent=UA, client=client).related_signals(
            call["entity_id"], region_code=call["region_code"], limit=call["limit"])


async def test_an_alias_collision_stays_ambiguous():
    # Wikidata lists "Pongal" as the label of two items and as an alias of Makar Sankranti.
    result = await resolve("resolve_pongal")
    ids = {c.entity_id: c for c in result.candidates}
    assert result.status == "ambiguous" and result.entity is None
    assert ids["Q10253"].match_type == "alias" and ids["Q10253"].label == "Makar Sankranti"
    assert ids["Q29271"].match_type == "label" and ids["Q29271"].label == "Pongal"
    assert "match the query exactly" in (result.note or "")


async def test_two_items_with_the_same_label_stay_ambiguous():
    result = await resolve("resolve_thrissur_pooram")
    exact = [c for c in result.candidates if c.label == "Thrissur Pooram"]
    assert result.status == "ambiguous" and len(exact) == 2 and result.entity is None


async def test_one_exact_match_resolves_and_keeps_the_alternatives():
    result = await resolve("resolve_gudi_padwa")
    assert result.status == "resolved" and result.entity.entity_id == "Q615384"
    assert result.entity.url == "https://www.wikidata.org/wiki/Q615384" and result.sources == ["wikidata"]
    assert result.retrieved_at.tzinfo is not None


async def test_the_regional_language_is_searched_too():
    seen: list[httpx.Request] = []
    body = {"search": []}
    async with scripted_client([httpx.Response(200, json=body)] * 2, seen) as client:
        result = await WikidataSource(user_agent=UA, client=client).resolve_entity("பொங்கல்", language="ta", region_code="IN-TN")
    assert [r.url.params["language"] for r in seen] == ["ta", "en"] and result.status == "unresolved"
    assert all(r.url.params["action"] == "wbsearchentities" for r in seen)


async def test_entity_statements_carry_full_provenance():
    claims = await signals("signals_onam")
    assert len(claims) == 4
    for claim in claims:
        assert claim.kind == "observed" and claim.subject == "entity:Q1969250"
        (source,) = claim.sources
        assert source.source_type == "wikidata" and source.source_identifier == "Q1969250"
        assert source.url == "https://www.wikidata.org/wiki/Q1969250" and source.publisher == "Wikidata"
        assert source.independence_group == "wikimedia" and source.retrieved_at.tzinfo is not None
        assert source.published_at is not None  # the item's last-modified date
    located = next(c for c in claims if c.attribute == "wikidata_located_in_q1186")
    assert located.value["target_id"] == "Q1186" and located.scope.region_code == "IN-KL"  # names the region
    assert claims[0] is located  # region-linked statements come first
    assert next(c for c in claims if c.attribute == "wikidata_country_q668").scope.region_code is None
    keys = [(c.subject, c.attribute, c.scope.model_dump_json()) for c in claims]
    assert len(keys) == len(set(keys))  # two instance-of statements are two facts, never one fact with two values


async def test_region_seed_returns_languages_scripts_and_linked_items():
    claims = await signals("signals_region_tn")
    languages = {c.value: c for c in claims if c.attribute == "official_language"}
    assert set(languages) == {"Tamil", "English"} and languages["Tamil"].scope.language == "ta"
    assert languages["Tamil"].category == "language" and languages["Tamil"].sources[0].source_identifier == "Q1445"
    scripts = [c for c in claims if c.category == "script"]
    assert scripts and all(c.value["iso15924"] in SCRIPT_CODES for c in scripts)  # no Vatteluttu, Deseret or Braille
    assert {c.value["iso15924"] for c in scripts if c.scope.language == "ta"} == {"Taml"}
    assert all(c.attribute == f"writing_system_{c.value['iso15924'].lower()}" for c in scripts)
    keys = [(c.subject, c.attribute, c.scope.model_dump_json()) for c in claims]
    assert len(keys) == len(set(keys))
    linked = [c for c in claims if c.attribute == "linked_to_region"]
    assert linked and all(c.scope.region_code == "IN-TN" and c.sources[0].source_type == "wikidata" for c in linked)
    assert all(not c.value["label"].startswith("Q") or not c.value["label"][1:].isdigit() for c in linked)  # never a bare id


async def test_an_invalid_language_code_is_not_sent_to_the_api():
    seen: list[httpx.Request] = []
    async with scripted_client([httpx.Response(200, json={"search": []})] * 2, seen) as client:
        await WikidataSource(user_agent=UA, client=client).resolve_entity("Onam", language="en&action=wbremoveclaims", region_code=None)
    assert [r.url.params["language"] for r in seen] == ["en"]  # fell back to the default; nothing injected


@pytest.mark.parametrize("entity_id",["Q1 | DROP", "not-an-id", "region:IN-TN\" . } #", "region:ZZ", "Q0123"])
async def test_malformed_ids_never_reach_the_network(entity_id):
    async with scripted_client([]) as client:  # an empty script raises on any request
        assert await WikidataSource(user_agent=UA, client=client).related_signals(entity_id, region_code="IN-TN") == []
