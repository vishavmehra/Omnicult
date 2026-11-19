"""RegionProfileBuilder: categorisation, merging of corroborating claims, visible disagreements and gaps, partial failure."""

from datetime import UTC, date, datetime

import pytest

from app.core.config import Settings
from app.integrations.culture import CultureService, RegionProfileBuilder, build_culture_service
from app.integrations.culture.base import CultureSourceError
from app.integrations.culture.profile import PROFILE_CATEGORIES, _fingerprint as _fp, merge_corroborating, wikipedia_titles
from app.schemas.claims import ClaimDraft, ClaimScope, SourceRef
from tests.unit.culture.test_culture_service import FakeSource

TODAY = date(2026, 11, 17)


def fixture_service() -> CultureService:
    return build_culture_service(Settings(_env_file=None, app_env="test"), mode="demo")


def claim(value, *, group="g", ident="u", subject="s", attribute="a", category="custom", region="IN-TN") -> ClaimDraft:
    stamp = datetime(2026, 11, 17, tzinfo=UTC)
    source = SourceRef(source_type="curated_reference", source_identifier=ident, retrieved_at=stamp, independence_group=group)
    return ClaimDraft(subject=subject, attribute=attribute, category=category, value=value, value_text="t",
                      scope=ClaimScope(region_code=region), kind="observed", sources=[source], retrieved_at=stamp)


def test_equal_values_merge_into_one_claim_with_both_sources_and_differing_values_stay_apart():
    merged = merge_corroborating([claim("Tamil", group="wikimedia", ident="a"), claim(" tamil ", group="gov", ident="b"),
                                  claim("Tamil", group="gov", ident="b"), claim("English", ident="c")])
    assert [c.value for c in merged] == ["Tamil", "English"]
    assert [(s.independence_group, s.source_identifier) for s in merged[0].sources] == [("wikimedia", "a"), ("gov", "b")]
    different_scope = claim("Tamil", region="IN-KL")
    assert len(merge_corroborating([claim("Tamil"), different_scope])) == 2


def test_wikipedia_titles_are_read_from_cited_pages():
    stamp = datetime(2026, 11, 17, tzinfo=UTC)

    def festival(url):
        source = SourceRef(source_type="wikipedia", source_identifier=url, url=url, retrieved_at=stamp, independence_group="wikimedia")
        return claim("x").model_copy(update={"sources": [source]})

    assert wikipedia_titles([festival("https://en.wikipedia.org/wiki/Pongal_(festival)"), festival("https://en.wikipedia.org/wiki/Onam"),
                             festival("https://en.wikipedia.org/wiki/Pongal_(festival)"), festival("https://hi.wikipedia.org/wiki/x")]
                            ) == ["Pongal (festival)", "Onam"]


async def test_profile_groups_claims_by_category_with_the_call_log():
    profile = await RegionProfileBuilder(fixture_service()).build("IN-TN", today=TODAY)
    assert profile.region_name == "Tamil Nadu" and profile.mode == "fixture"
    assert list(profile.claims_by_category) == list(PROFILE_CATEGORIES)
    for category, claims in profile.claims_by_category.items():
        assert all(c.category == category for c in claims)
    for category in ("language", "festival", "moment", "food", "colour", "symbol", "custom", "sensitivity", "trend"):
        assert profile.claims_by_category[category], category
    ops = [r.operation for r in profile.call_log]
    assert ops.count("moments") == 2 and ops.count("trend_series") == 3 and "audience_facts" in ops and "related_signals" in ops
    assert {r.source for r in profile.call_log} == {"fixture"} and all(r.status in ("ok", "empty") for r in profile.call_log)
    assert len(profile.all_claims()) == sum(len(v) for v in profile.claims_by_category.values())


async def test_a_weak_region_shows_its_gaps():
    profile = await RegionProfileBuilder(fixture_service()).build("IN-TN", today=TODAY)
    assert "No claims for category 'humour'." in profile.gaps  # no source in the dataset supports a humour entry for TN
    assert "No claims for category 'script'." in profile.gaps  # scripts come from Wikidata, absent in fixture mode


async def test_every_claim_has_provenance_unless_it_is_an_interpretation():
    profile = await RegionProfileBuilder(fixture_service()).build("IN-KL", today=TODAY)
    for c in profile.all_claims():
        assert c.sources or c.kind in ("interpretation", "unverified")
        for s in c.sources:
            assert s.retrieved_at.tzinfo is not None and s.independence_group
            assert s.source_identifier.startswith("fixture:")  # demo output is never mistaken for a live result


async def test_trend_claims_are_synthetic_in_fixture_mode():
    profile = await RegionProfileBuilder(fixture_service()).build("IN-TN", today=TODAY)
    trends = profile.claims_by_category["trend"]
    assert len(trends) == 3 and all(t.kind == "synthetic" and "not demand" in t.value_text for t in trends)
    assert all("DEMO FIXTURE" not in t.sources[0].title for t in trends)


async def test_genuine_disagreements_survive_as_separate_claims():
    wb = await RegionProfileBuilder(fixture_service()).build("IN-WB", today=TODAY)
    hindi = [c for c in wb.claims_by_category["language"] if c.attribute == "language_share" and c.scope.language == "hi"]
    assert sorted(c.value for c in hindi) == [5.0, 6.96]  # Wikipedia's figure and census table C-16: both kept
    mh = await RegionProfileBuilder(fixture_service()).build("IN-MH", today=TODAY)
    dahi = [c for c in mh.all_claims() if c.attribute == "festival_day_relative_to_janmashtami"]
    assert len(dahi) == 2 and dahi[0].value != dahi[1].value


async def test_the_only_disagreements_in_the_demo_profiles_are_the_two_genuine_ones():
    found = set()
    for region in ("IN-MH", "IN-TN", "IN-KL", "IN-WB"):
        profile = await RegionProfileBuilder(fixture_service()).build(region, today=TODAY)
        groups: dict[tuple, list[ClaimDraft]] = {}
        for c in profile.all_claims():
            groups.setdefault((c.subject, c.attribute, c.scope.model_dump_json()), []).append(c)
        found |= {(region, k[0], k[1]) for k, members in groups.items() if len({_fp(m.value) for m in members}) > 1}
    assert found == {("IN-MH", "festival:dahi_handi", "festival_day_relative_to_janmashtami"),
                     ("IN-WB", "region:IN-WB", "language_share")}


async def test_two_independent_groups_exist_for_key_festival_and_language_claims():
    for region, subject in (("IN-TN", "festival:pongal"), ("IN-KL", "festival:onam"), ("IN-MH", "festival:ganesh_chaturthi")):
        profile = await RegionProfileBuilder(fixture_service()).build(region, today=TODAY)
        core = [c for c in profile.claims_by_category["festival"] if c.subject == subject and c.attribute == "major_festival"]
        assert core and len({s.independence_group for s in core[0].sources}) >= 2, subject
    tn = await RegionProfileBuilder(fixture_service()).build("IN-TN", today=TODAY)
    official = next(c for c in tn.claims_by_category["language"] if c.attribute == "official_language")
    assert len({s.independence_group for s in official.sources}) == 2


async def test_fixture_profile_is_deterministic_except_the_generation_time():
    first = await RegionProfileBuilder(fixture_service()).build("IN-TN", today=TODAY)
    second = await RegionProfileBuilder(fixture_service()).build("IN-TN", today=TODAY)
    assert first.model_dump(exclude={"generated_at", "call_log"}) == second.model_dump(exclude={"generated_at", "call_log"})


async def test_a_failing_source_is_reported_as_a_gap_and_the_rest_still_arrive():
    bad, good = FakeSource("bad"), FakeSource("good")
    bad.error = CultureSourceError("bad", "audience_facts", "boom")
    good.claims = [claim("Tamil", category="language")]
    profile = await RegionProfileBuilder(CultureService([bad, good], mode="live")).build("IN-TN", today=TODAY, trend_terms=[])
    assert [c.value for c in profile.claims_by_category["language"]] == ["Tamil"]
    assert any(g.startswith("bad.audience_facts failed (error)") for g in profile.gaps)


async def test_an_unconfigured_source_is_listed():
    profile = await RegionProfileBuilder(CultureService([FakeSource("off", configured=False), FakeSource("on")])).build(
        "IN-TN", today=TODAY, trend_terms=[])
    assert profile.sources_skipped == ["off"] and "Source 'off' is not configured; its claims are missing." in profile.gaps


@pytest.mark.parametrize("region", ["IN-MH", "IN-TN", "IN-KL", "IN-WB"])
async def test_every_demo_state_builds_a_profile_with_claims_in_most_categories(region):
    profile = await RegionProfileBuilder(fixture_service()).build(region, today=TODAY)
    assert sum(1 for v in profile.claims_by_category.values() if v) >= 9
