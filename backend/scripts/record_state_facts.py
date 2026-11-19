"""Record the data.gov.in rows the demo's State facts panel shows. Manual, opt-in, never run by pytest.

    uv --directory backend run python -m scripts.record_state_facts

Needs DATA_GOV_IN_API_KEY in the environment (the key is never printed). Makes one paged request per resource (at most 50
records each, so 7 requests) through `DataGovClient`, keeps the records of the demo states plus the all-India row, exactly as the
API sent them, and writes `app/fixtures/state_facts/recorded.json`. Demo mode parses that file with the same code live mode
uses and makes no network call.

    uv --directory backend run python -m scripts.record_state_facts --all
keeps every record instead and writes `app/fixtures/state_facts/all_states.json`, which the seed job loads into the deployed
database: data.gov.in refuses requests from Google Cloud addresses, so the deployed service cannot pull it itself.
"""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from app.integrations.culture.adapters.datagov import NATIONAL, RESOURCES, DataGovClient, region_code_for
from app.reference.india import DEMO_REGIONS

OUT = Path(__file__).resolve().parents[1] / "app" / "fixtures" / "state_facts" / "recorded.json"
ALL = OUT.with_name("all_states.json")


async def record(every: bool = False) -> int:
    client = DataGovClient(get_settings().data_gov_in_api_key, timeout=90.0)
    keep = {*DEMO_REGIONS, NATIONAL}
    out_file = ALL if every else OUT
    out: dict[str, object] = {}
    for resource in RESOURCES:
        records, updated, total = await client.records(resource)
        mine = records if every else [r for r in records if region_code_for(r.get(resource.state_field), census_2011=resource.census_2011) in keep]
        found = {region_code_for(r.get(resource.state_field), census_2011=resource.census_2011) for r in mine}
        print(f"{resource.key}: {len(records)} of {total} records, kept {len(mine)}; missing {sorted(keep - found) or 'none'}")
        out[resource.key] = {"resource_id": resource.resource_id, "title": resource.title, "total": total,
                             "updated_date": updated.isoformat() if updated else None, "records": mine}
    out_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {"recorded_on": datetime.now(UTC).date().isoformat(), "regions": "all" if every else sorted(keep), "resources": out}
    out_file.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(record("--all" in sys.argv[1:])))
