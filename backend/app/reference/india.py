"""India reference data: 36 states and union territories (ISO 3166-2:IN), their languages and scripts, and curated moments.

This is structural reference data, like a gazetteer. It is not evidence: a statement such as "Tamil is spoken by X
percent of Tamil Nadu" is a claim with sources, created through `ClaimDraft`. "primary" below means the principal
official language of the state or union territory; "secondary" means an additional official or widely used language.
No speaker share is asserted here.

Languages use ISO 639-1; ISO 639-3 is used only where no two-letter code exists (flagged in `LANGUAGES`).
Scripts are ISO 15924. Region ids are stable (`region_id`), so every environment seeds the same UUIDs.
"""

from typing import NamedTuple
from uuid import NAMESPACE_URL, UUID, uuid5

COUNTRY = "IN"
PACK_VERSION = "1"
DEMO_REGIONS = ("IN-MH", "IN-TN", "IN-KL", "IN-WB")
REGION_NAMESPACE = uuid5(NAMESPACE_URL, "https://omnicult.app/ns/region")


def region_id(code: str) -> UUID:
    return uuid5(REGION_NAMESPACE, code)


class LanguageRow(NamedTuple):
    code: str
    name: str
    native_name: str
    script: str
    direction: str = "ltr"
    standard: str = "iso639-1"


LANGUAGES: tuple[LanguageRow, ...] = (
    LanguageRow("en", "English", "English", "Latn"),
    LanguageRow("hi", "Hindi", "हिन्दी", "Deva"),
    LanguageRow("mr", "Marathi", "मराठी", "Deva"),
    LanguageRow("ta", "Tamil", "தமிழ்", "Taml"),
    LanguageRow("ml", "Malayalam", "മലയാളം", "Mlym"),
    LanguageRow("bn", "Bengali", "বাংলা", "Beng"),
    LanguageRow("te", "Telugu", "తెలుగు", "Telu"),
    LanguageRow("kn", "Kannada", "ಕನ್ನಡ", "Knda"),
    LanguageRow("gu", "Gujarati", "ગુજરાતી", "Gujr"),
    LanguageRow("pa", "Punjabi", "ਪੰਜਾਬੀ", "Guru"),
    LanguageRow("or", "Odia", "ଓଡ଼ିଆ", "Orya"),
    LanguageRow("as", "Assamese", "অসমীয়া", "Beng"),  # ISO 15924 has no separate Assamese script code
    LanguageRow("ur", "Urdu", "اردو", "Arab", "rtl"),
    LanguageRow("ne", "Nepali", "नेपाली", "Deva"),
    LanguageRow("ks", "Kashmiri", "کٲشُر", "Arab", "rtl"),
    LanguageRow("sa", "Sanskrit", "संस्कृतम्", "Deva"),
    LanguageRow("bo", "Tibetan (Bhoti)", "བོད་སྐད་", "Tibt"),
    LanguageRow("kok", "Konkani", "कोंकणी", "Deva", standard="iso639-3"),
    LanguageRow("mni", "Meitei (Manipuri)", "ꯃꯤꯇꯩꯂꯣꯟ", "Mtei", standard="iso639-3"),
    LanguageRow("brx", "Bodo", "बड़ो", "Deva", standard="iso639-3"),
    LanguageRow("doi", "Dogri", "डोगरी", "Deva", standard="iso639-3"),
    LanguageRow("sat", "Santali", "ᱥᱟᱱᱛᱟᱲᱤ", "Olck", standard="iso639-3"),
    LanguageRow("lus", "Mizo", "Mizo ṭawng", "Latn", standard="iso639-3"),
    LanguageRow("kha", "Khasi", "Khasi", "Latn", standard="iso639-3"),
    LanguageRow("grt", "Garo", "A·chik", "Latn", standard="iso639-3"),
    LanguageRow("trp", "Kokborok", "Kokborok", "Latn", standard="iso639-3"),
)
SCRIPT_OF = {row.code: row.script for row in LANGUAGES}


class RegionRow(NamedTuple):
    code: str
    name: str
    kind: str  # state | union_territory
    primary: str
    secondary: tuple[str, ...]


REGIONS: tuple[RegionRow, ...] = (
    RegionRow("IN-AN", "Andaman and Nicobar Islands", "union_territory", "hi", ("en",)),
    RegionRow("IN-AP", "Andhra Pradesh", "state", "te", ("en",)),
    RegionRow("IN-AR", "Arunachal Pradesh", "state", "en", ("hi",)),
    RegionRow("IN-AS", "Assam", "state", "as", ("bn", "brx")),
    RegionRow("IN-BR", "Bihar", "state", "hi", ("ur",)),
    RegionRow("IN-CH", "Chandigarh", "union_territory", "en", ("hi", "pa")),
    RegionRow("IN-CG", "Chhattisgarh", "state", "hi", ("en",)),
    RegionRow("IN-DH", "Dadra and Nagar Haveli and Daman and Diu", "union_territory", "hi", ("en", "gu")),
    RegionRow("IN-DL", "Delhi", "union_territory", "hi", ("en", "pa", "ur")),
    RegionRow("IN-GA", "Goa", "state", "kok", ("mr", "en")),
    RegionRow("IN-GJ", "Gujarat", "state", "gu", ("hi", "en")),
    RegionRow("IN-HR", "Haryana", "state", "hi", ("en", "pa")),
    RegionRow("IN-HP", "Himachal Pradesh", "state", "hi", ("en", "sa")),
    RegionRow("IN-JK", "Jammu and Kashmir", "union_territory", "ur", ("hi", "ks", "doi", "en")),
    RegionRow("IN-JH", "Jharkhand", "state", "hi", ("en", "ur", "bn", "sat")),
    RegionRow("IN-KA", "Karnataka", "state", "kn", ("en",)),
    RegionRow("IN-KL", "Kerala", "state", "ml", ("en",)),
    RegionRow("IN-LA", "Ladakh", "union_territory", "hi", ("en", "ur", "bo")),
    RegionRow("IN-LD", "Lakshadweep", "union_territory", "ml", ("en",)),
    RegionRow("IN-MP", "Madhya Pradesh", "state", "hi", ("en",)),
    RegionRow("IN-MH", "Maharashtra", "state", "mr", ("hi", "en")),
    RegionRow("IN-MN", "Manipur", "state", "mni", ("en",)),
    RegionRow("IN-ML", "Meghalaya", "state", "en", ("kha", "grt")),
    RegionRow("IN-MZ", "Mizoram", "state", "lus", ("en",)),
    RegionRow("IN-NL", "Nagaland", "state", "en", ()),
    RegionRow("IN-OD", "Odisha", "state", "or", ("en",)),
    RegionRow("IN-PY", "Puducherry", "union_territory", "ta", ("en", "te", "ml")),
    RegionRow("IN-PB", "Punjab", "state", "pa", ("hi", "en")),
    RegionRow("IN-RJ", "Rajasthan", "state", "hi", ("en",)),
    RegionRow("IN-SK", "Sikkim", "state", "ne", ("en",)),
    RegionRow("IN-TN", "Tamil Nadu", "state", "ta", ("en",)),
    RegionRow("IN-TS", "Telangana", "state", "te", ("ur", "en")),
    RegionRow("IN-TR", "Tripura", "state", "bn", ("trp", "en")),
    RegionRow("IN-UP", "Uttar Pradesh", "state", "hi", ("ur", "en")),
    RegionRow("IN-UT", "Uttarakhand", "state", "hi", ("sa", "en")),
    RegionRow("IN-WB", "West Bengal", "state", "bn", ("ne", "hi", "ur", "sat", "en")),
)

LANGUAGE_NOTE = (
    "Principal and additional official or widely used languages of the state or union territory. "
    "This is not a measure of speaker share; see the language claims for sourced figures."
)


class MomentRow(NamedTuple):
    slug: str
    name: str
    kind: str  # festival | holiday | season | event
    region: str | None  # ISO 3166-2 code, or None for national
    months: tuple[int, ...]
    calendar: str  # solar | lunisolar | civil
    notes: str


MOMENTS: tuple[MomentRow, ...] = (
    MomentRow("diwali", "Diwali (Deepavali)", "festival", None, (10, 11), "lunisolar",
              "Festival of lights celebrated across India; the date follows the lunisolar calendar."),
    MomentRow("holi", "Holi", "festival", None, (3,), "lunisolar", "Spring festival of colours; lunisolar date."),
    MomentRow("republic-day", "Republic Day", "holiday", None, (1,), "civil", "National holiday on 26 January."),
    MomentRow("independence-day", "Independence Day", "holiday", None, (8,), "civil", "National holiday on 15 August."),
    MomentRow("gudi-padwa", "Gudi Padwa", "festival", "IN-MH", (3, 4), "lunisolar",
              "Marathi new year, on the first day of the lunisolar month of Chaitra."),
    MomentRow("ganesh-chaturthi", "Ganesh Chaturthi", "festival", "IN-MH", (8, 9), "lunisolar",
              "Ten-day festival; the largest public celebrations are in Maharashtra."),
    MomentRow("pongal", "Thai Pongal", "festival", "IN-TN", (1,), "solar",
              "Harvest festival around 14 to 15 January (Tamil month of Thai)."),
    MomentRow("puthandu", "Puthandu (Tamil New Year)", "festival", "IN-TN", (4,), "solar",
              "Tamil new year around 14 April."),
    MomentRow("onam", "Onam", "festival", "IN-KL", (8, 9), "lunisolar",
              "Harvest festival in the Malayalam month of Chingam; the date follows the Thiruvonam star."),
    MomentRow("vishu", "Vishu", "festival", "IN-KL", (4,), "solar", "Malayalam new year around 14 to 15 April."),
    MomentRow("durga-puja", "Durga Puja", "festival", "IN-WB", (9, 10), "lunisolar",
              "Major festival in West Bengal, in the lunisolar month of Ashwin."),
    MomentRow("poila-boishakh", "Poila Boishakh (Bengali New Year)", "festival", "IN-WB", (4,), "solar",
              "Bengali new year around 14 to 15 April."),
)
MOMENT_NOTE = "Typical months only. Exact dates for a year come from a dated claim (holidays package or curated list)."

PACK = {
    "country_code": COUNTRY,
    "name": "India",
    "version": PACK_VERSION,
    "region_codes": [row.code for row in REGIONS],
    "demo_regions": list(DEMO_REGIONS),
    "scripts": sorted({row.script for row in LANGUAGES}),
    "sampling_dimensions": {
        "state": "ISO 3166-2:IN region code",
        "language": "ISO 639 language code",
        "city_tier": ["tier1", "tier2", "tier3", "rural"],
        "age_band": ["18-24", "25-34", "35-44", "45-54", "55+"],
    },
    "never_sampled": ["religion", "caste", "health", "sexual orientation", "political opinion"],
    "notes": (
        "Panels may vary by state, language, city tier and age band (decision M-13). "
        "Protected traits are never sampled. Reference data only: facts about a region are claims with sources."
    ),
}
PACK_SOURCE = "Omnicult curated reference: ISO 3166-2:IN, ISO 639, ISO 15924; official-language lists from state and union territory legislation"
