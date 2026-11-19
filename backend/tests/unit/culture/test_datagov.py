"""data.gov.in adapter: number parsing, state-name mapping and record parsing. No network."""

import json

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.integrations.culture.adapters.datagov import (
    BY_KEY,
    NATIONAL,
    RESOURCES,
    DataGovClient,
    parse_number,
    parse_records,
    parse_updated,
    region_code_for,
)
from app.integrations.culture.base import SourceAuthError, SourceNotConfigured, SourceRateLimited, SourceValidationError
from app.integrations.culture.http import HttpFetcher
from app.reference.india import REGIONS
from app.services.state_facts import recorded


@pytest.mark.parametrize(("raw", "expected"), [
    (46.9, 46.9), ("33.3", 33.3), ("(45.3)", 45.3), (" 1,234 ", 1234.0), (12, 12.0),
    ("*", None), ("NA", None), ("na", None), ("", None), (None, None), (True, None), (float("nan"), None), ("12abc", None),
])
def test_parse_number_keeps_published_figures_and_drops_everything_else(raw: object, expected: float | None) -> None:
    assert parse_number(raw) == expected


@pytest.mark.parametrize(("name", "code"), [
    ("Tamil Nadu", "IN-TN"), ("Maharastra", "IN-MH"), ("Chattisgarh", "IN-CG"), ("Uttrakhand", "IN-UT"), ("Orissa", "IN-OD"),
    ("Jammu & Kashmir", "IN-JK"), ("Andaman & Nicobar Islands", "IN-AN"), ("NCT of Delhi", "IN-DL"), ("Telangana", "IN-TS"),
    ("Dadra & Nagar Haveli and Daman & Diu", "IN-DH"), ("Pondicherry", "IN-PY"), ("India", NATIONAL), ("All India", NATIONAL),
    ("Total", NATIONAL), ("Andhra Pradesh(old)", None), ("Daman & Diu", None), ("Atlantis", None), (None, None), (7, None),
])
def test_state_names_map_to_region_codes_including_renamed_and_misspelt_ones(name: object, code: str | None) -> None:
    assert region_code_for(name) == code


def test_every_region_maps_from_its_own_name_and_a_2011_figure_is_never_given_to_a_state_that_changed_since() -> None:
    assert all(region_code_for(r.name) == r.code for r in REGIONS)
    for changed in ("Andhra Pradesh", "Telangana", "Jammu and Kashmir", "Ladakh", "Dadra and Nagar Haveli and Daman and Diu"):
        assert region_code_for(changed, census_2011=True) is None, changed
    assert region_code_for("Kerala", census_2011=True) == "IN-KL"


def test_the_catalogue_is_consistent() -> None:
    assert len({r.resource_id for r in RESOURCES}) == len(RESOURCES) == len(BY_KEY)
    for r in RESOURCES:
        assert len(r.resource_id) == 36 and r.metrics and r.cadence_days >= 1
        assert len({(m.key, m.period) for m in r.metrics}) == len(r.metrics), r.key  # one column per metric and period


def test_the_recorded_snapshot_parses_to_the_published_figures() -> None:
    by: dict[tuple[str, str, str], float] = {}
    for key, saved in recorded()["resources"].items():
        rows, unmapped = parse_records(BY_KEY[key], saved["records"])
        assert unmapped == [], (key, unmapped)
        by.update({(r.region_code, r.metric, r.period): r.value for r in rows})
    assert by[("IN-TN", "women_internet", "2019-21")] == 46.9 and by[(NATIONAL, "women_internet", "2019-21")] == 33.3
    assert by[("IN-MH", "women_internet", "2019-21")] > 0  # "Maharastra" in the NFHS table
    assert by[("IN-TN", "literacy", "2001")] == 73.45 and by[("IN-TN", "literacy", "2011")] == 80.09
    assert by[("IN-TN", "nsdp", "2022-23")] == 275583 and (NATIONAL, "nsdp", "2022-23") not in by  # NSDP has no all-India row
    assert by[("IN-TN", "mpce_urban", "2023-24")] == 8165 and by[(NATIONAL, "teledensity", "Jun 2024")] == 85.95
    assert ("IN-AP", "literacy", "2011") not in by  # undivided-state census rows are not mapped


def test_unreadable_cells_are_skipped_not_guessed() -> None:
    rows, unmapped = parse_records(BY_KEY["nsdp"], [{"state_ut": "Goa", "_2019_20": 100, "_2020_21": "NA", "_2021_22": "*", "_2022_23": None},
                                                    {"state_ut": "Nowhere", "_2019_20": 1}])
    assert [(r.region_code, r.period, r.value) for r in rows] == [("IN-GA", "2019-20", 100.0)] and unmapped == ["Nowhere"]


def test_updated_date_is_read_as_utc() -> None:
    parsed = parse_updated("2026-02-10T07:49:27Z")
    assert parsed is not None and parsed.isoformat() == "2026-02-10T07:49:27+00:00"
    assert parse_updated("garbage") is None and parse_updated(None) is None


# --- the client, against respx ------------------------------------------------------------------------------------------

KEY = "unit-test-key-0000"
URL = "https://api.data.gov.in/resource/"


def client(key: str | None = KEY) -> DataGovClient:
    async def nap(_: float) -> None:
        return None

    return DataGovClient(SecretStr(key) if key else None, http=HttpFetcher("data_gov_in", user_agent="t", max_retries=1, backoff_seconds=0, sleep=nap))


def listing(records: list[dict], total: int | None = None) -> dict:
    return {"status": "ok", "total": len(records) if total is None else total, "count": len(records), "updated_date": "2026-01-01T00:00:00Z", "records": records}


async def test_pull_sends_the_key_filters_and_fields_and_pages_until_the_total() -> None:
    nfhs = BY_KEY["nfhs5"]
    pages = [[{"states_uts": "Kerala", "population_living_in_households_with_electricity____": 99.9}],
             [{"states_uts": "Goa", "population_living_in_households_with_electricity____": "(98.0)"}]]
    seen: list[dict[str, str]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=listing(pages[len(seen) - 1], total=2))

    with respx.mock(assert_all_called=False) as mock:
        mock.get(URL + nfhs.resource_id).mock(side_effect=answer)
        pull = await client().pull(nfhs)
    assert [(r.region_code, r.value) for r in pull.rows] == [("IN-KL", 99.9), ("IN-GA", 98.0)] and pull.total == 2
    first = seen[0]
    assert first["api-key"] == KEY and first["filters[area]"] == "Total" and first["limit"] == "50" and first["offset"] == "0"
    assert first["fields"].split(",")[0] == "states_uts" and seen[1]["offset"] == "50"


async def test_typed_failures_and_the_key_never_appears_in_them() -> None:
    nfhs = BY_KEY["nfhs5"]
    with pytest.raises(SourceNotConfigured):
        await client(None).pull(nfhs)
    for status, error in ((401, SourceAuthError), (403, SourceAuthError), (429, SourceRateLimited)):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(URL + nfhs.resource_id).mock(return_value=httpx.Response(status, json={"message": "no"}))
            with pytest.raises(error) as caught:
                await client().pull(nfhs)
        assert KEY not in str(caught.value)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(URL + nfhs.resource_id).mock(return_value=httpx.Response(200, json={"status": "error"}))
        with pytest.raises(SourceValidationError):
            await client().pull(nfhs)
    with respx.mock(assert_all_called=False) as mock:
        mock.get(URL + nfhs.resource_id).mock(return_value=httpx.Response(200, json=listing([{"states_uts": "Nowhere"}])))
        with pytest.raises(SourceValidationError, match="no row could be read"):
            await client().pull(nfhs)


async def test_probe_asks_for_one_record() -> None:
    nsdp = BY_KEY["nsdp"]
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(URL + nsdp.resource_id).mock(return_value=httpx.Response(200, json=listing([{"state_ut": "Goa"}], total=33)))
        updated, total = await client().probe(nsdp)
    assert total == 33 and updated is not None and route.calls[0].request.url.params["limit"] == "1"
    assert json.dumps(dict(route.calls[0].request.url.params)).count(KEY) == 1  # sent once, as a parameter, nowhere else
