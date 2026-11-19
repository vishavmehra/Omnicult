"use client";

import { Bot, CircleDashed, ExternalLink, Eye, GitCompareArrows, MessageSquareText, Sigma, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { ConfidenceIndicator, type ConfidenceLevel } from "@/components/evidence/confidence";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Claim kinds (contracts: ClaimKind). The kind says how we know, not how sure we are. */
export type ClaimKind = "observed" | "calculated" | "synthetic" | "interpretation" | "unverified";

export const KIND: Record<ClaimKind, { label: string; Icon: LucideIcon; meaning: string; className: string }> = {
  observed: { label: "Observed", Icon: Eye, meaning: "Directly supported by a source.", className: "text-ink" },
  calculated: { label: "Calculated", Icon: Sigma, meaning: "Produced by a documented calculation.", className: "text-ink" },
  synthetic: { label: "Panel response", Icon: Bot, meaning: "Produced by the audience panel.", className: "text-ink-secondary" },
  interpretation: {
    label: "Interpretation",
    Icon: MessageSquareText,
    meaning: "A reasoned conclusion, not itself an observed fact.",
    className: "text-ink-secondary",
  },
  unverified: { label: "Unverified", Icon: CircleDashed, meaning: "Not adequately supported yet.", className: "text-warning" },
};

export function KindTag({ kind }: { kind: ClaimKind }) {
  const { label, Icon, meaning, className } = KIND[kind];
  return (
    <span className={cn("inline-flex items-center gap-1 font-medium", className)} title={meaning}>
      <Icon aria-hidden className="size-3.5 shrink-0" />
      {label}
    </span>
  );
}

export type EvidenceSource = { label: string; url?: string | null; identifier?: string | null };
export type EvidenceScope = { region?: string | null; language?: string | null; cityTier?: string | null; period?: string | null };

function scopeText(scope: EvidenceScope | string) {
  if (typeof scope === "string") return scope;
  const parts = [scope.region, scope.language, scope.cityTier, scope.period].filter(Boolean);
  return parts.length ? parts.join(" · ") : "Country-wide";
}

function Cell({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0 px-3 py-2", className)}>
      <dt className="type-meta">{label}</dt>
      <dd className="mt-0.5 truncate text-[13px] text-ink-body">{children}</dd>
    </div>
  );
}

/**
 * One ledger entry: the claim, then its five tags (Source, Date, Kind, Scope, Confidence) as ruled columns. The
 * corner marks an entry with a receipt attached. Conflicts and staleness are stated in words, never only by colour.
 */
export function EvidenceRow({
  claim,
  source,
  published,
  retrieved,
  kind,
  scope,
  confidence,
  conflict,
  stale,
  className,
}: {
  claim?: ReactNode;
  source: EvidenceSource | null;
  published?: string | null;
  retrieved?: string | null;
  kind: ClaimKind;
  scope: EvidenceScope | string;
  confidence: ConfidenceLevel;
  conflict?: boolean;
  stale?: boolean;
  className?: string;
}) {
  return (
    <article className={cn("rounded-card border border-border bg-surface", source && "receipt-corner", className)}>
      {(claim || conflict || stale) && (
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 px-3.5 pt-3 pb-2.5">
          {claim && <p className="min-w-0 flex-1 text-[14.5px] leading-snug text-ink">{claim}</p>}
          <div className="flex flex-wrap gap-1.5">
            {conflict && (
              <span className="inline-flex items-center gap-1 rounded-stamp border border-warning/50 bg-warning-soft px-1.5 py-0.5 text-[11.5px] font-medium text-warning">
                <GitCompareArrows aria-hidden className="size-3.5" />
                Open conflict
              </span>
            )}
            {stale && (
              <span className="inline-flex items-center gap-1 rounded-stamp border border-border-strong/60 px-1.5 py-0.5 text-[11.5px] text-ink-secondary">
                Older than two years
              </span>
            )}
          </div>
        </div>
      )}
      <dl className="type-ledger grid grid-cols-2 border-t border-border sm:grid-cols-[minmax(0,1.4fr)_minmax(0,0.9fr)_minmax(0,0.9fr)_minmax(0,1fr)_minmax(0,1fr)] sm:divide-x sm:divide-border [&>*:nth-child(n+3)]:border-t [&>*:nth-child(n+3)]:border-border sm:[&>*:nth-child(n+3)]:border-t-0">
        <Cell label="Source" className="col-span-2 sm:col-span-1">
          {source ? (
            source.url ? (
              <a href={source.url} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 text-rose underline-offset-2 hover:underline">
                <span className="truncate">{source.label}</span>
                <ExternalLink aria-hidden className="size-3 shrink-0" />
                <span className="sr-only">(opens the original source in a new tab)</span>
              </a>
            ) : (
              source.label
            )
          ) : (
            <span className="text-ink-muted">No source</span>
          )}
        </Cell>
        <Cell label="Date">
          {published ? formatDate(published) : retrieved ? `Retrieved ${formatDate(retrieved)}` : <span className="text-ink-muted">Undated</span>}
        </Cell>
        <Cell label="Kind">
          <KindTag kind={kind} />
        </Cell>
        <Cell label="Scope">{scopeText(scope)}</Cell>
        <Cell label="Confidence">
          <ConfidenceIndicator level={confidence} />
        </Cell>
      </dl>
    </article>
  );
}
