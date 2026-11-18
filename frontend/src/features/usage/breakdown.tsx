"use client";

import { useState } from "react";

import { SectionTitle } from "@/features/workspaces/parts";
import { cn } from "@/lib/utils";

import type { UsageReport, UsageRow } from "./api";
import { capabilityLabel, costParts, modelLabel, num } from "./format";

type Dimension = "capability" | "model" | "project" | "campaign" | "user" | "run";

const DIMENSIONS: { key: Dimension; label: string; column: string }[] = [
  { key: "capability", label: "Capability", column: "Capability" },
  { key: "model", label: "Model", column: "Model" },
  { key: "project", label: "Project", column: "Project" },
  { key: "campaign", label: "Campaign", column: "Campaign" },
  { key: "user", label: "Person", column: "Person" },
  { key: "run", label: "Run", column: "Run" },
];

function rowsOf(report: UsageReport, d: Dimension): UsageRow[] {
  return { capability: report.by_capability, model: report.by_model, project: report.by_project, campaign: report.by_campaign, user: report.by_user, run: report.by_run }[d];
}

function nameOf(d: Dimension, r: UsageRow) {
  if (d === "capability") return capabilityLabel(r.key);
  if (d === "model") return modelLabel(r.key);
  return r.label ?? `${r.key.slice(0, 8)}`;
}

/** The same calls cut six ways. Owners get every cut; other members get their own calls, so the person cut is left out for them. */
export function Breakdown({ report }: { report: UsageReport }) {
  const [dimension, setDimension] = useState<Dimension>("capability");
  const available = DIMENSIONS.filter((d) => d.key !== "user" || report.scope === "workspace");
  const active = available.find((d) => d.key === dimension) ?? available[0];
  const rows = rowsOf(report, active.key);
  const omitted = report.omitted_rows[active.key] ?? 0;
  return (
    <section aria-labelledby="breakdown" className="space-y-3">
      <SectionTitle id="breakdown">Where it went</SectionTitle>
      <div role="group" aria-label="Break down by" className="flex flex-wrap gap-1.5">
        {available.map((d) => (
          <button
            key={d.key}
            type="button"
            aria-pressed={d.key === active.key}
            onClick={() => setDimension(d.key)}
            className={cn(
              "flex h-9 items-center rounded-lg border px-3 text-[13.5px]",
              d.key === active.key ? "clay border-border font-medium text-ink" : "border-transparent text-ink-secondary hover:bg-surface-muted hover:text-ink",
            )}
          >
            {d.label}
          </button>
        ))}
      </div>
      <div className="overflow-x-auto rounded-card border border-border bg-surface">
        <table className="type-ledger w-full min-w-[40rem] text-[13px]">
          <caption className="sr-only">Calls, tokens and estimated cost by {active.label.toLowerCase()}</caption>
          <thead className="text-left text-ink-muted">
            <tr className="border-b border-border">
              <th scope="col" className="px-4 py-2 font-normal">{active.column}</th>
              <th scope="col" className="px-3 py-2 text-right font-normal">Calls</th>
              <th scope="col" className="px-3 py-2 text-right font-normal">Failed</th>
              <th scope="col" className="px-3 py-2 text-right font-normal">Tokens in</th>
              <th scope="col" className="px-3 py-2 text-right font-normal">Tokens out</th>
              <th scope="col" className="px-4 py-2 text-right font-normal">Estimated cost</th>
            </tr>
          </thead>
          <tbody className="ledger-rules">
            {rows.map((r) => {
              const cost = costParts(r);
              return (
                <tr key={r.key}>
                  <th scope="row" className="max-w-[22rem] px-4 py-2 text-left font-normal break-words text-ink-body">{nameOf(active.key, r)}</th>
                  <td className="px-3 py-2 text-right">{num.format(r.calls)}</td>
                  <td className="px-3 py-2 text-right">{num.format(r.failed_calls)}</td>
                  <td className="px-3 py-2 text-right">{num.format(r.input_tokens)}</td>
                  <td className="px-3 py-2 text-right">{num.format(r.output_tokens + r.thinking_tokens)}</td>
                  <td className="px-4 py-2 text-right">
                    <span className={cn(cost.recorded ? "text-ink" : "text-ink-muted")}>{cost.value}</span>
                    {cost.note && <span className="type-meta block">{cost.note}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {omitted > 0 && <p className="type-meta">{num.format(omitted)} more {omitted === 1 ? "row is" : "rows are"} not listed. The totals above include {omitted === 1 ? "it" : "them"}.</p>}
    </section>
  );
}
