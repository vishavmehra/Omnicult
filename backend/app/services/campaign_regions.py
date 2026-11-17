"""Where a campaign keeps its target regions. The one place that knows; the Campaign Brief stream changes it only here."""


def campaign_region_codes(target_markets: list[dict], requested: list[str] | None) -> tuple[list[str], str]:
    """Region codes (ISO 3166-2) to report on, and where they came from.

    A request that names regions wins (an empty request means "none"); otherwise each campaign target market that has a
    `region_code` contributes it. Country-only markets (no region code) give no region: nothing is inferred."""
    if requested is not None:
        return list(dict.fromkeys(requested)), "request"
    codes = [t["region_code"] for t in target_markets if isinstance(t, dict) and t.get("region_code")]
    return list(dict.fromkeys(codes)), "campaign"
