"use client";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useCampaign } from "@/features/workspaces/campaign-context";

import type { useProofReport, useProofReports } from "./api";
import { ExportsPanel } from "./exports-panel";
import { GenerateReport } from "./generate-report";
import { ReportViewer, SnapshotPicker } from "./report-viewer";
import { useProofParams } from "./use-proof-params";

type ReportsQuery = ReturnType<typeof useProofReports>;
type ReportQuery = ReturnType<typeof useProofReport>;

/** The Report view: the snapshot list, the open snapshot as a document, and its exports. */
export function ReportTab({
  reports,
  report,
  selectedId,
  generateOpen,
  onGenerateOpenChange,
}: {
  reports: ReportsQuery;
  report: ReportQuery;
  selectedId: string | null;
  generateOpen: boolean;
  onGenerateOpenChange: (open: boolean) => void;
}) {
  const { campaign, project } = useCampaign();
  const { set } = useProofParams();
  const created = (id: string) => {
    set({ view: "report", report: id, claim: null });
    onGenerateOpenChange(false);
  };

  if (reports.isPending) return <LoadingState label="Loading the campaign's reports…" />;
  if (reports.error) return <ErrorState error={reports.error} onRetry={() => void reports.refetch()} />;
  const items = reports.data.items;

  if (items.length === 0) {
    return (
      <div className="space-y-4">
        <EmptyState
          title="No Proof Report for this campaign yet"
          description={
            <>
              Generating one saves a snapshot of this campaign&apos;s evidence trail: the brief, the regions, every claim with its source, date, kind, scope and confidence, the Evidence Meter for each region, conflicts and the decisions on them, then
              limitations and the runs behind it. As the other workspaces connect, it also carries creative versions, risk flags, audience results, readiness and approvals. It is assembled by fixed rules, no model is called, and a
              section with nothing behind it is listed as missing instead of left blank.
            </>
          }
          needs={[
            { label: "A campaign with a saved creative version", met: true },
            { label: "Regions to report on: the campaign's own, or chosen when you generate" },
            { label: "Sourced claims for those regions, stored by Market Lens (without them the report is partial)" },
          ]}
        />
        <GenerateReport campaignId={campaign.id} suggestChoose onCreated={created} />
      </div>
    );
  }

  const open = report.data;
  return (
    <div className="space-y-4">
      <SnapshotPicker items={items} value={selectedId ?? items[0].id} onChange={(id) => set({ report: id, claim: null })} />
      {generateOpen && (
        <GenerateReport
          campaignId={campaign.id}
          suggestChoose={open?.target_region_codes.length === 0}
          onCreated={created}
          onCancel={() => onGenerateOpenChange(false)}
        />
      )}
      {report.isPending ? (
        <LoadingState label="Opening the snapshot…" />
      ) : report.error ? (
        <ErrorState error={report.error} onRetry={() => void report.refetch()} />
      ) : (
        <>
          <ExportsPanel report={report.data!} />
          <ReportViewer
            report={report.data!}
            workspaceId={project.workspace_id}
            onOpenClaim={(claimId) => set({ claim: claimId })}
            onOpenView={(view) => set({ view })}
          />
        </>
      )}
    </div>
  );
}
