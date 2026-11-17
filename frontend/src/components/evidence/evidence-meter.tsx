"use client";

import { TriangleAlert } from "lucide-react";

import { KIND, type ClaimKind } from "@/components/evidence/evidence-row";
import { cn } from "@/lib/utils";

const ORDER: ClaimKind[] = ["observed", "calculated", "interpretation", "synthetic", "unverified"];

// Fill per kind. Observed is the only solid ink fill: it is the evidence that carries weight. The others are quieter fills or
// patterns, and the legend names every segment with its count, so the meter never depends on colour.
const FILL: Record<ClaimKind, string> = {
  observed: "bg-ink",
  calculated: "bg-ink-secondary",
  interpretation: "bg-[repeating-linear-gradient(90deg,var(--ink-secondary)_0_2px,transparent_2px_5px)]",
  synthetic: "bg-[repeating-linear-gradient(45deg,var(--ink-muted)_0_1.5px,transparent_1.5px_5px)]",
  unverified: "bg-transparent outline outline-1 -outline-offset-2 outline-dashed outline-warning",
};

/**
 * Evidence Meter: what the claims for a scope are made of, by kind, plus how many independent source groups stand
 * behind them. A composition, not a score: it never turns into a percentage of "truth".
 */
export function EvidenceMeter({
  counts,
  independentGroups,
  conflicts = 0,
  scopeLabel,
  className,
}: {
  counts: Partial<Record<ClaimKind, number>>;
  independentGroups: number;
  conflicts?: number;
  scopeLabel: string;
  className?: string;
}) {
  const total = ORDER.reduce((sum, k) => sum + (counts[k] ?? 0), 0);
  const thin = total > 0 && ((counts.observed ?? 0) < 3 || independentGroups < 2);
  return (
    <section aria-label={`Evidence meter for ${scopeLabel}`} className={cn("space-y-2.5", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-semibold text-ink">Evidence for {scopeLabel}</h3>
        <p className="type-meta">
          {total} {total === 1 ? "claim" : "claims"} · {independentGroups} independent source {independentGroups === 1 ? "group" : "groups"}
          {conflicts > 0 && ` · ${conflicts} open ${conflicts === 1 ? "conflict" : "conflicts"}`}
        </p>
      </div>
      <div className="clay-well flex h-3.5 overflow-hidden rounded-[5px] p-[3px]" aria-hidden>
        {total === 0 ? (
          <span className="m-auto h-px w-full bg-border-strong/50" />
        ) : (
          ORDER.filter((k) => counts[k]).map((k) => (
            <span key={k} className={cn("h-full first:rounded-l-[3px] last:rounded-r-[3px]", FILL[k])} style={{ width: `${((counts[k] ?? 0) / total) * 100}%` }} />
          ))
        )}
      </div>
      {total === 0 ? (
        <p className="text-[13px] text-ink-secondary">No claims recorded for this scope yet, so nothing is calculated. Thin or missing evidence is shown as missing, not filled in.</p>
      ) : (
        <ul className="type-ledger flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-ink-body">
          {ORDER.filter((k) => counts[k]).map((k) => (
            <li key={k} className="inline-flex items-center gap-1.5">
              <span aria-hidden className={cn("size-2.5 rounded-[2px]", FILL[k])} />
              {KIND[k].label} <span className="text-ink-muted">{counts[k]}</span>
            </li>
          ))}
        </ul>
      )}
      {thin && (
        <p className="flex items-start gap-1.5 text-[12.5px] text-warning">
          <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          Thin coverage: fewer than three observed claims or fewer than two independent source groups.
        </p>
      )}
    </section>
  );
}
