"""Load the reference tables (languages, regions, country pack, curated moments). Idempotent: safe to re-run.

Run from backend/ after the migrations, against the database named by DATABASE_URL:
    uv run python -m scripts.seed_reference_data
"""

import asyncio

from app.db.session import dispose_engine, session
from app.reference.seed import seed_reference_data


async def main() -> None:
    try:
        async with session() as s, s.begin():
            counts = await seed_reference_data(s)
        print(
            f"seeded {counts.languages} languages, {counts.regions} regions, {counts.profiles} language profiles, "
            f"{counts.moments} moments, {counts.packs} country pack"
        )
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
