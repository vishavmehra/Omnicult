"use client";

import { CircleCheck, CircleDashed, TriangleAlert } from "lucide-react";

import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useCampaign } from "@/features/workspaces/campaign-context";

import { useSectionInfo } from "./api";
import { Fact, Kind, SELECT_CLASS } from "./parts";
import { ReportProvider, ReportSection } from "./report-sections";
import type { ProofReport, ProofReportSummary, ProofView } from "./types";

/** Which snapshot is open. The newest first; each is a fixed record of what was true when it was made. */
export function SnapshotPicker({ items, value, onChange }: { items: ProofReportSummary[]; value: string; onChange: (id: string) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label htmlFor="snapshot" className="text-[13px] font-medium text-ink">
        Snapshot
      </label>
      <select id="snapshot" value={value} onChange={(e) => onChange(e.target.value)} className={cn(SELECT_CLASS, "max-w-full")}>
        {items.map((r) => (
          <option key={r.id} value={r.id}>
            {`#${r.version_number} · ${formatDateTime(r.created_at)} · ${r.status === "partial" ? "partial" : "complete"}${r.mode === "demo" ? " · demo data" : ""}`}
          </option>
        ))}
      </select>
      <span className="type-meta">{items.length} saved, newest first. A snapshot is never changed.</span>
    </div>
  );
}

function DocumentHeader({ report }: { report: ProofReport }) {
  const { campaign } = useCampaign();
  const version = campaign.versions.find((v) => v.id === report.campaign_version_id);
  const partial = report.status === "partial";
  return (
    <header className="space-y-4 border-b border-border pb-6">
      <div className="space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          {partial ? (
            <span className="inline-flex items-center gap-1 rounded-stamp border border-warning/50 bg-warning-soft px-1.5 py-0.5 text-[11.5px] font-semibold text-warning">
              <TriangleAlert aria-hidden className="size-3.5" />
              Partial
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-stamp border border-success/45 bg-success-soft px-1.5 py-0.5 text-[11.5px] font-semibold text-success">
              <CircleCheck aria-hidden className="size-3.5" />
              Complete
            </span>
          )}
        </div>
        <h2 className="type-title text-[26px] text-ink sm:text-[30px]">{report.title}</h2>
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
        <Fact label="Snapshot">#{report.version_number} for this campaign</Fact>
        <Fact label="Made">{formatDateTime(report.created_at)}</Fact>
        <Fact label="Creative version">{version ? `v${version.version_number}` : "Not in the current list"}</Fact>
        <Fact label="Regions">{report.target_region_codes.length ? report.target_region_codes.join(", ") : "None reported on"}</Fact>
        <Fact label="Assembled by">
          Fixed rules ({report.assembly.registry_version}). No model was called.
        </Fact>
        <Fact label="Data">{report.mode === "demo" ? "Demo fixtures" : "Live"}</Fact>
        <Fact label="Fingerprint">
          <span className="font-mono text-[12px]" title={`SHA-256 of the sections: ${report.content_sha256}. The same inputs give the same hash.`}>
            {report.content_sha256.slice(0, 12)}
          </span>
        </Fact>
      </dl>

      {partial && (
        <details className="group rounded-card border border-warning/40 bg-warning-soft/40 px-3.5 py-2.5 text-[13.5px]">
          <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-ink marker:hidden">
            <TriangleAlert aria-hidden className="size-4 shrink-0 text-warning" />
            {report.missing_sections.length} of {report.sections.length} sections are not in this snapshot
            <span className="ml-auto text-[12px] font-normal text-ink-secondary group-open:hidden">Show which</span>
          </summary>
          <ul className="mt-2 space-y-1 border-t border-border pt-2">
            {report.missing_sections.map((m) => (
              <li key={m.id} className="text-ink-body">
                <a href={`#sec-${m.id}`} className="font-medium text-rose underline-offset-2 hover:underline">
                  {m.title}
                </a>
                <span className="text-ink-secondary">: {m.reason}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <details className="group text-[13px]">
        <summary className="cursor-pointer text-ink-secondary marker:hidden hover:text-ink">What the five kinds of content mean</summary>
        <ul className="mt-2 space-y-1.5">
          {report.kind_legend.map((k) => (
            <li key={k.kind} className="grid gap-x-3 sm:grid-cols-[9rem_minmax(0,1fr)]">
              <Kind kind={k.kind} />
              <span className="text-ink-secondary">{k.applies_to}</span>
            </li>
          ))}
        </ul>
      </details>
    </header>
  );
}

/** The report as a document: a title block, then every section in order with its kinds, content and limitations. */
export function ReportViewer({
  report,
  workspaceId,
  onOpenClaim,
  onOpenView,
}: {
  report: ProofReport;
  workspaceId: string | null;
  onOpenClaim: (claimId: string) => void;
  onOpenView: (view: ProofView) => void;
}) {
  const info = useSectionInfo();
  const wired = new Map((info.data ?? []).map((s) => [s.id, s.wired]));
  return (
    <ReportProvider value={{ report, workspaceId, mode: report.mode, openClaim: workspaceId ? onOpenClaim : undefined, openView: onOpenView }}>
      <article aria-label={report.title} className="rounded-card border border-border bg-surface px-4 py-6 sm:px-8 sm:py-8">
        <DocumentHeader report={report} />
        <div className="divide-y divide-border pt-6">
          {report.sections.map((s) => (
            <ReportSection key={s.id} section={s} wired={info.isSuccess ? wired.get(s.id) : undefined} />
          ))}
        </div>
        <footer className="mt-6 border-t border-border pt-4">
          <p className="max-w-[72ch] text-[12.5px] text-ink-muted">{report.legal_notice}</p>
        </footer>
      </article>
    </ReportProvider>
  );
}

/** Contents of the open report with each section's state, for the context panel. */
export function ReportToc({ report }: { report: ProofReport }) {
  return (
    <nav aria-label="Report contents" className="space-y-2">
      <h3 className="text-[13px] font-semibold text-ink">Report contents</h3>
      <ol className="ledger-rules rounded-card border border-border">
        {report.sections.map((s) => {
          const missing = s.status === "missing";
          return (
            <li key={s.id}>
              <a href={`#sec-${s.id}`} className="flex items-center gap-2 px-3 py-2 text-[13px] hover:bg-surface-muted focus-visible:-outline-offset-2">
                {missing ? <CircleDashed aria-hidden className="size-3.5 shrink-0 text-ink-muted" /> : <CircleCheck aria-hidden className="size-3.5 shrink-0 text-success" />}
                <span className={cn("min-w-0 flex-1 truncate", missing ? "text-ink-muted" : "text-ink-body")}>{s.title}</span>
                <span className="type-meta shrink-0">{missing ? "not included" : "included"}</span>
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
