"""Category Shelf discovery: relevance rule, placement by located-in chain, unknowns kept empty, failures reported. No network."""

from typing import Any

import httpx

from app.integrations.culture.shelf import WikidataShelfSource, match_pack, pack_by_key, packs, relevance
from tests.unit.culture.culture_helpers import UA, no_sleep, scripted_client

PACK = pack_by_key("festive_sweets_snacks")
assert PACK is not None


def item(qid: str, label: str, description: str | None, claims: dict[str, list[Any]] | None = None, sitelinks: list[str] | None = None) -> dict:
    return {
        "id": qid, "labels": {"en": {"language": "en", "value": label}},
        "descriptions": {"en": {"language": "en", "value": description}} if description else {},
        "claims": {p: [{"mainsnak": {"datavalue": {"value": v}}} for v in values] for p, values in (claims or {}).items()},
        "sitelinks": {s: {"site": s, "title": label} for s in (sitelinks or [])}}


def ref(qid: str) -> dict:
    return {"entity-type": "item", "id": qid}


ENTITIES = {
    "Q1": item("Q1", "Pune Sweets", "Indian chain of confectionery stores",
               {"P31": [ref("Q4830453")], "P159": [ref("Q10")], "P571": [{"time": "+1950-00-00T00:00:00Z"}], "P856": ["https://example.org"]},
               ["enwiki", "mrwiki", "hiwiki", "commonswiki"]),
    "Q2": item("Q2", "Sweet Dreams", "2019 Indian film", {"P31": [ref("Q11424")]}),
    "Q3": item("Q3", "rasgulla", "syrupy dessert of the Indian subcontinent", {"P279": [ref("Q182940")], "P131": [ref("Q1356")]}, ["enwiki", "bnwiki"]),
    "Q4": item("Q4", "Acme Pumps", "Indian pump manufacturer", {"P31": [ref("Q4830453")], "P159": [ref("Q10")]}),
    "Q5": item("Q5", "Jaipur Mithai", "Indian snack brand", {"P31": [ref("Q431289")]}),  # no place, no year, no site
    "Q6": item("Q6", "Mystery Sweets", None, {"P31": [ref("Q4830453")]}),
    "Q4830453": item("Q4830453", "business", None), "Q11424": item("Q11424", "film", None), "Q182940": item("Q182940", "dessert", None),
    "Q431289": item("Q431289", "brand", None),
    "Q10": item("Q10", "Pune", None, {"P131": [ref("Q20")]}), "Q20": item("Q20", "Pune district", None, {"P131": [ref("Q1191")]}),
    "Q1191": item("Q1191", "Maharashtra", None), "Q1356": item("Q1356", "West Bengal", None),
}


def handler(seen: list[httpx.Request]):
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        params = dict(request.url.params)
        if params.get("list") == "search":
            return httpx.Response(200, json={"query": {"search": [{"title": q} for q in ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "bad")]}})
        ids = params["ids"].split("|")
        return httpx.Response(200, json={"entities": {i: ENTITIES.get(i, {"id": i, "missing": ""}) for i in ids}})
    return answer


def source(seen: list[httpx.Request]) -> WikidataShelfSource:
    return WikidataShelfSource(user_agent=UA, client=httpx.AsyncClient(transport=httpx.MockTransport(handler(seen))), gap_seconds=0, sleep=no_sleep)


async def test_discovery_keeps_businesses_and_products_that_name_the_category_and_says_why_it_left_out_the_rest() -> None:
    seen: list[httpx.Request] = []
    found = await source(seen).discover(PACK)
    assert [e.entity_id for e in found.entities] == ["Q1", "Q3", "Q5"]  # ordered by Wikipedia editions (3, 2, 0), then name
    reasons = {x.entity_id: x.reason for x in found.excluded}
    assert "other than a business or a product" in reasons["Q2"]  # a film
    assert "do not name the category" in reasons["Q4"]  # a pump maker
    assert "no description" in reasons["Q6"]
    assert found.gaps == [] and all(c.status == "ok" for c in found.calls) and found.pack_key == PACK.key
    assert all(r.headers["User-Agent"] == UA for r in seen)
    assert "P17=Q668|P495=Q668" in str(next(r for r in seen if r.url.params.get("list") == "search").url.params["srsearch"])


async def test_a_state_link_comes_from_the_located_in_chain_and_says_how() -> None:
    found = {e.entity_id: e for e in (await source([]).discover(PACK)).entities}
    q1, q3 = found["Q1"], found["Q3"]
    assert q1.kind == "brand" and q1.region_codes == ["IN-MH"] and q1.founded_year == 1950 and q1.website == "https://example.org"
    assert q1.region_basis == "headquarters Pune, which Wikidata places in Maharashtra" and q1.wikipedia_languages == 3  # commons is not an edition
    assert set(q1.sitelinks) == {"en", "mr", "hi"}
    assert q3.kind == "product" and q3.region_codes == ["IN-WB"] and q3.classes == ["dessert"] and q3.region_basis == "recorded place West Bengal"


async def test_what_wikidata_does_not_hold_stays_empty_never_estimated() -> None:
    q5 = next(e for e in (await source([]).discover(PACK)).entities if e.entity_id == "Q5")
    assert q5.founded_year is None and q5.website is None and q5.places == [] and q5.region_codes == [] and q5.region_basis is None
    assert q5.wikipedia_languages == 0 and q5.sitelinks == {}
    assert not any(hasattr(q5, name) for name in ("price", "sales", "market_share", "revenue"))


async def test_a_failing_source_is_reported_as_a_gap_not_raised_or_invented() -> None:
    client = scripted_client([httpx.Response(500)] * 40)
    found = await WikidataShelfSource(user_agent=UA, client=client, gap_seconds=0, sleep=no_sleep, max_retries=0).discover(PACK)
    assert found.entities == [] and found.excluded == []
    assert found.gaps and all("failed (http)" in g for g in found.gaps)
    assert all(c.status == "error" and c.error_type == "http" for c in found.calls)


def test_the_relevance_rule_reads_class_then_description() -> None:
    assert relevance(PACK, "X", "Indian snack brand", ["brand"]) == ("brand", "A business or product whose description names the category.")
    assert relevance(PACK, "X", "Indian snack", ["dish"])[0] == "product"
    assert relevance(PACK, "X", "Indian snack", ["hotel"])[0] is None
    assert relevance(PACK, "X", None, ["business"])[0] is None


def test_a_category_text_picks_the_pack_that_names_it_and_nothing_is_guessed() -> None:
    assert match_pack("Festive sweets and snacks for gifting").key == "festive_sweets_snacks"  # type: ignore[union-attr]
    assert match_pack("Premium loose-leaf tea").key == "tea_coffee"  # type: ignore[union-attr]
    assert match_pack("Industrial valves") is None and match_pack(None) is None and match_pack("") is None
    assert len({p.key for p in packs()}) == len(packs()) >= 4
    assert match_pack("Instead of steel pipes") is None  # "tea" inside a word is not tea
