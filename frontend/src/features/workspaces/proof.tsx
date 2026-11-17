"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, FileText } from "lucide-react";
import Link from "next/link";

import { ContextPanel } from "@/components/shell/workspace-shell";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { RunStatusBadge } from "@/components/workflow/run-status";
import { sectionHref } from "@/features/project/workflow";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";

import { useCampaign } from "./campaign-context";
import { CampaignFacts, EarlierTools, FeatureScope, SectionTitle, useCampaignRuns, WorkspaceHeader } from "./parts";
import { RunLedger } from "./run-ledger";

/** Proof Vault: the campaign's reports as a reading list on paper, and the full run history as the ledger behind them. */
export function ProofWorkspace() {
  const { campaign } = useCampaign();
  const runs = useCampaignRuns(undefined, 50);
  const reports = useQuery({
    queryKey: ["reports", campaign.project_id, "campaign", campaign.id],
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/projects/{project_id}/reports", { params: { path: { project_id: campaign.project_id }, query: { limit: 50 } } }))).items.filter(
        (r) => r.campaign_id === campaign.id,
      ),
  });
  const proofHref = sectionHref(campaign.project_id, "proof", campaign.id);

  return (
    <>
      <WorkspaceHeader workspace="proof">
        <CampaignFacts />
      </WorkspaceHeader>
      <div className="grid gap-6 2xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <section aria-labelledby="reports" className="space-y-2.5">
          <SectionTitle id="reports" meta="Each report keeps its version">
            Proof reports
          </SectionTitle>
          {reports.error ? (
            <ErrorState error={reports.error} onRetry={() => void reports.refetch()} />
          ) : reports.isPending ? (
            <LoadingState label="Loading reports…" />
          ) : reports.data.length === 0 ? (
            <EmptyState
              title="No report for this campaign yet"
              description="A Proof Report gathers regional findings with their sources, conflicts, creative changes, audience results, risk findings, readiness, limitations and run metadata."
              needs={[
                { label: "At least one completed run", met: Boolean(runs.data?.some((r) => r.status === "completed")) },
                { label: "A report created from the earlier Proof page", met: false },
              ]}
              action={
                <Link href={proofHref} className="inline-flex items-center gap-1 text-[13.5px] font-medium text-rose hover:underline">
                  Open the Proof page to create one
                  <ArrowUpRight aria-hidden className="size-4" />
                </Link>
              }
            />
          ) : (
            <ul className="creative-mat ledger-rules rounded-card">
              {reports.data.map((r) => (
                <li key={r.id}>
                  <Link href={`/projects/${r.project_id}/proof/${r.id}?campaign=${r.campaign_id}`} className="flex items-start gap-3 px-4 py-3.5 hover:bg-black/[0.03]">
                    <FileText aria-hidden className="mt-0.5 size-4 shrink-0 opacity-70" />
                    <span className="min-w-0 flex-1">
                      <span className="type-title block text-[18px]">{r.title}</span>
                      <span className="block text-[12.5px] opacity-75">
                        Version {r.version_number} · {formatDateTime(r.created_at)} · {r.mode === "demo" ? "demo fixture" : "live"}
                      </span>
                    </span>
                    <RunStatusBadge status={r.status} className="text-[12px]" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section aria-labelledby="history" className="space-y-2.5">
          <SectionTitle id="history" meta={runs.data ? `${runs.data.length} runs` : undefined}>
            Run history
          </SectionTitle>
          {runs.error ? (
            <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
          ) : runs.isPending ? (
            <LoadingState label="Loading run history…" />
          ) : (
            <RunLedger runs={runs.data} empty="No runs recorded for this campaign yet. Every analysis, rehearsal, adaptation and evaluation will be listed here with its state." />
          )}
        </section>
      </div>
      <ContextPanel title="Evidence">
        <EarlierTools
          tools={[
            { segment: "graph", label: "Evidence graph", note: "Sources, claims and findings as a connected map" },
            { segment: "proof", label: "Proof", note: "Create and export reports" },
          ]}
        />
        <FeatureScope workspace="proof" />
      </ContextPanel>
    </>
  );
}
