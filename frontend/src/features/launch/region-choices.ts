"use client";

import { useMemo } from "react";

import { useCampaign } from "@/features/workspaces/campaign-context";

import type { Region } from "./types";

/**
 * Regions for a picker: those the campaign targets (matched by name against its target markets) first, then the rest.
 * A target market that names a country rather than a state matches nothing, and nothing is inferred from it.
 */
export function useRegionChoices(regions: Region[] | undefined) {
  const { campaign } = useCampaign();
  return useMemo(() => {
    if (!regions) return [];
    const targeted = new Set(campaign.target_markets.map((m) => m.display_name.trim().toLowerCase()));
    const mine = regions.filter((r) => targeted.has(r.name.toLowerCase()));
    const rest = regions.filter((r) => !targeted.has(r.name.toLowerCase())).sort((a, b) => a.name.localeCompare(b.name));
    return [
      ...(mine.length ? [{ label: "Campaign regions", regions: mine }] : []),
      { label: mine.length ? "Other regions" : "Regions", regions: rest },
    ];
  }, [regions, campaign.target_markets]);
}
