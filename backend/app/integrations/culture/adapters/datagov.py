"""India's Open Government Data platform (data.gov.in): state-wise official statistics for the State facts panel.

Each dataset is a `resource`: GET https://api.data.gov.in/resource/<id>?api-key=..&format=json&limit=..&offset=..&filters[f]=v.
The catalogue below was checked against the live resources (ids, field ids, units, periods); see
omnicult-docs/datagov/NOTES.md. A field the source marks `*`, `NA` or leaves blank is skipped, never guessed. Rows are mapped to
Omnicult region codes by name (renamed states and union territories included); a name that cannot be mapped safely is dropped.

The key comes from settings (DATA_GOV_IN_API_KEY) and is sent only as the `api-key` query parameter; neither the key nor the
URL is ever put into an error message. Calls go through `HttpFetcher` (bounded retries, typed errors).
"""

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import SecretStr

from app.integrations.culture.base import SourceNotConfigured, SourceValidationError
from app.integrations.culture.http import HttpFetcher
from app.reference.india import REGIONS

SOURCE = "data_gov_in"
API = "https://api.data.gov.in/resource/"
USER_AGENT = "OmnicultStateFacts/1.0"
PAGE = 50  # records per request; every resource below has 40 rows or fewer
MAX_PAGES = 6
NATIONAL = "IN"  # the all-India row of a dataset, where it has one


@dataclass(frozen=True)
class Metric:
    key: str  # stored metric name; several columns of one resource may share it (one per period)
    field: str  # the API field id
    period: str  # sortable text: a year, a financial year or "2019-21"
    unit: str  # percent | per100 | inr


@dataclass(frozen=True)
class Resource:
    key: str
    resource_id: str
    title: str
    state_field: str
    metrics: tuple[Metric, ...]
    cadence_days: int  # how long a stored copy is served before the read path pulls again
    filters: dict[str, str] = field(default_factory=dict)
    census_2011: bool = False  # 2011 boundaries: states split or merged since are not mapped


def _m(key: str, field_id: str, period: str, unit: str) -> Metric:
    return Metric(key, field_id, period, unit)


RESOURCES: tuple[Resource, ...] = (
    Resource(
        "nfhs5", "7c568619-b9b4-40bb-b563-68c28c27a6c1", "All India and State/UT-wise Factsheets of NFHS-5, 2019-2021", "states_uts",
        (_m("electricity", "population_living_in_households_with_electricity____", "2019-21", "percent"),
         _m("women_mobile", "women__age_15_49_years__having_a_mobile_phone_that_they_themselves_use____", "2019-21", "percent"),
         _m("women_internet", "women__age_15_49___who_have_ever_used_the_internet____", "2019-21", "percent"),
         _m("men_internet", "men__age_15_49___who_have_ever_used_the_internet____", "2019-21", "percent")),
        cadence_days=30, filters={"area": "Total"}),
    Resource(
        "teledensity", "64da9332-95e7-4ba9-8919-0f47911f4c78", "State/UT-wise Total Tele Density as on 30-06-2024", "state_ut",
        (_m("teledensity", "total_teledensity__in___", "Jun 2024", "per100"),), cadence_days=7),
    Resource(
        "internet", "d441cbd3-2143-4c4d-927d-f168ad8a1eb7", "State/UT-wise Internet Penetration as on 31st March 2024", "state_ut",
        (_m("internet_per100", "teledensity_______total", "Mar 2024", "per100"),
         _m("internet_per100_rural", "teledensity_______rural", "Mar 2024", "per100"),
         _m("internet_per100_urban", "teledensity_______urban", "Mar 2024", "per100")), cadence_days=7),
    Resource(
        "nsdp", "c9bfd3c0-b9de-4a5b-8752-f72a4f2932ad", "State/UT-wise Per Capita NSDP at Current Prices, 2019-20 to 2022-23", "state_ut",
        tuple(_m("nsdp", f"_{y[:4]}_{y[5:]}", y, "inr") for y in ("2019-20", "2020-21", "2021-22", "2022-23")), cadence_days=7),
    Resource(
        "mpce", "29d2831a-0ded-45f8-8919-0d1849f1a375", "State/UT-wise Average MPCE, 2022-23 and 2023-24", "state_ut",
        (_m("mpce_rural", "_2022_23___average_mpce__in_rs_____rural", "2022-23", "inr"),
         _m("mpce_urban", "_2022_23___average_mpce__in_rs_____urban", "2022-23", "inr"),
         _m("mpce_rural", "_2023_24___average_mpce__in_rs_____rural", "2023-24", "inr"),
         _m("mpce_urban", "_2023_24___average_mpce__in_rs_____urban", "2023-24", "inr")), cadence_days=7),
    Resource(
        "literacy", "5b9c2422-d8e4-4f57-9585-2831aaf18a1a", "State/UTs-wise Literacy Rates, Census 2001 and 2011", "india_states_uts",
        (_m("literacy", "census_2001", "2001", "percent"), _m("literacy", "census_2011", "2011", "percent")),
        cadence_days=30, census_2011=True),
    Resource(
        "urban", "8cf7eeb8-cefa-4416-b84c-4f7c9c369424", "State/UT-wise Percentage of Urban Population, Census 2001 and 2011",
        "state_union_territory",
        (_m("urban_share", "__of_urban_population_to_total_population___2001", "2001", "percent"),
         _m("urban_share", "__of_urban_population_to_total_population___2011", "2011", "percent")),
        cadence_days=30, census_2011=True),
)
BY_KEY = {r.key: r for r in RESOURCES}

# --- state names -> region codes --------------------------------------------------------------------------------------

_ALIASES = {
    "all india": NATIONAL, "india": NATIONAL, "total": NATIONAL,  # the TRAI tables close with a "Total" row
    "maharastra": "IN-MH", "chattisgarh": "IN-CG", "uttrakhand": "IN-UT",  # spellings the sources use
    "a and n islands": "IN-AN", "andaman and nicobar": "IN-AN", "nct of delhi": "IN-DL",
    "delhi nct": "IN-DL", "orissa": "IN-OD", "uttaranchal": "IN-UT", "pondicherry": "IN-PY", "telengana": "IN-TS",
    "j and k": "IN-JK", "jammu and kashmir ut": "IN-JK", "dadra and nagar haveli and daman and diu": "IN-DH",
}
# States whose 2011 census figure describes a different territory than today's state (Telangana was carved out of Andhra
# Pradesh in 2014, Ladakh out of Jammu and Kashmir in 2019, and the two Dadra, Nagar Haveli and Daman and Diu territories merged
# in 2020), so a 2011 number is not assigned to the current state.
_CENSUS_2011_CHANGED = frozenset({"IN-AP", "IN-TS", "IN-JK", "IN-LA", "IN-DH"})


def _norm(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", name.casefold().replace("&", " and ")).strip()
    return re.sub(r"\band\b", "and", text)


_BY_NAME = {_norm(r.name): r.code for r in REGIONS} | _ALIASES


def region_code_for(name: Any, *, census_2011: bool = False) -> str | None:
    """`IN` for the all-India row, a region code for a state or union territory, None for anything that cannot be mapped."""
    if not isinstance(name, str) or "(old)" in name.casefold():
        return None  # "Andhra Pradesh(old)" is the undivided state: it is neither of today's two
    code = _BY_NAME.get(_norm(name))
    if code is None or (census_2011 and code in _CENSUS_2011_CHANGED):
        return None
    return code


# --- values -----------------------------------------------------------------------------------------------------------

_NUMBER = re.compile(r"\(?\s*(-?\d+(?:\.\d+)?)\s*\)?")


def parse_number(raw: Any) -> float | None:
    """A number from a source cell. NFHS prints `(45.3)` for a figure based on 25-49 cases (kept: it is the published
    figure) and `*` where the figure is suppressed; `NA`, blanks and anything else are not numbers."""
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int | float):
        return float(raw) if math.isfinite(raw) else None
    match = _NUMBER.fullmatch(str(raw).strip().replace(",", ""))
    return float(match.group(1)) if match else None


@dataclass(frozen=True)
class Snapshot:
    resource_id: str
    region_code: str
    metric: str
    period: str
    value: float
    unit: str


@dataclass(frozen=True)
class Pull:
    resource_id: str
    updated: datetime | None
    total: int
    rows: list[Snapshot]
    unmapped: list[str]  # state names the mapper dropped


def parse_updated(raw: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def parse_records(resource: Resource, records: list[dict[str, Any]]) -> tuple[list[Snapshot], list[str]]:
    rows: dict[tuple[str, str, str], Snapshot] = {}
    unmapped: list[str] = []
    for record in records:
        name = record.get(resource.state_field)
        code = region_code_for(name, census_2011=resource.census_2011)
        if code is None:
            if isinstance(name, str) and name not in unmapped:
                unmapped.append(name)
            continue
        for metric in resource.metrics:
            value = parse_number(record.get(metric.field))
            if value is not None:
                rows[(code, metric.key, metric.period)] = Snapshot(resource.resource_id, code, metric.key, metric.period, value, metric.unit)
    return list(rows.values()), unmapped


# --- the client -------------------------------------------------------------------------------------------------------


class DataGovClient:
    def __init__(self, api_key: SecretStr | None, *, http: HttpFetcher | None = None, timeout: float = 15.0) -> None:
        self._key = api_key.get_secret_value().strip() if api_key else ""
        self.http = http or HttpFetcher(SOURCE, user_agent=USER_AGENT, timeout=timeout)

    def _params(self, resource: Resource, limit: int, offset: int, *, fields: bool) -> dict[str, Any]:
        if not self._key:
            raise SourceNotConfigured(SOURCE, "resource", "DATA_GOV_IN_API_KEY is not set")
        params: dict[str, Any] = {"api-key": self._key, "format": "json", "limit": limit, "offset": offset}
        for name, value in resource.filters.items():
            params[f"filters[{name}]"] = value
        if fields:
            params["fields"] = ",".join([resource.state_field, *dict.fromkeys(m.field for m in resource.metrics)])
        return params

    async def _get(self, resource: Resource, limit: int, offset: int, *, fields: bool, operation: str) -> dict[str, Any]:
        data = await self.http.get_json(API + resource.resource_id, self._params(resource, limit, offset, fields=fields), operation=operation)
        if not isinstance(data, dict) or data.get("status") != "ok" or not isinstance(data.get("records"), list):
            raise SourceValidationError(SOURCE, operation, "the response is not a data.gov.in resource listing")
        return data

    async def probe(self, resource: Resource) -> tuple[datetime | None, int]:
        """The resource's `updated_date` and record count from a one-record request: cheap enough to ask every time."""
        data = await self._get(resource, 1, 0, fields=True, operation="probe")
        return parse_updated(data.get("updated_date")), int(data.get("total") or 0)

    async def records(self, resource: Resource) -> tuple[list[dict[str, Any]], datetime | None, int]:
        """Every record of the resource as the API sent it (only the state and metric fields), its `updated_date` and its total."""
        records: list[dict[str, Any]] = []
        updated, total = None, 0
        for page in range(MAX_PAGES):
            data = await self._get(resource, PAGE, page * PAGE, fields=True, operation="records")
            updated, total = parse_updated(data.get("updated_date")), int(data.get("total") or 0)
            records.extend(r for r in data["records"] if isinstance(r, dict))
            if not data["records"] or len(records) >= total:
                break
        return records, updated, total

    async def pull(self, resource: Resource) -> Pull:
        records, updated, total = await self.records(resource)
        rows, unmapped = parse_records(resource, records)
        if not rows:
            raise SourceValidationError(SOURCE, "records", f"{resource.key}: no row could be read (fields or names changed?)")
        return Pull(resource.resource_id, updated, total, rows, unmapped)
