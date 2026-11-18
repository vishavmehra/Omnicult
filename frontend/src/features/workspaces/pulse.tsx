"use client";

import { ContextPanel } from "@/components/shell/workspace-shell";
import { ErrorState, LoadingState } from "@/components/states";
import { Dashboard } from "@/features/pulse/dashboard";
import { useDatasetStatus } from "@/features/pulse/api";
import { FreshnessPanel } from "@/features/pulse/freshness-panel";
import { Intro } from "@/features/pulse/intro";
import { SampleBand } from "@/features/pulse/sample-band";
import { MetricDefinitions, SourcesAndCalibration } from "@/features/pulse/sources";

import { useCampaign } from "./campaign-context";
import { CampaignFacts, FeatureScope, WorkspaceHeader } from "./parts";

/**
 * Live Pulse on the labelled sample dataset. The sample label is permanent (a sticky band), the dashboard appears only once
 * the sample is loaded, and platform connections and Predicted vs Actual state plainly that they are not available.
 */
export function PulseWorkspace() {
  const { campaign } = useCampaign();
  const status = useDatasetStatus(campaign.id);
  const loaded = status.data?.loaded === true;

  return (
    <>
      <WorkspaceHeader workspace="pulse">
        <CampaignFacts />
      </WorkspaceHeader>
      <div className="space-y-8">
        <SampleBand status={status.data} />
        {status.error ? (
          <ErrorState error={status.error} onRetry={() => void status.refetch()} />
        ) : !status.data ? (
          <LoadingState label="Checking the sample dataset…" />
        ) : loaded ? (
          <Dashboard campaignId={campaign.id} status={status.data} />
        ) : (
          <Intro campaignId={campaign.id} />
        )}
        <SourcesAndCalibration campaignId={campaign.id} />
        <MetricDefinitions campaignId={campaign.id} open={!loaded} />
      </div>
      <ContextPanel title="Data freshness">
        <FreshnessPanel campaignId={campaign.id} status={status.data} />
        <FeatureScope workspace="pulse" />
      </ContextPanel>
    </>
  );
}
