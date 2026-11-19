"use client";

import { useState } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { useCampaign } from "@/features/workspaces/campaign-context";

import { useSamplingOptions } from "../api";
import { RunPicker } from "../lab-parts";
import { pluralise } from "../labels";
import { SetupPanel } from "../sampling-form";
import type { useLabLocation } from "../use-lab-location";
import { useBuzz, useBuzzRuns, useSessionDefaults } from "./buzz-api";
import { BuzzForm } from "./buzz-setup";
import { BuzzView } from "./buzz-result";

type Loc = ReturnType<typeof useLabLocation>;

/**
 * Buzz Simulator: how a creative could be passed on inside a synthetic population, per state and language. Spread, sentiment
 * and cohort counts are computed from the saved acts; the posts are the model's. The one source line says what it is.
 */
export function BuzzTab({ loc }: { loc: Loc }) {
  const { campaign } = useCampaign();
  const options = useSamplingOptions();
  const defaults = useSessionDefaults(campaign.id);
  const runs = useBuzzRuns(campaign.id);
  const selectedId = loc.runId ?? runs.data?.[0]?.id ?? null;
  const result = useBuzz(campaign.id, selectedId);
  const [open, setOpen] = useState<boolean | null>(null);
  const setupOpen = open ?? (runs.isSuccess && runs.data.length === 0);
  const stateName = (code: string) => options.data?.states.find((s) => s.code === code)?.name ?? code;

  const failure = options.error ?? defaults.error ?? runs.error;
  if (failure) return <ErrorState error={failure} onRetry={() => void Promise.all([options.refetch(), defaults.refetch(), runs.refetch()])} />;
  if (runs.isPending || !options.data || !defaults.data) return <LoadingState label="Loading Buzz Simulator…" />;

  const items = runs.data ?? [];

  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <p className="max-w-[68ch] text-[14px] text-ink-secondary">
          Posts, replies and reshares in response to the creative, per state and language: who sees it, who passes it on, what they say and how the message changes on the way.
        </p>
      </div>

      <SetupPanel title="New simulation" meta={items.length ? undefined : "Start here"} open={setupOpen} onOpenChange={setOpen}>
        <BuzzForm
          options={options.data}
          defaults={defaults.data}
          onStarted={(id) => {
            setOpen(false);
            loc.selectRun(id);
          }}
        />
      </SetupPanel>

      <RunPicker runs={items} selectedId={selectedId} onSelect={loc.selectRun} regionName={stateName} describe={(r) => pluralise(r.participant_count, "account")} />

      {selectedId && result.error && <ErrorState error={result.error} onRetry={() => void result.refetch()} />}
      {selectedId && !result.data && !result.error && <LoadingState label="Opening the simulation…" />}
      {result.data && <BuzzView result={result.data} stateName={stateName} onNewRun={() => setOpen(true)} />}
    </div>
  );
}
