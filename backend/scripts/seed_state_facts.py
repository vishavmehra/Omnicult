"""Load the State facts recordings of every state into the database: data.gov.in (`app/fixtures/state_facts/all_states.json`) and
Google Data Commons (`datacommons_states.json`).

data.gov.in refuses requests from Google Cloud addresses, so the deployed service cannot pull it itself: it is recorded from an
Indian connection with `python -m scripts.record_state_facts` and loaded here by the omnicult-seed job. Data Commons is recorded with
`python -m scripts.record_datacommons`; loading it gives a fresh database its figures before the first live fetch. Idempotent: a
dataset whose recorded update date is already stored, and Data Commons figures that have not changed, are skipped.
    python -m scripts.seed_state_facts
"""

import asyncio
import sys

from app.db.session import dispose_engine, session
from app.services.state_facts import load_recording


async def main() -> int:
    try:
        async with session() as s, s.begin():
            summary = await load_recording(s)
        print(f"state facts: {summary.updated} sources stored, {summary.unchanged} unchanged, {summary.failed} failed")
        return 1 if summary.failed else 0
    finally:
        await dispose_engine()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
