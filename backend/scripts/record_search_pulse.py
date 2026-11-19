"""Record the demo snapshot of the search pulse: one real BigQuery query (about 0.9 GB, free tier), the four demo states.

    BIGQUERY_PROJECT=omnicult-app uv run python -m scripts.record_search_pulse

Writes app/fixtures/lens_t3/search_pulse.json. Demo mode reads that file and never queries BigQuery."""

import json
from datetime import date

from app.analytics import search_pulse as logic
from app.core.config import get_settings
from app.fixtures.lens_t3_demo import RECORDED_FILE as _LENS_T3
from app.integrations import google_trends as trends

DEMO_STATES = ("IN-MH", "IN-TN", "IN-KL", "IN-WB")
OUT = _LENS_T3.parent / "search_pulse.json"


def main() -> None:
    settings = get_settings()
    fetched = trends.fetch_india(settings)
    assert fetched is not None
    rows = [r for r in logic.shape(fetched.rows, weeks=settings.search_pulse_weeks, code_for=trends.omnicult_region) if r["region_code"] in DEMO_STATES]
    data = {
        "recorded_on": date.today().isoformat(), "refresh_date": fetched.refresh_date.isoformat(), "dataset": trends.DATASET,
        "job_id": fetched.job_id, "bytes_processed": fetched.bytes_processed, "regions": list(DEMO_STATES), "columns": list(logic.KEYS),
        "rows": [[r["week"].isoformat() if k == "week" else r[k] for k in logic.KEYS] for r in rows],
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(rows)} rows, refresh_date {fetched.refresh_date}, job {fetched.job_id}, bytes processed {fetched.bytes_processed}, billed {fetched.bytes_billed}")


if __name__ == "__main__":
    main()
