"""Public-holiday dates from the python-holidays package, enriched from the curated festival list.

The package encodes government-notified calendars as code; its India class supports state subdivisions, including
all four demo states (MH, TN, KL, WB). It lists observances that are public holidays: a festival with no holiday
(for example Thaipusam or Dahi Handi) will not appear here. Dates for movable festivals depend on the package
release in use; the claim's source identifier records the package version. This adapter makes no network calls.
"""

import re
from datetime import date, datetime, timedelta
from importlib import metadata
from typing import Any

from app.integrations.culture.adapters.curated import load_curated, name_variants
from app.integrations.culture.base import SourceBase, SourceDescriptor, now_utc
from app.integrations.culture.regions import region_for, subdivision
from app.schemas.claims import ClaimDraft, ClaimScope, SourceRef

PYPI_URL = "https://pypi.org/project/holidays/"


def supported_subdivisions() -> list[str]:
    """ISO-style subdivision codes the installed package supports for India (recorded in docs/audit/CULTURE_SOURCES.md)."""
    import holidays

    return sorted(holidays.India.subdivisions)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")


class HolidaysCalendarSource(SourceBase):
    name = "holidays_calendar"
    descriptor = SourceDescriptor(
        name="holidays_calendar", source_type="calendar", supported_operations=frozenset({"moments"}),
        scope="India public holidays by state subdivision, any year the package supports.",
        coverage_limitations=[
            "Only observances declared public holidays; many festivals are not.",
            "Dates follow the package release, which tracks notifications with some delay; verify before a launch.",
            "State coverage is per subdivision; a state with a missing or partial list returns fewer moments.",
        ],
        cache_policy={"moments": timedelta(days=7)},
    )

    async def moments(self, region_code: str, *, year: int) -> list[ClaimDraft]:
        region = region_for(region_code)
        if region is None or not 1950 <= year <= 2100:  # outside the years the package documents: no guess
            return []
        import holidays

        sub = subdivision(region.code)
        if sub not in holidays.India.subdivisions:
            return []
        calendar = holidays.India(subdiv=sub, years=year)
        version = metadata.version("holidays")
        curated = load_curated(region.code)
        festivals = {v: e for e in (curated.entries if curated else []) if e.attribute == "major_festival"
                     for v in name_variants(str(e.value.get("name", "")) if isinstance(e.value, dict) else "")}
        retrieved = now_utc()
        out: list[ClaimDraft] = []
        for day, joined in sorted(calendar.items()):
            for holiday_name in joined.split("; "):
                out.append(self._claim(region.code, region.name, sub, year, version, day, holiday_name, festivals, retrieved))
        return out

    def _claim(self, code: str, state: str, sub: str, year: int, version: str, day: date, name: str,
               festivals: dict[str, Any], retrieved: datetime) -> ClaimDraft:
        match = next((festivals[v] for v in name_variants(name) if v in festivals), None)
        value: dict[str, Any] = {"date": day.isoformat(), "name": name, "subdivision": sub, "year": year}
        if match is not None:
            value["curated_festival"] = match.subject  # enrichment: the cited festival entry this holiday corresponds to
        source = SourceRef(
            source_type="holidays_package", source_identifier=f"holidays=={version}:{code}:{year}", url=PYPI_URL,
            title=f"python-holidays {version}: India, subdivision {sub}, {year}", publisher="python-holidays contributors",
            retrieved_at=retrieved, excerpt=f"{day.isoformat()} {name}", independence_group="python-holidays")
        return ClaimDraft(
            subject=f"moment:{_slug(name)}", attribute="public_holiday_date", category="moment", value=value,
            value_text=f"python-holidays {version} lists {name} as a public holiday in {state} on {day.isoformat()}.",
            scope=ClaimScope(region_code=code, period=str(year)), kind="observed", sources=[source], retrieved_at=retrieved)
