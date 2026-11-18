"use client";

import { CircleCheck, CircleDashed, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { EvidenceRow, KindTag, type EvidenceScope } from "@/components/evidence/evidence-row";
import { cn } from "@/lib/utils";
import { shortId } from "@/lib/format";

import type { ClaimView } from "./types";

/** A native select in the app's control vocabulary (32px, 9px corners, control edge, well). */
export const SELECT_CLASS =
  "h-8 min-w-0 rounded-lg border border-border-strong/55 bg-surface-muted px-2.5 text-[13.5px] text-ink shadow-well disabled:opacity-50";

/** Estimated cost. The API only ever estimates (price table), so the figure is always labelled as such by the caller. */
export function formatUsd(value: number) {
  return `$${value > 0 && value < 0.01 ? value.toFixed(4) : value.toFixed(2)}`;
}

export const formatCount = (n: number) => new Intl.NumberFormat("en").format(n);

export function scopeOf(scope: ClaimView["scope"]): EvidenceScope {
  return { region: scope.region_code, language: scope.language, cityTier: scope.city_tier, period: scope.period };
}

export function sourceLabel(claim: ClaimView) {
  const first = claim.sources[0];
  if (!first) return null;
  const label = first.title ?? first.publisher ?? first.source_type.replace(/_/g, " ");
  return { label: claim.sources.length > 1 ? `${label} (+${claim.sources.length - 1} more)` : label, url: first.url };
}

/** A claim as one ledger entry (its five tags); the statement opens the claim detail. */
export function ClaimRow({ claim, onOpen }: { claim: ClaimView; onOpen?: (claimId: string) => void }) {
  const statement = (
    <span lang={claim.scope.language ?? undefined}>
      {claim.value_text}
    </span>
  );
  return (
    <EvidenceRow
      claim={
        onOpen ? (
          <button type="button" onClick={() => onOpen(claim.id)} className="rounded-sm text-left underline-offset-2 hover:underline">
            {statement}
            <span className="sr-only"> (open claim detail)</span>
          </button>
        ) : (
          statement
        )
      }
      source={sourceLabel(claim)}
      published={claim.published_at}
      retrieved={claim.retrieved_at}
      kind={claim.kind}
      scope={scopeOf(claim.scope)}
      confidence={claim.effective_confidence}
      conflict={claim.conflict_ids.length > 0}
      stale={claim.stale}
    />
  );
}

/** What a claim id points at, as a short monospace button that opens the claim detail. */
export function ClaimChip({ id, onOpen }: { id: string; onOpen?: (claimId: string) => void }) {
  const label = `claim ${shortId(id)}`;
  if (!onOpen) return <span className="font-mono text-[11.5px] text-ink-muted">{label}</span>;
  return (
    <button type="button" onClick={() => onOpen(id)} className="rounded-sm font-mono text-[11.5px] text-rose underline-offset-2 hover:underline">
      {label}
    </button>
  );
}

export function ClaimChips({ ids, onOpen }: { ids: string[]; onOpen?: (claimId: string) => void }) {
  if (!ids.length) return null;
  return (
    <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
      <span className="type-meta">Evidence</span>
      {ids.map((id) => (
        <ClaimChip key={id} id={id} onOpen={onOpen} />
      ))}
    </span>
  );
}

/** Which kind of content a line is: the same icon and word everywhere (Observed, Calculated, Synthetic, ...). */
export const Kind = KindTag;

export type Strength = "weak" | "partial" | "solid";
const STRENGTH: Record<Strength, { label: string; Icon: typeof CircleCheck; className: string }> = {
  solid: { label: "Solid evidence", Icon: CircleCheck, className: "border-success/45 bg-success-soft text-success" },
  partial: { label: "Partial evidence", Icon: CircleDashed, className: "border-border-strong/60 bg-surface-muted text-ink-body" },
  weak: { label: "Weak evidence", Icon: TriangleAlert, className: "border-warning/50 bg-warning-soft text-warning" },
};

/** Evidence strength as a stamp: icon, word and tone, so it never rests on colour alone. */
export function StrengthStamp({ strength }: { strength: Strength }) {
  const { label, Icon, className } = STRENGTH[strength];
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-stamp border px-1.5 py-0.5 text-[11.5px] font-semibold", className)}>
      <Icon aria-hidden className="size-3.5" />
      {label}
    </span>
  );
}

/** A calm note for something that is not there, with the reason. Never an error colour: absence is a state, not a failure. */
export function Absent({ title, children, className }: { title: string; children?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-start gap-2.5 rounded-card border border-dashed border-border-strong/50 bg-surface-muted/50 px-4 py-3", className)}>
      <CircleDashed aria-hidden className="mt-0.5 size-4 shrink-0 text-ink-muted" />
      <div className="min-w-0 space-y-0.5 text-[13.5px]">
        <p className="font-medium text-ink-body">{title}</p>
        {children && <div className="text-ink-secondary">{children}</div>}
      </div>
    </div>
  );
}

/** Label and value as a ruled ledger column pair, for facts that are not claims. */
export function Fact({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0", className)}>
      <dt className="type-meta">{label}</dt>
      <dd className="type-ledger mt-0.5 text-[13.5px] text-ink-body">{children}</dd>
    </div>
  );
}
