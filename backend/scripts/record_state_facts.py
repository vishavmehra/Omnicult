"""Record the data.gov.in rows the State facts panel shows, for every state. Manual, opt-in, never run by pytest.

    uv --directory backend run python -m scripts.record_state_facts

Needs DATA_GOV_IN_API_KEY in the environment (the key is never printed). Makes one paged request per resource (at most 50
records each) through `DataGovClient`, keeps every record exactly as the API sent it, and writes
`app/fixtures/state_facts/all_states.json`. Demo campaigns parse that file with the same code a live pull uses and make no
network call; the seed job (`scripts/seed_state_facts.py`) loads it into the deployed database, because data.gov.in refuses
requests from Google Cloud addresses. Run it from an Indian connection.
"""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from app.integrations.culture.adapters.datagov import RESOURCES, DataGovClient, parse_records
from app.reference.india import REGIONS

OUT = Path(__file__).resolve().parents[1] / "app" / "fixtures" / "state_facts" / "all_states.json"


async def record() -> int:
    import json

    client = DataGovClient(get_settings().data_gov_in_api_key, timeout=90.0)
    out: dict[str, object] = {}
    for resource in RESOURCES:
        records, updated, total = await client.records(resource)
        rows, unmapped = parse_records(resource, records)
        found = {r.region_code for r in rows}
        missing = sorted({r.code for r in REGIONS} - found)
        print(f"{resource.key}: {len(records)} of {total} records, {len(rows)} figures; states with none: {missing or 'none'}; "
              f"names not mapped: {unmapped or 'none'}")
        out[resource.key] = {"resource_id": resource.resource_id, "title": resource.title, "total": total,
                             "updated_date": updated.isoformat() if updated else None, "records": records}
    payload = {"recorded_on": datetime.now(UTC).date().isoformat(), "regions": "all", "resources": out}
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(record()))
