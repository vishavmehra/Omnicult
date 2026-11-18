"""The India Country Pack: a versioned description of the India reference data that already exists.

Nothing is copied here. Regions, languages and moments stay in `app.reference.india`; the ASCI ad-code index stays in
`ad_codes_asci.json`; the culture sources stay in `app.integrations.culture`. This module adds only what no other module
records: the licence and review state of each data source, the known gaps, and a fingerprint of the reference data so a
report can say which pack it used.

Licence statements were read on 2026-11-17 and are quoted from `docs/audit/CULTURE_SOURCES.md` (feat/culture). A source
without a verified statement says `not_checked`; no licence is assumed. Check a source's terms before reusing its data.

Bump `india.PACK_VERSION` whenever the reference data changes. `tests/api/test_country_pack.py` pins the fingerprint of
the current version and fails when the data changes without a bump.
"""

import hashlib
import json
from typing import Literal, NamedTuple

from app.reference import india

LICENCES_CHECKED_ON = "2026-11-17"

# ISO 15924 names of the scripts the pack uses. Descriptive only; the codes come from `india.LANGUAGES`.
SCRIPT_NAMES = {
    "Latn": "Latin", "Deva": "Devanagari", "Taml": "Tamil", "Mlym": "Malayalam", "Beng": "Bengali", "Telu": "Telugu",
    "Knda": "Kannada", "Gujr": "Gujarati", "Guru": "Gurmukhi", "Orya": "Odia", "Arab": "Arabic (Perso-Arabic)",
    "Tibt": "Tibetan", "Mtei": "Meitei Mayek", "Olck": "Ol Chiki",
}


class SourceNote(NamedTuple):
    id: str
    name: str
    used_for: str
    url: str | None
    licence: str | None
    licence_status: Literal["checked", "not_checked"]
    licence_note: str


SOURCE_NOTES: tuple[SourceNote, ...] = (
    SourceNote(
        "iso-codes", "ISO 3166-2:IN, ISO 639 and ISO 15924 code lists",
        "Identifiers for regions, languages and scripts.", None, None, "not_checked",
        "Codes are used as identifiers. The terms of the code lists were not reviewed for this pack."),
    SourceNote(
        "official-language-lists", "Official-language lists from state and union territory legislation",
        "Which languages are principal or additional for each region. No speaker share is asserted.", None, None, "not_checked",
        "Curated by hand from the legislation. The terms of the underlying texts were not reviewed."),
    SourceNote(
        "census-2011-c16", "Census of India 2011, table C-16 (population by mother tongue)",
        "Mother-tongue shares for the four demo states.", "https://censusindia.gov.in/nada/",
        "All rights reserved by the Census Digital Library (catalog page footer)", "checked",
        "Counts are stored as facts with the table's own citation; the workbook is not redistributed. "
        "A 2011 snapshot, never current."),
    SourceNote(
        "wikidata", "Wikidata", "Entity resolution and region-linked signals (queried live, not bundled).",
        "https://www.wikidata.org/wiki/Wikidata:Licensing", "CC0 1.0", "checked",
        "Wikidata requires a CC0 license. It throttles heavily; a throttled call is reported as a gap, not hidden."),
    SourceNote(
        "wikipedia-pageviews", "Wikimedia pageviews", "Attention over time for a festival's article, per language edition.",
        "https://wikimedia.org/api/rest_v1/metrics/pageviews", None, "not_checked",
        "The documentation states no data licence. Treated as Wikimedia open data; not verified as CC0."),
    SourceNote(
        "curated-references", "Curated references (English Wikipedia and government tourism pages)",
        "Festivals, foods, colours, symbols, customs and sensitivities for the four demo states.", None,
        "Wikipedia text: CC BY-SA 4.0. Government pages: each site's own terms.", "checked",
        "Short excerpts are stored with the page URL and title as attribution. Only short cited excerpts are kept."),
    SourceNote(
        "python-holidays", "python-holidays", "Public-holiday dates by state, from the installed package release.",
        "https://pypi.org/project/holidays/", "MIT", "checked",
        "Licence read from the package metadata. Dates follow the package release; verify before a launch."),
    SourceNote(
        "asci-code-index", "ASCI Code for Self-Regulation of Advertising Content in India (excerpts)",
        "Exact, cited clauses used by Risk Check as reference. Not legal advice and not an ASCI ruling.",
        "https://www.ascionline.in/the-asci-code-guidelines/", None, "not_checked",
        "Short exact excerpts with their PDF page and URL. No licence statement was found for the document; "
        "ASCI's own terms apply."),
)

# Gaps that hold today and are not visible from the data itself. Gaps that can be computed (coverage by state, the
# curated-reference dates, the ad-code limitations) are added by the service.
STATIC_GAPS = (
    "Only four states (IN-MH, IN-TN, IN-KL, IN-WB) have curated cultural references, Census 2011 language shares and "
    "pageview series. The other 32 states and union territories have regions, languages and scripts only.",
    "The Eighth Schedule of the Constitution lists 22 languages; Maithili and Sindhi are not in this pack's language list.",
    "Regions carry principal and additional languages with no speaker share. Sourced figures live in claims, not here.",
    "The moment list gives typical months only. Exact dates come from the public-holiday package or a dated claim.",
    "Census figures are from 2011 and are state level: no city tier or age split.",
    "Curated references lean on English Wikipedia and a few government pages. Regional-language sources and native "
    "review are not yet included.",
    "Public-holiday dates cover only observances declared holidays, and follow the python-holidays release in use.",
)

SAMPLING_DIMENSIONS = (
    ("state", "ISO 3166-2:IN region code", ()),
    ("language", "ISO 639 language code", ()),
    ("city_tier", None, ("tier1", "tier2", "tier3", "rural")),
    ("age_band", None, ("18-24", "25-34", "35-44", "45-54", "55+")),
)


def content_fingerprint() -> str:
    """SHA-256 over the reference data that the version number stands for (regions, languages, moments, pack record)."""
    payload = {
        "version": india.PACK_VERSION,
        "languages": [list(r) for r in india.LANGUAGES],
        "regions": [[r.code, r.name, r.kind, r.primary, list(r.secondary)] for r in india.REGIONS],
        "moments": [[r.slug, r.name, r.kind, r.region, list(r.months), r.calendar, r.notes] for r in india.MOMENTS],
        "pack": india.PACK,
        "source": india.PACK_SOURCE,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
