"""Record the Moment Calendar's Google data. Manual, opt-in, never run by pytest.

    uv --directory backend run python -m scripts.record_lens_calendar

Needs GOOGLE_PUBLIC_API_KEY (an API key restricted to the Calendar and Knowledge Graph Search APIs; never printed). Writes
- `app/fixtures/lens_calendar/google_holidays.json`: the events of Google Calendar's public "Holidays in India" calendar for
  2026 to 2028, one request a year. Demo campaigns read it and make no call.
- `app/integrations/culture/data/moment_notes.json`: a Knowledge Graph description for every moment name the calendar can
  show (Google's events, every state's public-holiday list in python-holidays, the reference moments). A result is kept only
  where `lens_moments.accept_kg` finds the moment itself; a name with no such result is stored as null and shows no
  description. Both modes read it. Requests are paced (one every 0.2 s; the free quota is 100,000 a day).
"""

import asyncio
import json
import re
import sys
from datetime import UTC, datetime

import httpx

from app.core.config import get_settings
from app.reference import india
from app.services import lens_moments as lm

YEARS = (2026, 2027, 2028)
KEEP = ("id", "summary", "description", "start", "htmlLink", "status")


def query_text(name: str) -> str:
    return " ".join(re.sub(r"\([^)]*\)", " ", name).split())


async def main() -> int:
    key = get_settings().google_public_api_key
    if key is None:
        print("GOOGLE_PUBLIC_API_KEY is not set", file=sys.stderr)
        return 1
    secret = key.get_secret_value()
    today = datetime.now(UTC).date().isoformat()
    async with httpx.AsyncClient(timeout=20) as client:
        years: dict[str, list[dict]] = {}
        for year in YEARS:
            items = await lm.fetch_year(year, key, client)
            years[str(year)] = [{k: i.get(k) for k in KEEP if i.get(k) is not None} for i in items]
            print(f"{year}: {len(items)} events")
        lm.FIXTURES.mkdir(parents=True, exist_ok=True)
        lm.RECORDED_FILE.write_text(json.dumps(
            {"recorded_on": today, "calendar_id": lm.CALENDAR_ID, "calendar": lm.CALENDAR_NAME, "years": years},
            ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")

        names = {e.name for items in years.values() for e in lm.parse_items(items, None)}
        names |= {name for r in india.REGIONS for year in YEARS for _, name in lm.state_holidays(r.code, year)}
        names |= {row.name for row in india.MOMENTS}
        notes: dict[str, dict | None] = {}
        for name in sorted(names):
            key_ = lm.name_key(name)
            if not key_ or key_ in notes:
                continue
            found = None
            for query in (query_text(name), f"{query_text(name)} India"):
                response = None
                for _ in range(3):  # a slow answer is retried twice; a name that never answers keeps no description
                    try:
                        response = await client.get(lm.KG_API, params={"query": query, "key": secret, "limit": 5, "languages": "en"})
                        break
                    except httpx.HTTPError as error:
                        print(f"{name}: {type(error).__name__}, retrying", file=sys.stderr)
                        await asyncio.sleep(2)
                await asyncio.sleep(0.2)
                if response is None:
                    break
                if response.status_code != 200:
                    print(f"{name}: Knowledge Graph answered {response.status_code}", file=sys.stderr)
                    break
                found = lm.accept_kg(query_text(name), response.json().get("itemListElement", []))
                if found:
                    break
            notes[key_] = {"name": name, **found} if found else None
        kept = sum(1 for n in notes.values() if n)
        print(f"notes: {kept} of {len(notes)} names have a description that names the moment itself")
        lm.NOTES_FILE.write_text(json.dumps(
            {"recorded_on": today, "api": lm.KG_API, "rule": "Kept only when the result's name is the moment's name, or its description "
             "names the moment in its opening words (lens_moments.accept_kg).", "notes": notes},
            ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
