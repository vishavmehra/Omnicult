"use client";

import { useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useCampaign } from "@/features/workspaces/campaign-context";

import { RunPicker } from "../lab-parts";
import { pluralise } from "../labels";
import { SetupPanel } from "../sampling-form";
import { useSamplingOptions } from "../api";
import type { useLabLocation } from "../use-lab-location";
import { useMessageCheck, useMessageChecks, useSessionDefaults, useStartMessageCheck } from "./check-api";
import { MessageCheckView } from "./check-result";
import { MessageCheckForm } from "./check-setup";

type Loc = ReturnType<typeof useLabLocation>;

/**
 * Message Check: does the intended message (default: the brief's primary message) land in each region? Synthetic participants read
 * only the regional copy, restate it and say what they remember; a separate comparison marks each key point and code counts.
 * One quiet line says what the panel is; every rate is "x of n".
 */
export function MessageCheckTab({ loc }: { loc: Loc }) {
  const { campaign } = useCampaign();
  const options = useSamplingOptions();
  const defaults = useSessionDefaults(campaign.id);
  const runs = useMessageChecks(campaign.id);
  const start = useStartMessageCheck(campaign.id);
  const selectedId = loc.runId ?? runs.data?.[0]?.id ?? null;
  const result = useMessageCheck(campaign.id, selectedId);
  const [open, setOpen] = useState<boolean | null>(null);
  const setupOpen = open ?? (runs.isSuccess && runs.data.length === 0);
  const regionName = (code: string) => options.data?.states.find((s) => s.code === code)?.name ?? code;

  if (options.error) return <ErrorState error={options.error} onRetry={() => void options.refetch()} />;
  if (defaults.error) return <ErrorState error={defaults.error} onRetry={() => void defaults.refetch()} />;
  if (runs.error) return <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />;
  if (runs.isPending || defaults.isPending || !options.data) return <LoadingState label="Loading Message Checks…" />;

  return (
    <div className="space-y-5">
      <p className="max-w-[68ch] text-[14px] text-ink-secondary">
        Simulated panel: synthetic participants read only the regional copy, restate it in their own words and say what stayed with them. Then a comparison marks each key point of the message, and the counts are made in code.
      </p>

      <SetupPanel title="New Message Check" meta={runs.data.length ? undefined : "Start here"} open={setupOpen} onOpenChange={setOpen}>
        <MessageCheckForm
          options={options.data}
          defaults={defaults.data}
          start={start}
          onStarted={(id) => {
            setOpen(false);
            loc.selectRun(id);
          }}
        />
      </SetupPanel>

      {runs.data.length === 0 && !setupOpen && (
        <EmptyState title="No Message Check yet" description="Open the form above to check whether the message survives in a region." />
      )}

      <RunPicker
        runs={runs.data}
        selectedId={selectedId}
        onSelect={loc.selectRun}
        regionName={regionName}
        describe={(r) => pluralise(r.participant_count, "synthetic participant")}
      />

      {selectedId && result.error && <ErrorState error={result.error} onRetry={() => void result.refetch()} />}
      {selectedId && !result.data && !result.error && <LoadingState label="Opening the Message Check…" />}
      {result.data && <MessageCheckView result={result.data} onNewRun={() => setOpen(true)} />}
    </div>
  );
}
