"""Google Data Commons: state-wise statistics for the State facts panel, read from its v2 observation API.

GET https://api.datacommons.org/v2/observation with `variable.dcids`, `entity.dcids` (the 36 states and union territories plus
India) and `select=date,entity,value,variable,facet`; the key is sent as the `X-API-Key` header, never in the URL. Two requests
fetch everything: one with `date=LATEST` for the single-figure variables and one without a date for the variable that is drawn as
a series (population). The catalogue below was checked against the live API on 20 Nov 2026 (omnicult-docs/datacommons/NOTES.md):
the place ids, the variables, and how many states each one covers.

Data Commons keeps several facets per variable (one per publisher import) and ranks them itself. A figure takes the first ranked
facet, or the first whose `measurementMethod` or `provenanceUrl` holds the variable's `prefer` text (the population series is the
NITI Aayog projection, which is the only facet with a figure for every year on today's state boundaries). Each stored figure
keeps its date and its facet (id, import, method, publisher page) so it can be traced. A value outside the variable's plausible
range is dropped, never kept: the source holds at least one impossible figure (a negative vaccination share). A figure of a
survey or census is not assigned to a state whose territory has changed since (see `datagov._CENSUS_2011_CHANGED`); the NFHS-4
figures (dated 2015) are also withheld from Jammu and Kashmir, Ladakh and Dadra and Nagar Haveli and Daman and Diu, because the
source files later survey rounds for the new territories under the same 2015 date (Ladakh's stunting share is the NFHS-5 one).

The key comes from settings (DATA_COMMONS_API_KEY). Calls go through `HttpFetcher` (bounded retries, typed errors); neither the key
nor a URL is put into an error message.
"""

import re
from dataclasses import dataclass
from typing import Any

from pydantic import SecretStr

from app.integrations.culture.adapters.datagov import _CENSUS_2011_CHANGED, NATIONAL, Snapshot, parse_number
from app.integrations.culture.base import SourceNotConfigured, SourceValidationError
from app.integrations.culture.http import HttpFetcher
from app.reference.india import REGIONS

SOURCE = "data_commons"
API = "https://api.datacommons.org/v2/observation"
USER_AGENT = "OmnicultStateFacts/1.0"
RESOURCE_PREFIX = "datacommons:"  # the `resource_id` of every stored row; one resource per variable
CADENCE_DAYS = 7  # how long a stored copy is served before the read path pulls again
COUNTRY = "country/IND"

# Omnicult region code -> Data Commons place id. Each was resolved with /v2/node (`<-containedInPlace+{typeOf:AdministrativeArea1}`
# under country/IND) and checked against the place's own `isoCode` and name. Data Commons also lists lookalikes that are not used:
# wikidataId/Q9357528 (the NCT of Delhi, a parent of Q1353), Q120971341 (a Chandigarh parent of Q43433), Q46107 (Dadra and Nagar
# Haveli as a district) and Q66710 (Daman and Diu before the 2020 merger).
DCIDS: dict[str, str] = {
    "IN-AN": "wikidataId/Q40888", "IN-AP": "wikidataId/Q1159", "IN-AR": "wikidataId/Q1162", "IN-AS": "wikidataId/Q1164",
    "IN-BR": "wikidataId/Q1165", "IN-CH": "wikidataId/Q43433", "IN-CG": "wikidataId/Q1168", "IN-DH": "wikidataId/Q77997266",
    "IN-DL": "wikidataId/Q1353", "IN-GA": "wikidataId/Q1171", "IN-GJ": "wikidataId/Q1061", "IN-HR": "wikidataId/Q1174",
    "IN-HP": "wikidataId/Q1177", "IN-JK": "wikidataId/Q66278313", "IN-JH": "wikidataId/Q1184", "IN-KA": "wikidataId/Q1185",
    "IN-KL": "wikidataId/Q1186", "IN-LA": "wikidataId/Q200667", "IN-LD": "wikidataId/Q26927", "IN-MP": "wikidataId/Q1188",
    "IN-MH": "wikidataId/Q1191", "IN-MN": "wikidataId/Q1193", "IN-ML": "wikidataId/Q1195", "IN-MZ": "wikidataId/Q1502",
    "IN-NL": "wikidataId/Q1599", "IN-OD": "wikidataId/Q22048", "IN-PY": "wikidataId/Q66743", "IN-PB": "wikidataId/Q22424",
    "IN-RJ": "wikidataId/Q1437", "IN-SK": "wikidataId/Q1505", "IN-TN": "wikidataId/Q1445", "IN-TS": "wikidataId/Q677037",
    "IN-TR": "wikidataId/Q1363", "IN-UP": "wikidataId/Q1498", "IN-UT": "wikidataId/Q1499", "IN-WB": "wikidataId/Q1356",
}
REGION_BY_DCID = {dcid: code for code, dcid in DCIDS.items()} | {COUNTRY: NATIONAL}
assert {r.code for r in REGIONS} == set(DCIDS), "every Omnicult region needs exactly one Data Commons place"

_DATE = re.compile(r"^\d{4}(-\d{2})?$")
NITI_PROJECTION = ("measurementMethod", "NITIIndiaProjection")
CENSUS = ("provenanceUrl", "censusindia.gov.in")
SINCE_2015 = frozenset({"IN-JK", "IN-LA", "IN-DH"})  # territories that changed after the 2015-16 survey round


@dataclass(frozen=True)
class Variable:
    key: str  # stored metric name
    dcid: str  # the statistical variable (the numerator of a derived one)
    unit: str  # a State facts unit: percent | inr | million | whole | decimal
    low: float  # plausible range of the stored value: anything outside is dropped
    high: float
    scale: float = 1.0  # stored value = published value x scale (people -> millions)
    prefer: tuple[str, str] | None = None  # (facet field, text it must hold); None takes Data Commons's first-ranked facet
    series: bool = False  # keep every year of the chosen facet instead of the latest
    national: bool = False  # also read the all-India row, from the same kind of facet
    per: str = ""  # derived: dcid / per, both from the same facet and the same date
    exclude: frozenset[str] = frozenset()  # regions whose territory no longer matches the figure's: nothing is stored for them

    @property
    def resource_id(self) -> str:
        return f"{RESOURCE_PREFIX}{self.dcid}" + (f"/{self.per}" if self.per else "")

    @property
    def dcids(self) -> tuple[str, ...]:
        return (self.dcid, self.per) if self.per else (self.dcid,)


# States covered when the catalogue was checked, of 36: population 35 (no projection for Chandigarh), sex ratio 33, density 33,
# household size 31, wage 36, electricity 34, development score 35, fertility 33, anaemia 33, stunting 33.
VARIABLES: tuple[Variable, ...] = (
    Variable("population", "Count_Person", "million", 0, 400, scale=1e-6, prefer=NITI_PROJECTION, series=True),
    Variable("sex_ratio", "Count_Person_Female_AsAFractionOf_Count_Person_Male", "whole", 500, 1500, exclude=SINCE_2015),
    Variable("density", "Count_Person_PerArea", "whole", 0, 100_000, national=True),
    Variable("household_size", "Count_Person", "decimal", 1, 15, per="Count_Household", prefer=CENSUS, exclude=_CENSUS_2011_CHANGED),
    Variable("wage_monthly", "Mean_WagesMonthly_Worker", "inr", 1_000, 500_000, national=True),
    Variable("electricity_use", "Annual_Amount_Electricity_AsAFractionOf_Count_Person", "whole", 0, 20_000, national=True),
    Variable("sdg_score", "IndexScore_SustainableDevelopmentGoal", "whole", 0, 100, national=True),
    Variable("fertility", "FertilityRate_Person_Female_AsAFractionOf_Count_Person_Female", "decimal", 0, 8, exclude=SINCE_2015),
    Variable("anaemia_women", "Count_NonPregnantWoman_15To49Years_ConditionAnaemia_AsAFractionOf_Count_NonPregnantWoman_15To49Years",
             "percent", 0, 100, exclude=SINCE_2015),
    Variable("stunting", "Count_Person_YearsUpto5_ConditionStunted_AsAFractionOf_Count_Person_Upto5Years", "percent", 0, 100, exclude=SINCE_2015),
)
LATEST_VARIABLES = tuple(v for v in VARIABLES if not v.series)
SERIES_VARIABLES = tuple(v for v in VARIABLES if v.series)
BY_RESOURCE = {v.resource_id: v for v in VARIABLES}


@dataclass(frozen=True)
class DcPull:
    rows: list[Snapshot]
    raw: dict[str, Any]  # {"latest": response, "series": response} exactly as the API sent them: what the recording stores
    empty: list[str]  # variables that produced no figure at all (a facet or a variable that moved)


# --- parsing ------------------------------------------------------------------------------------------------------------


def _by_variable(payload: Any, operation: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("byVariable"), dict):
        raise SourceValidationError(SOURCE, operation, "the response is not a Data Commons observation listing")
    facets = payload.get("facets")
    return payload["byVariable"], facets if isinstance(facets, dict) else {}


def _pick(by_variable: dict[str, Any], facets: dict[str, Any], dcid: str, entity: str, prefer: tuple[str, str] | None
          ) -> tuple[str, dict[str, Any], list[dict[str, Any]]] | None:
    """The facet this figure comes from and its observations: the first ranked facet, or the first one matching `prefer`."""
    ordered = (((by_variable.get(dcid) or {}).get("byEntity") or {}).get(entity) or {}).get("orderedFacets") or []
    for facet in ordered:
        if not isinstance(facet, dict):
            continue
        meta = facets.get(str(facet.get("facetId"))) or {}
        if prefer is None or prefer[1] in str(meta.get(prefer[0]) or ""):
            observations = [o for o in facet.get("observations") or [] if isinstance(o, dict) and _DATE.match(str(o.get("date")))]
            return (str(facet.get("facetId")), meta, observations) if observations else None
    return None


def _provenance(variable: Variable, facet_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    keys = {"import": "provenanceId", "method": "measurementMethod", "url": "provenanceUrl", "period": "observationPeriod", "unit": "unit"}
    return {"variable": "/".join(variable.dcids), "facet": facet_id, **{k: meta[src] for k, src in keys.items() if meta.get(src)}}


def _variable_rows(variable: Variable, by_variable: dict[str, Any], facets: dict[str, Any]) -> list[Snapshot]:
    rows: list[Snapshot] = []
    for entity, code in REGION_BY_DCID.items():
        if code == NATIONAL and not variable.national:
            continue
        if code in variable.exclude:
            continue
        top = _pick(by_variable, facets, variable.dcid, entity, variable.prefer)
        if top is None:
            continue
        facet_id, meta, observations = top
        if variable.per:  # a ratio: only the dates both variables hold, from the same kind of facet
            bottom = _pick(by_variable, facets, variable.per, entity, variable.prefer)
            below = {o["date"]: parse_number(o.get("value")) for o in bottom[2]} if bottom else {}
            observations = [{"date": o["date"], "value": _ratio(parse_number(o.get("value")), below.get(o["date"]))} for o in observations]
        elif not variable.series:
            observations = [max(observations, key=lambda o: str(o["date"]))]
        for obs in observations:
            value = parse_number(obs.get("value"))
            value = value * variable.scale if value is not None else None
            if value is not None and variable.low <= value <= variable.high:
                rows.append(Snapshot(variable.resource_id, code, variable.key, str(obs["date"]), value, variable.unit,
                                     _provenance(variable, facet_id, meta)))
    return rows


def _ratio(top: float | None, bottom: float | None) -> float | None:
    return top / bottom if top is not None and bottom else None


def parse_responses(latest: Any, series: Any) -> tuple[list[Snapshot], list[str]]:
    """Figures from the two API responses, and the variables that produced none. Used by the live client and the recording."""
    rows: list[Snapshot] = []
    empty: list[str] = []
    for group, payload, operation in ((LATEST_VARIABLES, latest, "latest"), (SERIES_VARIABLES, series, "series")):
        by_variable, facets = _by_variable(payload, operation)
        for variable in group:
            found = _variable_rows(variable, by_variable, facets)
            rows.extend(found)
            if not found:
                empty.append(variable.key)
    return rows, empty


# --- the client ---------------------------------------------------------------------------------------------------------


class DataCommonsClient:
    def __init__(self, api_key: SecretStr | None, *, http: HttpFetcher | None = None, timeout: float = 20.0) -> None:
        self._key = api_key.get_secret_value().strip() if api_key else ""
        self.http = http or HttpFetcher(SOURCE, user_agent=USER_AGENT, timeout=timeout)

    async def _get(self, variables: tuple[Variable, ...], *, latest: bool, operation: str) -> dict[str, Any]:
        if not self._key:
            raise SourceNotConfigured(SOURCE, operation, "DATA_COMMONS_API_KEY is not set")
        params: dict[str, Any] = {
            "variable.dcids": list(dict.fromkeys(d for v in variables for d in v.dcids)),
            "entity.dcids": [*DCIDS.values(), COUNTRY],
            "select": ["date", "entity", "value", "variable", "facet"],
        }
        if latest:
            params["date"] = "LATEST"
        data = await self.http.get_json(API, params, operation=operation, headers={"X-API-Key": self._key})
        _by_variable(data, operation)
        return data

    async def fetch(self) -> dict[str, Any]:
        """Both responses exactly as the API sent them."""
        return {"latest": await self._get(LATEST_VARIABLES, latest=True, operation="latest"),
                "series": await self._get(SERIES_VARIABLES, latest=False, operation="series")}

    async def pull(self) -> DcPull:
        raw = await self.fetch()
        rows, empty = parse_responses(raw["latest"], raw["series"])
        if not rows:
            raise SourceValidationError(SOURCE, "records", "no figure could be read (variables or places changed?)")
        return DcPull(rows, raw, empty)
