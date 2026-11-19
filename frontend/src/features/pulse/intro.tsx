"use client";

import { Database, LoaderCircle } from "lucide-react";

import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";

import { useLoadSample } from "./api";

/**
 * Before the data is loaded: what Live Pulse is and the one action that loads it. Nothing is drawn and no number is
 * shown until the user asks for it.
 */
export function Intro({ campaignId }: { campaignId: string }) {
  const load = useLoadSample(campaignId);
  return (
    <div className="space-y-3">
      <EmptyState
        title="Live Pulse is waiting for data"
        description={
          <div className="space-y-2">
            <p>
              Live Pulse shows how each version of a campaign is doing in each region: delivery, cost, response, video and outcome, with every figure carrying its platform,
              date range, last-updated time and whether it is still provisional.
            </p>
            <p>
              It covers three weeks of daily results for four regions and three versions, across Google Ads and YouTube.
            </p>
          </div>
        }
        needs={[
          { label: "The Live Pulse dataset: load it below", met: false },
        ]}
        action={
          <div className="space-y-2">
            <Button size="lg" onClick={() => load.mutate()} disabled={load.isPending}>
              {load.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <Database aria-hidden />}
              {load.isPending ? "Loading the data…" : "Load the dataset"}
            </Button>
            <p className="max-w-[60ch] text-[12.5px] text-ink-muted">
              Loading writes the rows to this campaign. Loading again replaces them with an identical copy. Only an owner or editor can load it.
            </p>
          </div>
        }
      />
      {load.error && <ErrorState error={load.error} onRetry={() => load.mutate()} />}
    </div>
  );
}
