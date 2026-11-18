"""Load the shared demo claims (the fixture claims behind the Aamod demo journey), and the reference tables they need.
Idempotent: safe to re-run; a database that already has them is left alone. Optional: the first "Try the demo" does it anyway.

Run from backend/ after the migrations, against the database named by DATABASE_URL:
    uv run python -m scripts.seed_demo_claims
"""

import asyncio

from app.db.session import dispose_engine
from app.services.demo_journey import prepare_shared_data


async def main() -> None:
    try:
        await prepare_shared_data()
        print("demo claims are in place")
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
