"""Rebuild app/integrations/culture/data/census_2011_languages.json from the official Census of India 2011 files.

    uv --directory backend run --with openpyxl python -m scripts.culture_build_census

openpyxl is a build-time tool only (not a runtime dependency). The script downloads the table C-16 "Population by
mother tongue" workbook of every 2011 state and union territory whose territory is unchanged since 2011 from the Census
Digital Library (censusindia.gov.in), keeps the state-level rows for languages (area code 000, mother-tongue code ending
000) and writes speaker counts. A state's population is the sum of those rows; it matches the published 2011 state totals
(table A-01). A language below 0.5% is kept only when it is one of the state's own languages in app.reference.india.REGIONS,
Hindi or English; the four original demo states also keep the six demo languages (mr, ta, ml, bn, hi, en), as first built.
Everything else, including the census row "Others" (mother tongues not grouped under any language), is folded into
`other_speakers`.
"""

import html
import json
import re
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.reference.india import DEMO_REGIONS, LANGUAGES, REGIONS

OUT = Path(__file__).resolve().parent.parent / "app" / "integrations" / "culture" / "data" / "census_2011_languages.json"
BASE = "https://censusindia.gov.in/nada/index.php/catalog"
# region -> (catalog id, download id, file name, state code), read from each catalog page (MH, TN, KL, WB on 2026-11-17,
# the rest on 2026-11-19). Not built, because today's region is not the 2011 territory: 01 Jammu & Kashmir (now IN-JK and
# IN-LA), 25 Daman & Diu and 26 Dadra & Nagar Haveli (merged into IN-DH in 2020), 28 Andhra Pradesh (now IN-AP and IN-TS).
FILES = {
    "IN-MH": ("10212", "13324", "DDW-C16-STMT-MDDS-2700.XLSX", "27"),
    "IN-TN": ("10222", "13334", "DDW-C16-STMT-MDDS-3300.XLSX", "33"),
    "IN-KL": ("10209", "13321", "DDW-C16-STMT-MDDS-3200.XLSX", "32"),
    "IN-WB": ("10226", "13338", "DDW-C16-STMT-MDDS-1900.XLSX", "19"),
    "IN-HP": ("10205", "13317", "DDW-C16-STMT-MDDS-0200.XLSX", "02"),
    "IN-PB": ("10219", "13331", "DDW-C16-STMT-MDDS-0300.XLSX", "03"),
    "IN-CH": ("10197", "13309", "DDW-C16-STMT-MDDS-0400.XLSX", "04"),
    "IN-UT": ("10225", "13337", "DDW-C16-STMT-MDDS-0500.XLSX", "05"),
    "IN-HR": ("10204", "13316", "DDW-C16-STMT-MDDS-0600.XLSX", "06"),
    "IN-DL": ("10201", "13313", "DDW-C16-STMT-MDDS-0700.XLSX", "07"),
    "IN-RJ": ("10220", "13332", "DDW-C16-STMT-MDDS-0800.XLSX", "08"),
    "IN-UP": ("10224", "13336", "DDW-C16-STMT-MDDS-0900.XLSX", "09"),
    "IN-BR": ("10196", "13308", "DDW-C16-STMT-MDDS-1000.XLSX", "10"),
    "IN-SK": ("10221", "13333", "DDW-C16-STMT-MDDS-1100.XLSX", "11"),
    "IN-AR": ("10194", "13306", "DDW-C16-STMT-MDDS-1200.XLSX", "12"),
    "IN-NL": ("10216", "13328", "DDW-C16-STMT-MDDS-1300.XLSX", "13"),
    "IN-MN": ("10213", "13325", "DDW-C16-STMT-MDDS-1400.XLSX", "14"),
    "IN-MZ": ("10215", "13327", "DDW-C16-STMT-MDDS-1500.XLSX", "15"),
    "IN-TR": ("10223", "13335", "DDW-C16-STMT-MDDS-1600.XLSX", "16"),
    "IN-ML": ("10214", "13326", "DDW-C16-STMT-MDDS-1700.XLSX", "17"),
    "IN-AS": ("10195", "13307", "DDW-C16-STMT-MDDS-1800.XLSX", "18"),
    "IN-JH": ("10207", "13319", "DDW-C16-STMT-MDDS-2000.XLSX", "20"),
    "IN-OD": ("10217", "13329", "DDW-C16-STMT-MDDS-2100.XLSX", "21"),
    "IN-CG": ("10198", "13310", "DDW-C16-STMT-MDDS-2200.XLSX", "22"),
    "IN-MP": ("10211", "13323", "DDW-C16-STMT-MDDS-2300.XLSX", "23"),
    "IN-GJ": ("10203", "13315", "DDW-C16-STMT-MDDS-2400.XLSX", "24"),
    "IN-KA": ("10208", "13320", "DDW-C16-STMT-MDDS-2900.XLSX", "29"),
    "IN-GA": ("10202", "13314", "DDW-C16-STMT-MDDS-3000.XLSX", "30"),
    "IN-LD": ("10210", "13322", "DDW-C16-STMT-MDDS-3100.XLSX", "31"),
    "IN-PY": ("10218", "13330", "DDW-C16-STMT-MDDS-3400.XLSX", "34"),
    "IN-AN": ("10192", "13304", "DDW-C16-STMT-MDDS-3500.XLSX", "35"),
}
ISO_639_1 = {
    "MARATHI": "mr", "HINDI": "hi", "TAMIL": "ta", "MALAYALAM": "ml", "BENGALI": "bn", "ENGLISH": "en", "URDU": "ur",
    "TELUGU": "te", "KANNADA": "kn", "GUJARATI": "gu", "NEPALI": "ne", "SINDHI": "sd", "PUNJABI": "pa", "ODIA": "or",
    "ASSAMESE": "as", "KASHMIRI": "ks", "SANSKRIT": "sa", "TIBETAN": "bo",
}
# The india.LANGUAGES codes that have no ISO 639-1 code: used only to keep a state's own languages (iso639_1 stays null).
ISO_639_3 = {"KONKANI": "kok", "MANIPURI": "mni", "BODO": "brx", "DOGRI": "doi", "SANTALI": "sat", "LUSHAI/MIZO": "lus",
             "KHASI": "kha", "GARO": "grt", "TRIPURI": "trp"}
DEMO = {"mr", "ta", "ml", "bn", "hi", "en"}
OTHERS = "124000"  # "Others": mother tongues the census did not group under a language; never listed as a language
MIN_SHARE = 0.005


def keep_below_min_share(region: str) -> set[str]:
    """Language codes kept even below MIN_SHARE: the region's own languages, Hindi and English; the four original demo
    states keep the six demo languages too, so their entries stay as first built."""
    row = next(r for r in REGIONS if r.code == region)
    return {row.primary, *row.secondary, "hi", "en"} | (DEMO if region in DEMO_REGIONS else set())


def parse(path: Path, state_code: str, keep: set[str]) -> dict:
    import openpyxl

    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        rows = [r for r in workbook.active.iter_rows(min_row=7, values_only=True)
                if r[0] and str(r[1]) == state_code and r[2] == "000" and r[3] == "00000" and str(r[5]).endswith("000")]
    finally:
        workbook.close()  # Windows keeps the file locked otherwise
    population = sum(int(r[7]) for r in rows)
    languages, other = [], 0
    for r in sorted(rows, key=lambda r: -int(r[7])):
        name = re.sub(r"^\d+\s+", "", str(r[6])).strip()
        iso = ISO_639_1.get(name.upper())
        if str(r[5]) != OTHERS and (int(r[7]) / population >= MIN_SHARE or (iso or ISO_639_3.get(name.upper())) in keep):
            languages.append({"mother_tongue_code": str(r[5]), "name": name.title() if name.isupper() else name,
                              "iso639_1": iso, "speakers": int(r[7])})
        else:
            other += int(r[7])
    state_name = str(rows[0][4]).title().replace("Nct Of ", "NCT of ")  # the census writes "NCT OF DELHI"
    return {"state_code": state_code, "state_name": state_name, "population": population,
            "languages": languages, "other_speakers": other}


def catalog_meta(page_html: str) -> dict[str, str]:
    """Reference id and catalog-entry date as printed on the Census Digital Library page for a table."""
    text = " ".join(html.unescape(re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", page_html, flags=re.S)).split())
    ref, created = re.search(r"Reference ID (\S+)", text), re.search(r"Created on ([A-Z][a-z]{2} \d{2}, \d{4})", text)
    cite = re.search(r"Citation (.*?) Back to Catalog", text)
    if not (ref and created and cite):
        raise SystemExit("catalog page layout changed: cannot read reference id, creation date and citation")
    return {"reference_id": ref.group(1), "catalog_created": datetime.strptime(created.group(1), "%b %d, %Y").date().isoformat(),
            "citation": cite.group(1)}


def main() -> int:
    missing = {row.code for row in LANGUAGES} - set(ISO_639_1.values()) - set(ISO_639_3.values())
    if missing:
        raise SystemExit(f"no census language name for {sorted(missing)}: a state's own language could be folded away")
    headers = {"User-Agent": get_settings().wikimedia_user_agent}
    pace = {"request": [lambda request: time.sleep(1)]}  # a public service: at most one request a second
    states: dict[str, dict] = {}
    with (tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp,
          httpx.Client(headers=headers, timeout=120, follow_redirects=True, event_hooks=pace) as client):
        for region, (catalog, download, name, code) in FILES.items():
            url = f"{BASE}/{catalog}/download/{download}/{name}"
            target = Path(tmp) / name
            target.write_bytes(client.get(url).raise_for_status().content)
            meta = catalog_meta(client.get(f"{BASE}/{catalog}").raise_for_status().text)
            if meta["reference_id"] != f"PC11_C16-{code}":
                raise SystemExit(f"{region}: catalog {catalog} is {meta['reference_id']}, not the C-16 table of state {code}")
            states[region] = {**parse(target, code, keep_below_min_share(region)), **meta,
                              "catalog_url": f"{BASE}/{catalog}", "download_url": url, "file": name}
            print(region, states[region]["population"], len(states[region]["languages"]), "languages")
    data = {
        "dataset_id": "census_2011_c16", "table_id": "C-16", "title": "C-16: Population by mother tongue", "year": "2011",
        "publisher": "Office of the Registrar General & Census Commissioner, India (Census of India 2011)",
        "retrieved_on": date.today().isoformat(),
        "published_at_note": "catalog_created is the date the table was added to the Census Digital Library, not the survey date; the data year is 2011.",
        "note": ("Speaker counts are persons by mother tongue as tabulated in the 2011 census. Shares are computed from the "
                 "table. This is a 2011 snapshot and must never be presented as current."),
        "states": states,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")  # LF on Windows too
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
