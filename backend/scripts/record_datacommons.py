"""Record the Google Data Commons responses the State facts panel shows, for every state. Manual, opt-in, never run by pytest.

    uv --directory backend run python -m scripts.record_datacommons

Needs DATA_COMMONS_API_KEY in the environment (the key is never printed). Makes two requests through `DataCommonsClient` (every
variable for the 36 states and India: one with date=LATEST, one with every year of the population series), keeps the facets the
catalogue picks exactly as the API sent them and drops the rest, and writes `app/fixtures/state_facts/datacommons_states.json`.
Demo campaigns parse that file with the same code a live pull uses and make no network call; the seed job
(`scripts/seed_state_facts.py`) loads it into the deployed database. It prints how many states each variable covers.
"""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.integrations.culture.adapters import datacommons as dc

OUT = Path(__file__).resolve().parents[1] / "app" / "fixtures" / "state_facts" / "datacommons_states.json"


def prune(payload: dict[str, Any], variables: tuple[dc.Variable, ...]) -> dict[str, Any]:
    """Only the facet each figure is taken from, and only the facet descriptions in use."""
    by_variable, facets = payload["byVariable"], payload.get("facets", {})
    kept: dict[str, Any] = {}
    used: set[str] = set()
    for variable in variables:
        for dcid in variable.dcids:
            for entity in dc.REGION_BY_DCID:
                top = dc._pick(by_variable, facets, dcid, entity, variable.prefer)
                if top is None:
                    continue
                chosen = next(f for f in by_variable[dcid]["byEntity"][entity]["orderedFacets"] if str(f.get("facetId")) == top[0])
                kept.setdefault(dcid, {"byEntity": {}})["byEntity"].setdefault(entity, {"orderedFacets": []})["orderedFacets"].append(chosen)
                used.add(top[0])
    return {"byVariable": kept, "facets": {k: v for k, v in facets.items() if k in used}}


async def record() -> int:
    raw = await dc.DataCommonsClient(get_settings().data_commons_api_key, timeout=90.0).fetch()
    rows, empty = dc.parse_responses(raw["latest"], raw["series"])
    pruned = {"latest": prune(raw["latest"], dc.LATEST_VARIABLES), "series": prune(raw["series"], dc.SERIES_VARIABLES)}
    again, _ = dc.parse_responses(pruned["latest"], pruned["series"])
    assert again == rows, "pruning changed what the parser reads"
    for variable in dc.VARIABLES:
        mine = [r for r in rows if r.metric == variable.key]
        states = {r.region_code for r in mine} - {dc.NATIONAL}
        periods = sorted({r.period for r in mine})
        print(f"{variable.key}: {len(states)} of 36 states; periods {periods[0]}..{periods[-1]}" if mine else f"{variable.key}: no figure",
              f"; all-India {'yes' if any(r.region_code == dc.NATIONAL for r in mine) else 'no'}")
    print(f"empty variables: {empty or 'none'}; {len(rows)} figures")
    payload = {"recorded_on": datetime.now(UTC).date().isoformat(), "regions": "all", "source": "api.datacommons.org/v2/observation", **pruned}
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(record()))
