"""Google Data Commons adapter: the place catalogue, facet choice, range and territory rules, the recorded snapshot and the client's
requests and typed failures. respx stands in for the API: no test touches the network."""

import json
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.integrations.culture.adapters import datacommons as dc
from app.integrations.culture.adapters.datagov import NATIONAL
from app.integrations.culture.base import SourceAuthError, SourceNetworkError, SourceNotConfigured, SourceRateLimited, SourceValidationError
from app.integrations.culture.http import HttpFetcher
from app.reference.india import REGIONS
from app.services.state_facts import recorded_datacommons

KEY = "dc-unit-test-key-0000"
TN, KL, AP, LA = dc.DCIDS["IN-TN"], dc.DCIDS["IN-KL"], dc.DCIDS["IN-AP"], dc.DCIDS["IN-LA"]


def snapshot() -> tuple[list[Any], list[str]]:
    recorded = recorded_datacommons()
    return dc.parse_responses(recorded["latest"], recorded["series"])


# --- catalogue ----------------------------------------------------------------------------------------------------------


def test_every_region_has_exactly_one_distinct_place_and_every_variable_a_distinct_resource() -> None:
    assert set(dc.DCIDS) == {r.code for r in REGIONS} and len(set(dc.DCIDS.values())) == 36
    assert all(dcid.startswith("wikidataId/Q") for dcid in dc.DCIDS.values())
    assert dc.REGION_BY_DCID[dc.COUNTRY] == NATIONAL
    assert len({v.resource_id for v in dc.VARIABLES}) == len(dc.VARIABLES) == len(dc.BY_RESOURCE)
    assert all(v.resource_id.startswith(dc.RESOURCE_PREFIX) and v.low < v.high for v in dc.VARIABLES)
    assert {v.series for v in dc.VARIABLES} == {True, False} and [v.key for v in dc.SERIES_VARIABLES] == ["population"]


# --- the recorded snapshot ----------------------------------------------------------------------------------------------


def test_the_recorded_snapshot_covers_the_states_it_was_measured_to_cover() -> None:
    rows, empty = snapshot()
    assert empty == []
    states = {v.key: {r.region_code for r in rows if r.metric == v.key} - {NATIONAL} for v in dc.VARIABLES}
    assert {key: len(codes) for key, codes in states.items()} == {
        "population": 35, "sex_ratio": 33, "density": 33, "household_size": 31, "wage_monthly": 36, "electricity_use": 34,
        "sdg_score": 35, "fertility": 33, "anaemia_women": 33, "stunting": 33}
    assert "IN-CH" not in states["population"] and "IN-DH" not in states["sdg_score"]  # the source has no figure for them
    assert {r.unit for r in rows} == {"million", "whole", "decimal", "inr", "percent"}
    assert len({(r.resource_id, r.region_code, r.metric, r.period) for r in rows}) == len(rows)  # one figure per key


def test_recorded_figures_are_the_published_ones_with_their_date_and_facet() -> None:
    rows, _ = snapshot()
    by = {(r.region_code, r.metric, r.period): r for r in rows}
    assert by["IN-TN", "sex_ratio", "2015"].value == 1033 and by["IN-KL", "sex_ratio", "2015"].value == 1049
    assert by["IN-TN", "stunting", "2015"].value == 27.1 and by["IN-TN", "fertility", "2015"].value == 1.7
    assert by["IN-TN", "wage_monthly", "2024-02"].value == 20707.75 and by["IN", "wage_monthly", "2024-02"].value == 21036.19
    assert by["IN-TN", "density", "2022"].value == 546.69 and by["IN", "density", "2022"].value == 427.2
    assert by["IN-TN", "population", "2026"].value == pytest.approx(77.609) and by["IN-TN", "population", "2011"].value == pytest.approx(72.437)
    assert by["IN-TN", "household_size", "2011"].value == pytest.approx(3.895, abs=1e-3)  # people / households, both Census 2011
    assert by["IN-TN", "sex_ratio", "2015"].provenance == {
        "variable": "Count_Person_Female_AsAFractionOf_Count_Person_Male", "facet": "14190567794592034968", "import": "dc/base/India_NFHS",
        "url": "https://ndap.niti.gov.in/dataset/6821, https://ndap.niti.gov.in/dataset/7034, https://ndap.niti.gov.in/dataset/6822",
        "unit": "Per1000Males"}
    assert all(r.provenance and r.provenance["facet"] and r.provenance["variable"] for r in rows)


def test_population_is_one_projection_series_per_state_and_never_a_census_figure_for_a_state_that_changed() -> None:
    rows, _ = snapshot()
    series = sorted((r.period, r.value) for r in rows if r.metric == "population" and r.region_code == "IN-TN")
    assert [p for p, _ in series] == [str(y) for y in range(2011, 2027)]
    assert {r.provenance["method"] for r in rows if r.metric == "population"} == {"NITIIndiaProjection"}
    assert {r.period for r in rows if r.metric == "population" and r.region_code == "IN-LA"} >= {"2011", "2026"}  # Ladakh has its own
    # Census 2011 ratios and NFHS-4 figures are withheld from territories that changed since
    for key, withheld in (("household_size", {"IN-AP", "IN-TS", "IN-JK", "IN-LA", "IN-DH"}), ("stunting", {"IN-JK", "IN-LA", "IN-DH"}),
                          ("sex_ratio", {"IN-JK", "IN-LA", "IN-DH"})):
        assert not {r.region_code for r in rows if r.metric == key} & withheld, key


def test_only_the_variables_with_an_all_india_figure_have_one_and_it_is_from_the_same_kind_of_facet() -> None:
    rows, _ = snapshot()
    assert {r.metric for r in rows if r.region_code == NATIONAL} == {v.key for v in dc.VARIABLES if v.national}
    for national in (r for r in rows if r.region_code == NATIONAL):
        facets = {r.provenance["facet"] for r in rows if r.metric == national.metric and r.period == national.period}
        assert national.provenance["facet"] in facets and len(facets) == 1


# --- facet choice, ranges, dates ----------------------------------------------------------------------------------------


def listing(variable: str, entity: str, facets: list[tuple[str, list[tuple[str, Any]]]]) -> dict[str, Any]:
    ordered = [{"facetId": fid, "observations": [{"date": d, "value": v} for d, v in obs]} for fid, obs in facets]
    return {"byVariable": {variable: {"byEntity": {entity: {"orderedFacets": ordered}}}}}


def only(variable: dc.Variable, payload: dict[str, Any], facets: dict[str, Any] | None = None) -> list[Any]:
    return dc._variable_rows(variable, payload["byVariable"], facets or {})


def test_a_variable_takes_the_first_ranked_facet_unless_it_prefers_another() -> None:
    wage = next(v for v in dc.VARIABLES if v.key == "wage_monthly")
    payload = listing(wage.dcid, TN, [("a", [("2024-02", 20000.0)]), ("b", [("2021-04", 16000.0)])])
    assert [(r.period, r.value, r.provenance["facet"]) for r in only(wage, payload)] == [("2024-02", 20000.0, "a")]
    population = next(v for v in dc.VARIABLES if v.key == "population")
    census = listing(population.dcid, TN, [("c", [("2011", 72_147_030)]), ("n", [("2011", 72_437_000), ("2026", 77_609_000)])])
    meta = {"c": {"provenanceUrl": "https://censusindia.gov.in/"}, "n": {"measurementMethod": "NITIIndiaProjection"}}
    assert [(r.period, r.provenance["facet"]) for r in only(population, census, meta)] == [("2011", "n"), ("2026", "n")]
    assert only(population, listing(population.dcid, TN, [("c", [("2011", 72_147_030)])]), meta) == []  # no projection, no figure


@pytest.mark.parametrize("value", [-93.2, 100.5, "n/a", None, True, float("nan")])
def test_a_value_outside_the_plausible_range_or_not_a_number_is_dropped_never_kept(value: Any) -> None:
    stunting = next(v for v in dc.VARIABLES if v.key == "stunting")
    assert only(stunting, listing(stunting.dcid, TN, [("a", [("2015", value)])])) == []
    assert [r.value for r in only(stunting, listing(stunting.dcid, TN, [("a", [("2015", 27.1)])]))] == [27.1]


def test_the_latest_observation_wins_and_a_malformed_date_is_ignored() -> None:
    sdg = next(v for v in dc.VARIABLES if v.key == "sdg_score")
    payload = listing(sdg.dcid, KL, [("a", [("2021", 75.0), ("2023", 79.0)])])
    assert [(r.period, r.value) for r in only(sdg, payload)] == [("2023", 79.0)]
    assert only(sdg, listing(sdg.dcid, KL, [("a", [("last year", 79.0), ("2023-5-1", 70.0)])])) == []


def test_a_ratio_needs_both_figures_from_the_same_date_and_a_non_zero_denominator() -> None:
    size = next(v for v in dc.VARIABLES if v.key == "household_size")
    census = {"c": {"provenanceUrl": "https://censusindia.gov.in/"}}

    def both(people: Any, homes: Any, homes_date: str = "2011") -> dict[str, Any]:
        merged = listing(size.dcid, KL, [("c", [("2011", people)])])
        merged["byVariable"].update(listing(size.per, KL, [("c", [(homes_date, homes)])])["byVariable"])
        return merged

    assert [r.value for r in only(size, both(3_346_000, 800_000), census)] == [pytest.approx(4.1825)]
    assert only(size, both(3_346_000, 800_000, "2001"), census) == [] and only(size, both(3_346_000, 0), census) == []
    assert only(size, both(3_346_000, None), census) == [] and only(size, both(30, 1_000), census) == []  # 0.03 people per home


def test_a_state_whose_territory_changed_gets_no_census_ratio_even_when_the_source_has_one() -> None:
    size = next(v for v in dc.VARIABLES if v.key == "household_size")
    payload = listing(size.dcid, AP, [("c", [("2011", 84_580_777)])])
    payload["byVariable"].update(listing(size.per, AP, [("c", [("2011", 21_000_000)])])["byVariable"])
    assert only(size, payload, {"c": {"provenanceUrl": "https://censusindia.gov.in/"}}) == []


def test_variables_that_return_nothing_are_reported_and_a_bad_payload_is_a_validation_error() -> None:
    rows, empty = dc.parse_responses({"byVariable": {}}, {"byVariable": {}})
    assert rows == [] and sorted(empty) == sorted(v.key for v in dc.VARIABLES)
    for bad in (None, [], {}, {"byVariable": []}):
        with pytest.raises(SourceValidationError):
            dc.parse_responses(bad, {"byVariable": {}})


# --- the client ---------------------------------------------------------------------------------------------------------


def client(key: str | None = KEY) -> dc.DataCommonsClient:
    async def nap(_: float) -> None:
        return None

    return dc.DataCommonsClient(SecretStr(key) if key else None, http=HttpFetcher("data_commons", user_agent="t", max_retries=1, backoff_seconds=0, sleep=nap))


def serve(mock: respx.MockRouter, seen: list[httpx.Request] | None = None) -> None:
    recorded = recorded_datacommons()

    def answer(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=recorded["latest"] if request.url.params.get("date") == "LATEST" else recorded["series"])

    mock.get(dc.API).mock(side_effect=answer)


async def test_a_pull_makes_two_requests_with_the_key_in_a_header_and_never_in_the_url() -> None:
    seen: list[httpx.Request] = []
    with respx.mock(assert_all_called=False) as mock:
        serve(mock, seen)
        pull = await client().pull()
    assert len(seen) == 2 and [r.url.params.get("date") for r in seen] == ["LATEST", None]
    assert all(r.headers["X-API-Key"] == KEY and KEY not in str(r.url) for r in seen)
    latest, series = seen
    assert sorted(latest.url.params.get_list("entity.dcids")) == sorted([*dc.DCIDS.values(), dc.COUNTRY])
    assert series.url.params.get_list("variable.dcids") == ["Count_Person"]
    assert {"Count_Household", "Count_Person_PerArea"} <= set(latest.url.params.get_list("variable.dcids"))
    assert set(latest.url.params.get_list("select")) == {"date", "entity", "value", "variable", "facet"}
    assert (pull.rows, pull.empty) == snapshot() and set(pull.raw) == {"latest", "series"}


async def test_the_pull_keeps_the_responses_exactly_as_the_api_sent_them() -> None:
    with respx.mock(assert_all_called=False) as mock:
        serve(mock)
        pull = await client().pull()
    assert pull.raw["latest"] == recorded_datacommons()["latest"] and pull.raw["series"] == recorded_datacommons()["series"]


async def test_without_a_key_nothing_is_requested() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(dc.API)
        with pytest.raises(SourceNotConfigured):
            await client(None).pull()
        with pytest.raises(SourceNotConfigured):
            await client("   ").pull()
    assert route.call_count == 0


@pytest.mark.parametrize(("status", "error"), [(401, SourceAuthError), (403, SourceAuthError), (429, SourceRateLimited)])
async def test_http_failures_are_typed_and_the_key_never_appears_in_them(status: int, error: type[Exception]) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(dc.API).mock(return_value=httpx.Response(status, json={"message": f"bad key {KEY}"}))
        with pytest.raises(error) as caught:
            await client().pull()
    assert KEY not in str(caught.value)


async def test_a_server_error_is_retried_a_bounded_number_of_times_then_raised() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(dc.API).mock(return_value=httpx.Response(503))
        with pytest.raises(Exception) as caught:
            await client().pull()
    assert route.call_count == 2 and getattr(caught.value, "kind", "") == "http" and KEY not in str(caught.value)


async def test_a_dropped_connection_is_a_network_error() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(dc.API).mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(SourceNetworkError):
            await client().pull()


@pytest.mark.parametrize("body", [{"status": "error"}, [], "text", {"byVariable": 3}])
async def test_a_response_that_is_not_an_observation_listing_is_a_validation_error(body: Any) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(dc.API).mock(return_value=httpx.Response(200, json=body))
        with pytest.raises(SourceValidationError):
            await client().pull()


async def test_a_listing_from_which_no_figure_can_be_read_is_a_validation_error() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(dc.API).mock(return_value=httpx.Response(200, json={"byVariable": {}, "facets": {}}))
        with pytest.raises(SourceValidationError, match="no figure could be read"):
            await client().pull()


def test_the_recording_is_the_api_listing_pruned_to_the_facets_in_use_and_holds_no_secret() -> None:
    recorded = recorded_datacommons()
    assert recorded["regions"] == "all" and set(recorded) >= {"recorded_on", "latest", "series"}
    for part in ("latest", "series"):
        facets_used = {f["facetId"] for v in recorded[part]["byVariable"].values() for e in v["byEntity"].values() for f in e["orderedFacets"]}
        assert facets_used == set(recorded[part]["facets"])
        assert {len(e["orderedFacets"]) for v in recorded[part]["byVariable"].values() for e in v["byEntity"].values()} == {1}
    assert "X-API-Key" not in json.dumps(recorded)
