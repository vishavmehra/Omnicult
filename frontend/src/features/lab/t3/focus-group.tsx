"use client";

import { useState } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { useCampaign } from "@/features/workspaces/campaign-context";

import { useSamplingOptions } from "../api";
import { RunPicker } from "../lab-parts";
import { pluralise } from "../labels";
import { SetupPanel } from "../sampling-form";
import type { useLabLocation } from "../use-lab-location";
import { useFocusDefaults, useFocusGroup, useFocusRuns } from "./focus-api";
import { FocusSession } from "./focus-session";
import { FocusSetup } from "./focus-setup";

type Loc = ReturnType<typeof useLabLocation>;

/**
 * Live Focus Group: a moderated text discussion among participants of a finished panel. The moderator asks the guide's questions,
 * the participants answer and reply to each other, and the transcript fills in while the session runs. The selected session lives
 * in the URL, like every other Lab tab.
 */
export function FocusGroupTab({ loc }: { loc: Loc }) {
  const { campaign } = useCampaign();
  const defaults = useFocusDefaults(campaign.id);
  const options = useSamplingOptions();
  const runs = useFocusRuns(campaign.id);
  const selectedId = loc.runId ?? runs.data?.[0]?.id ?? null;
  const result = useFocusGroup(campaign.id, selectedId);
  const [open, setOpen] = useState<boolean | null>(null);
  const setupOpen = open ?? (runs.isSuccess && runs.data.length === 0);
  const regionName = (code: string) => options.data?.states.find((s) => s.code === code)?.name ?? code;

  if (defaults.error) return <ErrorState error={defaults.error} onRetry={() => void defaults.refetch()} />;
  if (runs.error) return <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />;
  if (runs.isPending || defaults.isPending) return <LoadingState label="Loading Focus Groups…" />;

  return (
    <div className="space-y-5">
      <p className="max-w-[68ch] text-[14px] text-ink-secondary">
        A moderated discussion among a few participants of a finished panel. The moderator asks your guide&apos;s questions, the participants answer and reply to each other, and you can put a question to the group while it talks. Themes and disagreements are counted from the saved transcript.
      </p>
      <SetupPanel title="New Focus Group" meta={runs.data.length ? undefined : "Start here"} open={setupOpen} onOpenChange={setOpen}>
        <FocusSetup
          defaults={defaults.data}
          loc={loc}
          onStarted={(id) => {
            setOpen(false);
            loc.selectRun(id);
          }}
        />
      </SetupPanel>

      <RunPicker runs={runs.data} selectedId={selectedId} onSelect={loc.selectRun} regionName={regionName} describe={(r) => pluralise(r.participant_count, "speaker")} />

      {selectedId && result.error && <ErrorState error={result.error} onRetry={() => void result.refetch()} />}
      {selectedId && !result.data && !result.error && <LoadingState label="Opening the session…" />}
      {result.data && (
        <FocusSession campaignId={campaign.id} result={result.data} maxInterjections={defaults.data.limits.focus_max_interjections} onNewRun={() => setOpen(true)} />
      )}
    </div>
  );
}
