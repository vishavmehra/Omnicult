"use client";

import { ContextPanel } from "@/components/shell/workspace-shell";
import { ErrorState, LoadingState } from "@/components/states";
import { CommentPulse } from "@/features/digest/comment-pulse";
import { PulseTabs, usePulseView } from "@/features/digest/tabs";
import { WeeklyDigest } from "@/features/digest/weekly-digest";
import { Dashboard } from "@/features/pulse/dashboard";
import { useDatasetStatus } from "@/features/pulse/api";
import { FreshnessPanel } from "@/features/pulse/freshness-panel";
import { Intro } from "@/features/pulse/intro";
import { MetricDefinitions, SourcesAndCalibration } from "@/features/pulse/sources";
import { AlertsTab } from "@/features/pulse-t3/alerts-tab";
import { FatigueTab } from "@/features/pulse-t3/fatigue-tab";
import { PredictedActualTab } from "@/features/pulse-t3/predicted-actual";

import { useCampaign } from "./campaign-context";
import { CampaignFacts, FeatureScope, WorkspaceHeader } from "./parts";

/**
 * Live Pulse on the sample dataset (one quiet source line per view). One row of tabs, driven by `?view=`: the regional
 * dashboard, Predicted vs Actual, Alerts, Fatigue Watch, Comment Pulse and the Weekly Digest.
 */
export function PulseWorkspace() {
  const { campaign } = useCampaign();
  const status = useDatasetStatus(campaign.id);
  const loaded = status.data?.loaded === true;
  const view = usePulseView();

  return (
    <>
      <WorkspaceHeader workspace="pulse">
        <CampaignFacts />
      </WorkspaceHeader>
      <PulseTabs view={view} />
      {view === "comments" ? (
        <CommentPulse campaignId={campaign.id} />
      ) : view === "digest" ? (
        <WeeklyDigest campaignId={campaign.id} />
      ) : view === "predicted" ? (
        <PredictedActualTab campaignId={campaign.id} />
      ) : view === "alerts" ? (
        <AlertsTab campaignId={campaign.id} />
      ) : view === "fatigue" ? (
        <FatigueTab campaignId={campaign.id} />
      ) : (
        <div className="space-y-8">
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
      )}
      <ContextPanel title="Data freshness">
        <FreshnessPanel campaignId={campaign.id} status={status.data} />
        <FeatureScope workspace="pulse" />
      </ContextPanel>
    </>
  );
}
