"use client";

import { BookOpenText, Gauge, Info } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { workspaceHref } from "@/components/shell/workspaces";
import { Button, buttonVariants } from "@/components/ui/button";
import { EmptyState, ErrorState } from "@/components/states";
import { Skeleton } from "@/components/ui/skeleton";
import { useCampaign } from "@/features/workspaces/campaign-context";
import { SectionTitle } from "@/features/workspaces/parts";

import { useCapabilities, useReadinessBoard, useReadinessRules, useRegions, useVersionOptions } from "./api";
import { ComputeSheet, type ComputePreset } from "./compute-sheet";
import { HistoryTimeline, type HistoryFilter } from "./history";
import { RegionPanel } from "./region-panel";
import { RulesSheet } from "./rules";

/** The Readiness Board (feature 37): one panel per region with its Go, Fix or Rethink recommendation, then the verdict history. */
export function ReadinessTab() {
  const { campaign } = useCampaign();
  const board = useReadinessBoard(campaign.id);
  const rules = useReadinessRules(campaign.id);
  const caps = useCapabilities();
  const versions = useVersionOptions();
  const regions = useRegions();
  const [compute, setCompute] = useState<{ open: boolean; preset: ComputePreset }>({ open: false, preset: {} });
  const [rulesOpen, setRulesOpen] = useState(false);
  const [filter, setFilter] = useState<HistoryFilter>({ region: "", version: "" });

  const openCompute = (preset: ComputePreset = {}) => setCompute({ open: true, preset });
  const showHistory = (next: HistoryFilter) => {
    setFilter(next);
    window.setTimeout(() => document.getElementById("history")?.scrollIntoView({ block: "start" }), 0);
  };

  const hasVersions = versions.options.length > 0;
  const empty = board.data && board.data.regions.length === 0;

  return (
    <div className="space-y-10">
      <section aria-labelledby="board-title" className="space-y-4">
        <div className="space-y-2">
          <SectionTitle id="board-title" meta={rules.data ? `Rules ${rules.data.rule_version} · scoring ${rules.data.scoring_version}` : undefined}>
            Readiness by region
          </SectionTitle>
          <div className="flex flex-wrap items-center gap-2.5">
            <Button disabled={!caps.canCompute} onClick={() => openCompute()}>
              <Gauge aria-hidden />
              Compute verdict
            </Button>
            <Button variant="outline" onClick={() => setRulesOpen(true)}>
              <BookOpenText aria-hidden />
              Read the {rules.data ? rules.data.rules.length : ""} rules
            </Button>
          </div>
          {!caps.loading && caps.reason && !caps.canCompute && (
            <p role="status" className="flex max-w-[72ch] items-start gap-2 text-[13px] text-ink-secondary">
              <Info aria-hidden className="mt-0.5 size-4 shrink-0" />
              {caps.reason}
            </p>
          )}
        </div>

        {board.error ? (
          <ErrorState error={board.error} onRetry={() => void board.refetch()} />
        ) : board.isPending ? (
          <div role="status" aria-live="polite" className="space-y-4">
            <span className="sr-only">Reading the Readiness Board…</span>
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-56 rounded-card" />
            ))}
          </div>
        ) : empty ? (
          <EmptyState
            title="No readiness verdict yet"
            description="A verdict is computed for one version in one region by fixed rules, from observations such as a Quick Read, a Risk Check, transcreation checks and the region’s Evidence Meter. Until one is computed, nothing here says Go."
            needs={[
              { label: hasVersions ? `A creative version to judge (${versions.options.length} found)` : "A creative version to judge: make one in Creative Studio", met: hasVersions },
              { label: "A region to judge it in", met: Boolean(regions.data?.length) },
              { label: "Observations for that version and region, entered here or gathered. Anything missing is reported and holds the verdict at Fix; it is never assumed." },
            ]}
            action={
              <div className="flex flex-wrap items-center gap-2.5">
                {hasVersions ? (
                  <Button variant="outline" disabled={!caps.canCompute} onClick={() => openCompute()}>
                    <Gauge aria-hidden />
                    Compute the first verdict
                  </Button>
                ) : (
                  <Link href={workspaceHref(campaign.id, "studio")} className={buttonVariants({ variant: "outline", size: "sm" })}>
                    Open Creative Studio
                  </Link>
                )}
              </div>
            }
          />
        ) : (
          <div className="space-y-5">
            {board.data?.regions.map((region, i) => (
              <RegionPanel
                key={region.region_code}
                index={i}
                campaignId={campaign.id}
                region={region}
                rules={rules.data}
                caps={caps}
                onRecompute={openCompute}
                onHistory={showHistory}
              />
            ))}
          </div>
        )}
      </section>

      <HistoryTimeline campaignId={campaign.id} filter={filter} onFilter={setFilter} />

      <ComputeSheet campaignId={campaign.id} open={compute.open} onOpenChange={(open) => setCompute((c) => ({ ...c, open }))} preset={compute.preset} />
      <RulesSheet campaignId={campaign.id} open={rulesOpen} onOpenChange={setRulesOpen} />
    </div>
  );
}
