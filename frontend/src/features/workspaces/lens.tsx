"use client";

import { ContextPanel } from "@/components/shell/workspace-shell";
import { LensApp } from "@/features/lens/lens-app";

import { useCampaign } from "./campaign-context";
import { CampaignFacts, EarlierTools, FeatureScope, WorkspaceHeader } from "./parts";

/**
 * Market Lens: the Culture Atlas, State Profile, Moment Calendar, Region Compare and Language Map over one set of sourced
 * claims. Nothing is shown that was not sourced; a state with no evidence says so.
 */
export function LensWorkspace() {
  const { campaign } = useCampaign();
  return (
    <>
      <WorkspaceHeader workspace="lens">
        <CampaignFacts />
      </WorkspaceHeader>
      <LensApp campaignId={campaign.id} />
      <ContextPanel title="Region context">
        <FeatureScope workspace="lens" />
        <EarlierTools
          tools={[
            { segment: "atlas", label: "Atlas", note: "Cultural discovery and market brief" },
            { segment: "cultural-dna", label: "Cultural DNA", note: "Versioned cultural profile of a market" },
            { segment: "market-expansion", label: "Market Expansion", note: "Compare markets on shared evidence" },
            { segment: "trend-watch", label: "Trend Watch", note: "Snapshots compared over time" },
          ]}
        />
      </ContextPanel>
    </>
  );
}
