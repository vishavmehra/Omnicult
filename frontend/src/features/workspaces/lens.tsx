"use client";

import { ContextPanel } from "@/components/shell/workspace-shell";
import { LensApp } from "@/features/lens/lens-app";

import { useCampaign } from "./campaign-context";
import { CampaignFacts, FeatureScope, WorkspaceHeader } from "./parts";

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
      </ContextPanel>
    </>
  );
}
