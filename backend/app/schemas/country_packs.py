"""The Country Pack (Tier 2 feature 57): a versioned description of the reference data that already exists.

The pack points at the data (regions, languages, moments, ad codes, culture sources); it does not copy it. Use
`GET /regions?country_code=IN` for the regions and their languages.
"""

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel


class PackLanguage(ApiModel):
    code: str
    name: str
    native_name: str
    script: str
    direction: Literal["ltr", "rtl"]
    code_standard: Literal["iso639-1", "iso639-3"]
    region_count: int = Field(description="Regions that list it as a principal or additional language.")


class PackScript(ApiModel):
    code: str = Field(description="ISO 15924.")
    name: str
    language_codes: list[str]


class PackRegions(ApiModel):
    total: int
    states: int
    union_territories: int
    demo_codes: list[str] = Field(description="The four regions with curated references, Census 2011 shares and pageview series.")
    list_path: str = Field(description="API path that lists every region with its languages.")


class PackSeedStatus(ApiModel):
    loaded: bool = Field(description="True when the database holds every region, language and moment of this version.")
    regions_in_database: int
    regions_expected: int
    languages_in_database: int
    languages_expected: int
    moments_in_database: int
    moments_expected: int
    pack_record_loaded: bool
    pack_loaded_at: datetime | None


class PackCalendarSource(ApiModel):
    id: str
    name: str
    description: str
    coverage: str
    version: str | None = Field(description="Package or dataset version, where one exists.")
    as_of: str | None = Field(description="Date the data was retrieved or cut, where it is a snapshot.")
    entries: int | None
    limitations: list[str]


class PackAdCodes(ApiModel):
    dataset: str
    version: str
    publisher: str
    edition: str
    entries: int
    topics: list[str]
    retrieved_on: str
    source_url: str
    landing_page: str
    sha256: str
    limitations: list[str]


class PackDataSource(ApiModel):
    id: str
    name: str
    used_for: str
    url: str | None
    licence: str | None
    licence_status: Literal["checked", "not_checked"]
    licence_checked_on: str | None
    licence_note: str
    retrieved_on: str | None = Field(description="NULL for a source queried live or a code list.")


class PackDimension(ApiModel):
    name: str
    description: str | None
    values: list[str]


class PackLink(ApiModel):
    label: str
    path: str


class CountryPack(ApiModel):
    country_code: str
    name: str
    version: str
    citation: str = Field(description="The line a report uses to cite this reference data.")
    content_sha256: str = Field(description="Fingerprint of the regions, languages and moments this version stands for.")
    notes: str
    seed: PackSeedStatus
    regions: PackRegions
    languages: list[PackLanguage]
    scripts: list[PackScript]
    calendar_sources: list[PackCalendarSource]
    ad_codes: PackAdCodes
    data_sources: list[PackDataSource]
    sampling_dimensions: list[PackDimension]
    never_sampled: list[str]
    known_gaps: list[str]
    links: list[PackLink]
