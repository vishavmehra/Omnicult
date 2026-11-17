"""The demo regions the adapters know: ISO 3166-2:IN code, regional language, and the Census 2011 state code.

This is lookup data, not evidence: no claim is built from it. Wikipedia language editions follow the ISO 639-1 code.
"""

from dataclasses import dataclass

COUNTRY = "IN"


@dataclass(frozen=True)
class Region:
    code: str  # ISO 3166-2:IN
    name: str
    language: str  # principal regional language, ISO 639-1
    census_state_code: str  # Census of India 2011 state code, as in table C-16
    wikidata_id: str  # item whose P300 (ISO 3166-2 code) equals `code`; verified live by culture_live_smoke

    @property
    def wiki_editions(self) -> tuple[str, ...]:
        """Wikipedia language editions to read for this region: the regional language, then English."""
        return (self.language, "en")


REGIONS: dict[str, Region] = {
    "IN-MH": Region("IN-MH", "Maharashtra", "mr", "27", "Q1191"),
    "IN-TN": Region("IN-TN", "Tamil Nadu", "ta", "33", "Q1445"),
    "IN-KL": Region("IN-KL", "Kerala", "ml", "32", "Q1186"),
    "IN-WB": Region("IN-WB", "West Bengal", "bn", "19", "Q1356"),
}

LANGUAGE_NAMES = {"mr": "Marathi", "ta": "Tamil", "ml": "Malayalam", "bn": "Bengali", "hi": "Hindi", "en": "English"}


def region_for(code: str) -> Region | None:
    return REGIONS.get(code.upper())


def subdivision(code: str) -> str:
    """`IN-TN` -> `TN` (the python-holidays subdivision code)."""
    return code.split("-", 1)[1].upper()
