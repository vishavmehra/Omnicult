"""Load the State facts recording of every state (`app/fixtures/state_facts/all_states.json`) into the database.

data.gov.in refuses requests from Google Cloud addresses, so the deployed service cannot pull State facts itself. The recording
is made from an Indian connection with `python -m scripts.record_state_facts --all` and loaded here by the omnicult-seed job.
Idempotent: a dataset whose recorded update date is already stored is skipped.
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
        print(f"state facts: {summary.updated} datasets stored, {summary.unchanged} unchanged, {summary.failed} failed")
        return 1 if summary.failed else 0
    finally:
        await dispose_engine()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
