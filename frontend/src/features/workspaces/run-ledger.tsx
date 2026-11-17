"use client";

import Link from "next/link";

import { RunStatusBadge } from "@/components/workflow/run-status";
import { RUN_TYPE_META, sectionHref } from "@/features/project/workflow";
import type { Run } from "@/lib/api/types";
import { formatDateTime, formatElapsed, formatRelative, shortId } from "@/lib/format";

/**
 * Runs as ledger lines with fixed columns: type, state, started, duration, id. A changing run keeps its row and columns;
 * only its state word changes (held state, no reflow). Each row opens the page that owns the run's result.
 */
export function RunLedger({ runs, empty }: { runs: Run[]; empty: string }) {
  if (!runs.length) return <p className="rounded-card border border-dashed border-border-strong/50 px-4 py-3 text-[13px] text-ink-muted">{empty}</p>;
  return (
    <div className="overflow-x-auto rounded-card border border-border bg-surface">
      <table className="type-ledger w-full min-w-[34rem] text-left text-[13px]">
        <thead className="bg-surface-muted text-[11.5px] text-ink-muted">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Run</th>
            <th scope="col" className="w-[11.5rem] px-3 py-2 font-medium">State</th>
            <th scope="col" className="w-[9rem] px-3 py-2 font-medium">Started</th>
            <th scope="col" className="w-[6rem] px-3 py-2 font-medium">Took</th>
            <th scope="col" className="w-[6.5rem] px-3 py-2 font-medium">Id</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {runs.map((run) => {
            const meta = RUN_TYPE_META[run.run_type];
            const start = run.started_at ?? run.created_at;
            return (
              <tr key={run.id} className="hover:bg-surface-muted/60">
                <td className="px-3 py-2">
                  <Link href={sectionHref(run.project_id, meta.segment, run.campaign_id)} className="font-medium text-ink hover:text-rose hover:underline">
                    {meta.label}
                  </Link>
                  {run.mode === "demo" && <span className="ml-2 text-[11.5px] text-warning">demo fixture</span>}
                  {run.error && <p className="mt-0.5 max-w-[48ch] truncate text-[12px] text-danger" title={run.error.message}>{run.error.message}</p>}
                </td>
                <td className="px-3 py-2">
                  <RunStatusBadge status={run.status} />
                </td>
                <td className="px-3 py-2 text-ink-secondary" title={formatDateTime(start)}>
                  {formatRelative(start)}
                </td>
                <td className="px-3 py-2 text-ink-secondary tabular-nums">
                  {run.completed_at ? formatElapsed(Date.parse(run.completed_at) - Date.parse(start)) : "…"}
                </td>
                <td className="px-3 py-2 font-mono text-[11.5px] text-ink-muted">{shortId(run.id)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
