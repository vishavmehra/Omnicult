"""Rebuild app/integrations/culture/data/census_2011_languages.json from the official Census of India 2011 files.

    uv --directory backend run --with openpyxl python -m scripts.culture_build_census

openpyxl is a build-time tool only (not a runtime dependency). The script downloads the four state workbooks of
table C-16 "Population by mother tongue" from the Census Digital Library (censusindia.gov.in), keeps the state-level
rows for mother tongues (area code 000, mother-tongue code ending 000) and writes speaker counts. A state's population
is the sum of those rows; it matches the published 2011 state totals. Languages below 0.5% are kept only when they are
one of the six demo languages (mr, ta, ml, bn, hi, en); everything else is folded into `other_speakers`.
"""

import html
import json
import re
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

import httpx

from app.core.config import get_settings

OUT = Path(__file__).resolve().parent.parent / "app" / "integrations" / "culture" / "data" / "census_2011_languages.json"
BASE = "https://censusindia.gov.in/nada/index.php/catalog"
# region -> (catalog id, download id, file name, state code), read from each catalog page on 2026-11-17.
FILES = {
    "IN-MH": ("10212", "13324", "DDW-C16-STMT-MDDS-2700.XLSX", "27"),
    "IN-TN": ("10222", "13334", "DDW-C16-STMT-MDDS-3300.XLSX", "33"),
    "IN-KL": ("10209", "13321", "DDW-C16-STMT-MDDS-3200.XLSX", "32"),
    "IN-WB": ("10226", "13338", "DDW-C16-STMT-MDDS-1900.XLSX", "19"),
}
ISO_639_1 = {
    "MARATHI": "mr", "HINDI": "hi", "TAMIL": "ta", "MALAYALAM": "ml", "BENGALI": "bn", "ENGLISH": "en", "URDU": "ur",
    "TELUGU": "te", "KANNADA": "kn", "GUJARATI": "gu", "NEPALI": "ne", "SINDHI": "sd", "PUNJABI": "pa", "ODIA": "or",
}
DEMO = {"mr", "ta", "ml", "bn", "hi", "en"}
MIN_SHARE = 0.005


def parse(path: Path, state_code: str) -> dict:
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
        if int(r[7]) / population >= MIN_SHARE or iso in DEMO:
            languages.append({"mother_tongue_code": str(r[5]), "name": name.title() if name.isupper() else name,
                              "iso639_1": iso, "speakers": int(r[7])})
        else:
            other += int(r[7])
    return {"state_code": state_code, "state_name": str(rows[0][4]).title(), "population": population,
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
    headers = {"User-Agent": get_settings().wikimedia_user_agent}
    states: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, httpx.Client(headers=headers, timeout=120, follow_redirects=True) as client:
        for region, (catalog, download, name, code) in FILES.items():
            url = f"{BASE}/{catalog}/download/{download}/{name}"
            target = Path(tmp) / name
            target.write_bytes(client.get(url).raise_for_status().content)
            meta = catalog_meta(client.get(f"{BASE}/{catalog}").raise_for_status().text)
            states[region] = {**parse(target, code), **meta, "catalog_url": f"{BASE}/{catalog}", "download_url": url, "file": name}
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
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
