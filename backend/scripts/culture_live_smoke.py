"""Opt-in live smoke check of the culture adapters against the real services. Not run by pytest.

    uv --directory backend run python -m scripts.culture_live_smoke [--regions IN-MH,IN-TN,IN-KL,IN-WB] [--pause 20]

Calls: Wikidata entity resolution (an unambiguous and an ambiguous term), then one full region profile per region (python-holidays,
census, curated, Wikidata languages/scripts/linked items, Wikipedia pageviews for up to three festivals). Needs no credential:
Wikidata and Wikimedia are open APIs, so keep the pause between regions (the SPARQL endpoint rate-limits bursts with HTTP 429).
Gemini grounding is not exercised here (it needs the gateway's grounded_research capability). Prints a sanitized report: per
call the source, operation, status, latency, result count and the typed error, then claim counts per category, claims with
two independent source groups, and the disagreements found (same subject, attribute and scope; different values).
Exit code 0 when no call errored, 1 otherwise.
"""

import argparse
import asyncio
import sys
from collections import defaultdict

from app.core.config import get_settings
from app.integrations.culture import RegionProfileBuilder, build_culture_service
from app.integrations.culture.profile import PROFILE_CATEGORIES, _fingerprint
from app.integrations.culture.regions import REGIONS
from app.schemas.claims import ClaimDraft


def disagreements(claims: list[ClaimDraft]) -> list[tuple[ClaimDraft, ClaimDraft]]:
    groups: dict[tuple, list[ClaimDraft]] = defaultdict(list)
    for c in claims:
        groups[(c.subject, c.attribute, c.scope.model_dump_json())].append(c)
    return [(a, b) for members in groups.values() for i, a in enumerate(members) for b in members[i + 1:]
            if _fingerprint(a.value) != _fingerprint(b.value)]


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    service = build_culture_service(settings, mode="live")
    errors = 0
    print(f"User-Agent: {settings.wikimedia_user_agent}\nTimeout: {settings.culture_http_timeout_seconds}s\n")
    print("== entity resolution (Wikidata)")
    for term, region in (("Gudi Padwa", "IN-MH"), ("Pongal", "IN-TN")):
        res = await service.resolve_entity(term, language="en", region_code=region)
        print(f"  {term!r}: {res.status}; " + "; ".join(f"{c.label} ({c.entity_id}, {c.match_type})" for c in res.candidates[:4]))
        await asyncio.sleep(2)
    for code in (r.strip() for r in args.regions.split(",")):
        if code not in REGIONS:
            print(f"unknown region {code}")
            return 2
        await asyncio.sleep(args.pause)
        profile = await RegionProfileBuilder(service).build(code)
        print(f"\n== profile {code} {profile.region_name}")
        for r in profile.call_log:
            errors += r.status == "error"
            print(f"  {r.source:<20} {r.operation:<16} {r.status:<6} {r.duration_ms:>6} ms  n={r.result_count:<4} "
                  f"{'cached ' if r.cached else ''}{r.error_type or ''} {r.error or ''}")
        claims = profile.all_claims()
        print("  claims:", ", ".join(f"{c}={len(profile.claims_by_category[c])}" for c in PROFILE_CATEGORIES), f"| total {len(claims)}")
        two = [c for c in claims if len({s.independence_group for s in c.sources}) >= 2]
        print(f"  claims with 2+ independence groups: {len(two)}")
        for a, b in disagreements(claims):
            print(f"  DISAGREEMENT {a.subject} {a.attribute} {a.scope.language or ''}: {a.value!r} ({a.sources[0].independence_group})"
                  f" vs {b.value!r} ({b.sources[0].independence_group})")
        for gap in profile.gaps:
            print("  gap:", gap)
    return 1 if errors else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--regions", default=",".join(REGIONS))
    parser.add_argument("--pause", type=float, default=20.0, help="seconds between regions (SPARQL rate limit)")
    sys.exit(asyncio.run(run(parser.parse_args())))
