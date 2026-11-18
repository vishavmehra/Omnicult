"""Record the public data the Aamod demo shows in Trend Radar and Category Shelf. Manual, opt-in, never run by pytest.

    uv --directory backend run python -m scripts.record_lens_t3_fixtures [--pause 1.0]

Reads two free public sources politely (Wikimedia pageviews through Wikidata sitelinks, and the Wikidata API, both through
`HttpFetcher`: descriptive User-Agent, serial requests, a pause between items) and writes
`app/fixtures/lens_t3/recorded.json`. Demo mode reads that file and makes no network call. The file is real data with its
retrieval date, not a synthetic series; the demo labels it as recorded.

What is recorded: monthly pageviews (and each edition's own monthly total) (regional edition and English) of the festival articles the demo claims cite, of the
category topics, and of the brands and products Wikidata links to the demo states; and the shelf discovery itself.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.analytics.lens_trends import add_months, festival_articles, month_start
from app.core.config import get_settings
from app.integrations.culture import RegionProfileBuilder, build_culture_service
from app.integrations.culture.adapters.wikipedia_attention import WikipediaAttentionSource
from app.integrations.culture.base import SourceRateLimited
from app.integrations.culture.regions import REGIONS
from app.integrations.culture.shelf import WikidataShelfSource, pack_by_key

OUT = Path(__file__).resolve().parents[1] / "app" / "fixtures" / "lens_t3" / "recorded.json"
DEMO_PACK = "festive_sweets_snacks"
MONTHS = 24
MAX_FESTIVALS = 9
MAX_ENTITIES = 8


def window(today: date) -> tuple[date, date]:
    end = month_start(today) - timedelta(days=1)  # the last complete month
    return add_months(month_start(end), -(MONTHS - 1)), end


async def record(pause: float, reuse: bool) -> int:
    settings = get_settings()
    today = datetime.now(UTC).date()
    start, end = window(today)
    pageviews = WikipediaAttentionSource(user_agent=settings.wikimedia_user_agent, timeout=settings.culture_http_timeout_seconds)
    shelf_source = WikidataShelfSource(user_agent=settings.wikimedia_user_agent, timeout=settings.culture_http_timeout_seconds)
    pack = pack_by_key(DEMO_PACK)
    assert pack is not None
    fixture_builder = RegionProfileBuilder(build_culture_service(settings, mode="demo"))

    wanted: dict[tuple[str, str], str] = {}  # (term, region) -> why
    for code, region in REGIONS.items():
        profile = await fixture_builder.build(code, years=(2027,), today=date(2026, 11, 17))
        claims = [(c.subject, [(s.source_type, s.url) for s in c.sources]) for c in profile.claims_by_category["festival"]]
        for _, title in festival_articles(claims, region.name)[:MAX_FESTIVALS]:
            wanted[(title, code)] = "festival"
        for topic in pack.topics:
            wanted[(topic.entity_id, code)] = "category"

    print(f"Shelf discovery for '{pack.label}' ...")
    for attempt in range(3):
        discovery = await shelf_source.discover(pack)
        if not any("failed" in gap for gap in discovery.gaps):
            break
        print(f"  a Wikidata request failed (attempt {attempt + 1}); waiting 70 s before asking again")
        await asyncio.sleep(70)
    print(f"  {len(discovery.entities)} kept, {len(discovery.excluded)} excluded, {len(discovery.gaps)} gaps, {len(discovery.calls)} calls")
    placed = [e for e in discovery.entities if e.region_codes][:MAX_ENTITIES]
    for entity in placed:
        wanted[(entity.entity_id, entity.region_codes[0])] = "entity"

    before = json.loads(OUT.read_text(encoding="utf-8")) if reuse and OUT.exists() else {}
    series: dict[str, dict] = before.get("series", {})
    baselines: dict[str, list] = before.get("baselines", {})
    failures = 0
    for (term, code), why in sorted(wanted.items(), key=lambda kv: (kv[0][1], kv[1], kv[0][0])):
        if f"{term}|{code}" in series:
            continue
        result, error = None, None
        for attempt in range(4):
            try:
                result = await pageviews.trend_series(term, region_code=code, start=start, end=end)
                error = None
                break
            except SourceRateLimited as exc:  # the host told us to wait: wait, then ask again
                error = exc
                print(f"  waiting 35 s ({term} {code}, attempt {attempt + 1})")
                await asyncio.sleep(35)
            except Exception as exc:  # noqa: BLE001 - a failed term is reported, never invented
                error = exc
                break
        if error is not None:
            print(f"  FAILED {term} {code}: {type(error).__name__}: {error}")
            failures += 1
            continue
        if result is None:
            print(f"  no article  {term} {code}")
            continue
        for e in result.editions:  # the edition's own monthly total, kept once per project
            if e.baseline:
                baselines[e.project] = [[p.date.strftime("%Y-%m"), p.views] for p in e.baseline]
        series[f"{term}|{code}"] = {
            "term": term, "region_code": code, "why": why, "granularity": result.granularity, "url": result.source.url,
            "editions": [{"language": e.language, "project": e.project, "article": e.article,
                          "points": [[p.date.strftime("%Y-%m"), p.views] for p in e.points]} for e in result.editions]}
        print(f"  ok  {why:9} {term} {code}: " + ", ".join(f"{e.language} {e.total:,}" for e in result.editions))
        await asyncio.sleep(pause)

    for project in sorted({e["project"] for v in series.values() for e in v["editions"]} - set(baselines)):
        totals = None
        for attempt in range(4):  # a failure is not kept by the adapter, so asking again after a wait is a real retry
            totals = await pageviews._edition_totals(project, start, end)  # noqa: SLF001 - the recorder reads what the adapter reads
            if totals:
                break
            print(f"  baseline {project}: not read (attempt {attempt + 1}); waiting 35 s")
            await asyncio.sleep(35)
        if totals:
            baselines[project] = [[p.date.strftime("%Y-%m"), p.views] for p in totals]
        print(f"  baseline {project}: {'ok' if totals else 'NOT READ'}")
        await asyncio.sleep(pause)

    recorded = {
        "recorded_on": today.isoformat(), "window": {"start": start.isoformat(), "end": end.isoformat()},
        "source": "Wikimedia pageviews REST API (per-article, all-access, user) and the Wikidata API, read politely on the date shown.",
        "series": series,
        "baselines": baselines,
        "shelf": {DEMO_PACK: json.loads(discovery.model_copy(update={"calls": []}).model_dump_json())},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = ["{", f'"recorded_on": {json.dumps(recorded["recorded_on"])},', f'"window": {json.dumps(recorded["window"])},',
             f'"source": {json.dumps(recorded["source"])},', '"series": {']
    lines.append(",\n".join(f"{json.dumps(k)}: {json.dumps(v, separators=(',', ':'))}" for k, v in sorted(series.items())))
    lines.append("},")
    lines.append('"baselines": {' + ",\n".join(f"{json.dumps(k)}: {json.dumps(v, separators=(',', ':'))}" for k, v in sorted(baselines.items())) + "},")
    lines.append('"shelf": ' + json.dumps(recorded["shelf"], indent=1, ensure_ascii=False))
    lines.append("}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json.loads(OUT.read_text(encoding="utf-8"))  # the file must parse
    print(f"Wrote {OUT} ({len(series)} series, {failures} failures)")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between items")
    parser.add_argument("--reuse", action="store_true", help="keep series already in the file; read only what is missing")
    args = parser.parse_args()
    sys.exit(asyncio.run(record(args.pause, args.reuse)))


if __name__ == "__main__":
    main()
