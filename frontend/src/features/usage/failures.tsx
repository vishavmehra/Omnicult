"use client";

import { CircleAlert, CircleCheck } from "lucide-react";

import { SectionTitle } from "@/features/workspaces/parts";

import type { UsageReport } from "./api";
import { capabilityLabel, formatUtcTime, modelLabel, num } from "./format";

/** Failed model calls: how many per error code, then the newest ones with where they happened. */
export function Failures({ report }: { report: UsageReport }) {
  const failed = report.failed_calls;
  return (
    <section aria-labelledby="failed-calls" className="space-y-3">
      <SectionTitle id="failed-calls" meta={failed ? `${num.format(failed)} in this period` : undefined}>
        Failed calls
      </SectionTitle>
      {failed === 0 ? (
        <p className="flex items-center gap-2 text-[13.5px] text-ink-secondary">
          <CircleCheck aria-hidden className="size-4 text-success" />
          No failed calls in this period.
        </p>
      ) : (
        <>
          <ul aria-label="Failed calls by error code" className="flex flex-wrap gap-2">
            {report.failure_codes.map((c) => (
              <li key={c.error_code ?? "none"} className="inline-flex items-center gap-1.5 rounded-lg border border-danger/30 bg-danger-soft/50 px-2.5 py-1 text-[13px] text-ink">
                <CircleAlert aria-hidden className="size-3.5 text-danger" />
                {c.error_code ? <span className="font-mono text-[12px]">{c.error_code}</span> : <span>No code recorded</span>}
                <span className="type-ledger text-ink-secondary">{num.format(c.calls)}</span>
              </li>
            ))}
          </ul>
          <div className="overflow-x-auto rounded-card border border-border bg-surface">
            <table className="type-ledger w-full min-w-[40rem] text-[13px]">
              <caption className="sr-only">The newest failed calls</caption>
              <thead className="text-left text-ink-muted">
                <tr className="border-b border-border">
                  <th scope="col" className="px-4 py-2 font-normal">When</th>
                  <th scope="col" className="px-3 py-2 font-normal">Capability</th>
                  <th scope="col" className="px-3 py-2 font-normal">Model</th>
                  <th scope="col" className="px-3 py-2 font-normal">Error code</th>
                  <th scope="col" className="px-4 py-2 font-normal">Where</th>
                </tr>
              </thead>
              <tbody className="ledger-rules">
                {report.failures.map((f) => (
                  <tr key={f.id}>
                    <td className="px-4 py-2 whitespace-nowrap text-ink-body">{formatUtcTime(f.at)}</td>
                    <td className="px-3 py-2 whitespace-nowrap">{capabilityLabel(f.capability)}</td>
                    <td className="px-3 py-2 whitespace-nowrap">{modelLabel(`${f.provider} / ${f.model}`)}</td>
                    <td className="px-3 py-2">{f.error_code ? <span className="font-mono text-[12px]">{f.error_code}</span> : <span className="text-ink-muted">None recorded</span>}</td>
                    <td className="px-4 py-2 text-ink-secondary">
                      {[f.project_name, f.campaign_name, f.run_label].filter(Boolean).join(", ") || "Not tied to a project"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {failed > report.failures.length && <p className="type-meta">The newest {report.failures.length} are listed; the counts above cover all {num.format(failed)}.</p>}
        </>
      )}
    </section>
  );
}
