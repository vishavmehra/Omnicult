"""Offline adapters and their datasets: census, python-holidays, curated references. No network is involved."""

import re

import pytest

from app.integrations.culture.adapters.census import CensusSource, load_census
from app.integrations.culture.adapters.curated import CuratedReferenceSource, load_curated
from app.integrations.culture.adapters.holidays_calendar import HolidaysCalendarSource, supported_subdivisions
from app.integrations.culture.regions import REGIONS
from app.reference.india import DEMO_REGIONS

STATES = list(REGIONS)


# ---- census ----


async def test_census_language_claims_carry_the_2011_snapshot_and_its_source():
    claims = await CensusSource().audience_facts("IN-MH")
    speakers = next(c for c in claims if c.attribute == "mother_tongue_speakers" and c.scope.language == "mr")
    share = next(c for c in claims if c.attribute == "language_share" and c.scope.language == "mr")
    assert speakers.value == 77_461_172 and speakers.kind == "observed"
    assert share.value == 68.93 and share.kind == "calculated" and "2011" in share.value_text
    for claim in (speakers, share):
        assert claim.scope.period == "2011" and claim.scope.region_code == "IN-MH" and claim.category == "language"
        (source,) = claim.sources
        assert source.source_type == "census_2011" and source.independence_group == "census_2011"
        assert source.url == "https://censusindia.gov.in/nada/index.php/catalog/10212"
        assert "77461172" in source.excerpt and "C0116" in source.excerpt
        assert source.source_identifier == "PC11_C16-27:013000" and source.title.endswith("Table C-16: Population by mother tongue, Maharashtra - 2011")
        assert source.published_at.isoformat() == "2022-07-04"  # library entry date, so a 2011 snapshot is never "fresh"
        assert source.publisher.startswith("Office of the Registrar General")


@pytest.mark.parametrize(("region", "principal"), [("IN-MH", "Marathi"), ("IN-TN", "Tamil"), ("IN-KL", "Malayalam"), ("IN-WB", "Bengali")])
async def test_principal_language_per_demo_state(region, principal):
    claim = next(c for c in await CensusSource().audience_facts(region) if c.attribute == "principal_language")
    assert claim.value == principal and claim.kind == "calculated" and claim.scope.period == "2011"


def test_census_dataset_is_internally_consistent_and_covers_the_demo_languages():
    data = load_census()
    assert data["year"] == "2011" and data["table_id"] == "C-16"
    for region, state in data["states"].items():
        assert sum(lang["speakers"] for lang in state["languages"]) + state["other_speakers"] == state["population"]
        assert state["catalog_url"].startswith("https://censusindia.gov.in/nada/index.php/catalog/")
        isos = {lang["iso639_1"] for lang in state["languages"]}
        if region in DEMO_REGIONS:
            assert {"mr", "ta", "ml", "bn", "hi", "en"} <= isos, region  # the six demo languages are always listed there
        assert {"hi", "en"} <= isos, region
    assert len(data["states"]) == 31 and not {"IN-AP", "IN-TS", "IN-JK", "IN-LA", "IN-DH"} & set(data["states"])  # changed since 2011


@pytest.mark.parametrize("region", STATES)
async def test_census_claims_never_share_a_subject_attribute_and_scope(region):
    # Two languages without an ISO 639-1 code once shared one scope and looked like a conflict between two values.
    claims = await CensusSource().audience_facts(region)
    keys = [(c.subject, c.attribute, c.scope.model_dump_json()) for c in claims]
    assert len(keys) == len(set(keys))
    if region == "IN-WB":
        santali = next(c for c in claims if c.subject == "language:santali" and c.attribute == "language_share")
        assert santali.scope.language is None and santali.scope.region_code == "IN-WB" and santali.value == 2.66


async def test_census_unknown_region_returns_nothing():
    assert await CensusSource().audience_facts("IN-TS") == []  # Telangana did not exist in 2011
    gujarat = await CensusSource().audience_facts("IN-GJ")
    principal = next(c for c in gujarat if c.attribute == "principal_language")
    assert principal.value == "Gujarati" and "Gujarat" in principal.value_text and principal.scope.region_code == "IN-GJ"


# ---- holidays ----


def test_python_holidays_supports_the_four_demo_states():
    assert {"MH", "TN", "KL", "WB"} <= set(supported_subdivisions())


async def test_holiday_moments_have_provenance_and_curated_enrichment():
    claims = await HolidaysCalendarSource().moments("IN-TN", year=2026)
    pongal = next(c for c in claims if c.value["name"] == "Pongal")
    assert pongal.value["date"] == "2026-01-14" and pongal.value["curated_festival"] == "festival:pongal"
    assert pongal.kind == "observed" and pongal.category == "moment" and pongal.scope.period == "2026"
    (source,) = pongal.sources
    assert source.source_type == "holidays_package" and source.source_identifier.startswith("holidays==")
    assert source.source_identifier.endswith(":IN-TN:2026") and source.excerpt == "2026-01-14 Pongal"
    assert source.url == "https://pypi.org/project/holidays/" and source.independence_group == "python-holidays"


async def test_a_day_with_two_holidays_yields_two_claims():
    claims = await HolidaysCalendarSource().moments("IN-MH", year=2026)
    may_day = [c for c in claims if c.value["date"] == "2026-05-01"]
    assert {c.value["name"] for c in may_day} >= {"Maharashtra Day", "Buddha Purnima"}


@pytest.mark.parametrize("region", STATES)
async def test_every_demo_state_has_a_calendar_and_unknown_regions_none(region):
    claims = await HolidaysCalendarSource().moments(region, year=2026)
    assert any(c.value["name"] == "Republic Day" and c.value["date"] == "2026-01-26" for c in claims)
    assert await HolidaysCalendarSource().moments("IN-ZZ", year=2026) == []  # not a state: no guess
    other = await HolidaysCalendarSource().moments("IN-GJ", year=2026)  # a state without curated references: dates only, no festival link
    assert other and all("curated_festival" not in c.value for c in other)


# ---- curated ----


@pytest.mark.parametrize("region", STATES)
def test_curated_file_is_valid_cited_and_consistent(region):
    data = load_curated(region)
    assert data is not None and data.region_code == region
    ids = [e.id for e in data.entries]
    assert len(ids) == len(set(ids)) and all(i.startswith(f"in-{region[3:].lower()}-") for i in ids)
    for entry in data.entries:
        assert re.fullmatch(r"[a-z_]+:[A-Za-z0-9_-]+", entry.subject), entry.subject
        assert entry.sources, entry.id
        for source in entry.sources:
            assert source.url.startswith("https://") and 10 <= len(source.excerpt) <= 600, entry.id
            assert not re.search(r"\[\d+\]", source.excerpt), entry.id  # no citation markers inside quotes
            if source.source_type == "wikipedia":
                assert source.independence_group in {"wikimedia", "census_2011"}, entry.id
            else:
                assert source.independence_group.startswith("gov:"), entry.id
        if entry.kind == "observed":
            assert entry.value_text.strip()


@pytest.mark.parametrize("region", STATES)
def test_curated_coverage_per_demo_state(region):
    counts: dict[str, int] = {}
    for entry in load_curated(region).entries:
        counts[entry.category] = counts.get(entry.category, 0) + 1
    assert counts["festival"] >= 6 and counts["food"] >= 4 and counts["sensitivity"] >= 3 and counts["moment"] >= 3
    assert counts["language"] >= 1 and counts["colour"] >= 3 and counts["symbol"] >= 3


async def test_curated_operations_filter_by_subject_and_category():
    source = CuratedReferenceSource()
    onam = await source.related_signals("festival:onam", region_code="IN-KL")
    assert onam and all(c.subject == "festival:onam" for c in onam)
    moments = await source.moments("IN-KL", year=2026)
    assert moments and all(c.category == "moment" for c in moments)
    assert await source.related_signals("region:IN-GJ", region_code="IN-GJ") == []


async def test_two_group_claims_are_the_ones_where_every_source_supports_the_core_statement():
    claims = await CuratedReferenceSource().related_signals("region:IN-TN", region_code="IN-TN", limit=1000)
    two_group = [c for c in claims if len({s.independence_group for s in c.sources}) > 1]
    assert two_group  # genuine corroboration exists for Tamil Nadu
    official = next(c for c in claims if c.attribute == "official_language")
    assert official.value == "Tamil" and len({s.independence_group for s in official.sources}) == 2


async def test_the_dahi_handi_disagreement_is_kept_as_two_single_source_claims():
    claims = await CuratedReferenceSource().related_signals("festival:dahi_handi", region_code="IN-MH")
    pair = [c for c in claims if c.attribute == "festival_day_relative_to_janmashtami"]
    assert len(pair) == 2 and pair[0].scope == pair[1].scope and pair[0].subject == pair[1].subject
    assert {c.value for c in pair} == {"same day as Krishna Janmashtami", "day after Krishna Janmashtami"}
    assert all(len(c.sources) == 1 for c in pair)
    assert {c.sources[0].independence_group for c in pair} == {"gov:maharashtratourism.gov.in", "wikimedia"}


async def test_the_west_bengal_hindi_share_disagreement_has_the_same_scope_as_the_census_claim():
    census = next(c for c in await CensusSource().audience_facts("IN-WB") if c.attribute == "language_share" and c.scope.language == "hi")
    wiki = next(c for c in await CuratedReferenceSource().related_signals("region:IN-WB", region_code="IN-WB", limit=1000)
                if c.attribute == "language_share")
    assert (census.subject, census.attribute, census.scope) == (wiki.subject, wiki.attribute, wiki.scope)
    assert census.value == 6.96 and wiki.value == 5.0  # Wikipedia's 5.00% differs from table C-16 (6.96%)
    assert wiki.sources[0].independence_group == "census_2011"  # it cites the census, so it is not independent of it
