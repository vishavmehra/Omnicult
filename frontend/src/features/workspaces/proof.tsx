"use client";

import { FilePlus2 } from "lucide-react";
import { useState } from "react";

import { ContextPanel } from "@/components/shell/workspace-shell";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ClaimDrawer } from "@/features/proof-vault/claim-drawer";
import { useProofReport, useProofReports } from "@/features/proof-vault/api";
import { DataHealthPanel } from "@/features/proof-vault/data-health";
import { EvidenceMap } from "@/features/proof-vault/evidence-map";
import { ReportTab } from "@/features/proof-vault/report-tab";
import { ReportToc } from "@/features/proof-vault/report-viewer";
import { RunHistoryPanel } from "@/features/proof-vault/run-history";
import { SearchPanel } from "@/features/proof-vault/search-panel";
import type { ProofView } from "@/features/proof-vault/types";
import { useProofParams, VIEWS } from "@/features/proof-vault/use-proof-params";

import { useCampaign } from "./campaign-context";
import { CampaignFacts, FeatureScope, WorkspaceHeader } from "./parts";

/**
 * Proof Vault: the record behind a decision. The Proof Report as a document with its exports, every run with its cost estimate,
 * the health of the sources, the evidence map, and search. Claims open in a drawer from anywhere.
 */
export function ProofWorkspace() {
  const { campaign, project } = useCampaign();
  const { view, reportId, claimId, set } = useProofParams();
  const [generateOpen, setGenerateOpen] = useState(false);
  const reports = useProofReports(campaign.id);
  const selectedId = reportId ?? reports.data?.items[0]?.id ?? null;
  const report = useProofReport(selectedId);
  const hasReports = (reports.data?.items.length ?? 0) > 0;
  const openClaim = (id: string) => set({ claim: id });

  return (
    <>
      <WorkspaceHeader
        workspace="proof"
        actions={
          view === "report" && hasReports ? (
            <Button onClick={() => setGenerateOpen(true)} disabled={generateOpen}>
              <FilePlus2 aria-hidden />
              Generate report
            </Button>
          ) : undefined
        }
      >
        <CampaignFacts />
      </WorkspaceHeader>

      <Tabs value={view} onValueChange={(v) => set({ view: v as ProofView, claim: null })}>
        <div className="-mx-1 overflow-x-auto px-1">
          <TabsList variant="line" className="group-data-horizontal/tabs:h-10 border-b border-border">
            {VIEWS.map((v) => (
              <TabsTrigger key={v.key} value={v.key} className="flex-none px-3 text-[14px]">
                {v.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>

        <TabsContent value="report" className="pt-5">
          <ReportTab reports={reports} report={report} selectedId={selectedId} generateOpen={generateOpen} onGenerateOpenChange={setGenerateOpen} />
        </TabsContent>
        <TabsContent value="history" className="pt-5">
          <RunHistoryPanel campaignId={campaign.id} />
        </TabsContent>
        <TabsContent value="health" className="pt-5">
          <DataHealthPanel workspaceId={project.workspace_id} mode={project.mode} />
        </TabsContent>
        <TabsContent value="map" className="pt-5">
          <EvidenceMap projectId={project.id} campaignId={campaign.id} onOpenClaim={openClaim} onOpenReport={(id) => set({ view: "report", report: id, claim: null })} suggestedRegion={report.data?.target_region_codes[0]} />
        </TabsContent>
        <TabsContent value="search" className="pt-5">
          <SearchPanel projectId={project.id} campaignId={campaign.id} onOpenClaim={openClaim} />
        </TabsContent>
      </Tabs>

      <ClaimDrawer workspaceId={project.workspace_id} mode={project.mode} claimId={claimId} onOpenClaim={openClaim} onClose={() => set({ claim: null })} />

      {/* The evidence map needs the width, so its view has no docked context panel. */}
      {view !== "map" && (
        <ContextPanel title="Proof Vault">
          {view === "report" && report.data && <ReportToc report={report.data} />}
          <FeatureScope workspace="proof" />
        </ContextPanel>
      )}
    </>
  );
}
