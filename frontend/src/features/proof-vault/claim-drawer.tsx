"use client";

import { Check, Copy, ExternalLink } from "lucide-react";
import { useState, type ReactNode } from "react";

import { ConfidenceIndicator } from "@/components/evidence/confidence";
import { ConflictCard, type ConflictSide } from "@/components/evidence/conflict-card";
import { KIND } from "@/components/evidence/evidence-row";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import type { DataMode } from "@/lib/api/types";
import { formatDate, formatDateTime, humanize } from "@/lib/format";

import { useClaim, useRegionConflicts } from "./api";
import { Fact, Kind, scopeOf, sourceLabel } from "./parts";
import type { ClaimView, Conflict } from "./types";

const scopeText = (claim: ClaimView) => {
  const s = scopeOf(claim.scope);
  return [s.region, s.language, s.cityTier, s.period].filter(Boolean).join(" · ") || "Country-wide";
};

function sideOf(claim: ClaimView, thisId: string, onOpen: (id: string) => void): ConflictSide {
  const first = sourceLabel(claim);
  const mine = claim.id === thisId;
  return {
    value: (
      <span lang={claim.scope.language ?? undefined}>
        {mine && <span className="type-meta mb-0.5 block">This claim</span>}
        {mine ? (
          claim.value_text
        ) : (
          <button type="button" onClick={() => onOpen(claim.id)} className="rounded-sm text-left underline-offset-2 hover:underline">
            {claim.value_text}
          </button>
        )}
      </span>
    ),
    source: first?.label ?? "No source",
    url: first?.url,
    date: claim.published_at ?? claim.retrieved_at,
    scope: scopeText(claim),
  };
}

function ConflictOf({ conflict, thisId, onOpen }: { conflict: Conflict; thisId: string; onOpen: (id: string) => void }) {
  const resolved = conflict.status === "resolved";
  return (
    <ConflictCard
      subject={conflict.reason}
      a={sideOf(conflict.claim_a, thisId, onOpen)}
      b={sideOf(conflict.claim_b, thisId, onOpen)}
      recommended={conflict.current_selection}
      reason={
        <>
          {conflict.selection_reason}
          {conflict.status === "review_requested" && " A native review has been requested."}
        </>
      }
      resolved={
        resolved || conflict.resolutions.length > 0 ? (
          <>
            {conflict.resolutions.map((d) => (
              <span key={d.id} className="block">
                {formatDateTime(d.decided_at)}: {d.decision === "accept" ? "kept" : d.decision === "switch" ? "switched to" : "asked for a review, using"} value {d.selection_after.toUpperCase()}
                {d.note ? `. ${d.note}` : "."}
              </span>
            ))}
          </>
        ) : undefined
      }
    />
  );
}

function Section({ title, meta, children }: { title: string; meta?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[14px] font-semibold text-ink">{title}</h3>
        {meta && <span className="type-meta">{meta}</span>}
      </div>
      {children}
    </section>
  );
}

function Detail({ workspaceId, mode, claimId, onOpen }: { workspaceId: string; mode: DataMode; claimId: string; onOpen: (id: string) => void }) {
  const claim = useClaim(workspaceId, claimId);
  const region = claim.data?.scope.region_code;
  const conflicts = useRegionConflicts(workspaceId, region, mode);
  const [copied, setCopied] = useState(false);

  if (claim.isPending) return <LoadingState label="Loading the claim…" />;
  if (claim.error) return <ErrorState error={claim.error} onRetry={() => void claim.refetch()} />;
  const c = claim.data;
  const involved = (conflicts.data?.items ?? []).filter((x) => x.claim_a.id === claimId || x.claim_b.id === claimId);
  const groups = new Set(c.sources.map((s) => s.independence_group)).size;
  const lowered = c.effective_confidence !== c.confidence;

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="space-y-6 px-4 pb-6">
      <p lang={c.scope.language ?? undefined} className="text-[17px] leading-snug font-medium text-ink">
        {c.value_text}
      </p>

      <dl className="type-ledger ledger-rules rounded-card border border-border bg-surface [&>div]:grid [&>div]:gap-x-4 [&>div]:px-3.5 [&>div]:py-2.5 sm:[&>div]:grid-cols-[8rem_minmax(0,1fr)]">
        <Fact label="Kind">
          <Kind kind={c.kind} />
          <span className="mt-0.5 block text-[12.5px] text-ink-muted">{KIND[c.kind].meaning}</span>
        </Fact>
        <Fact label="Confidence">
          <ConfidenceIndicator level={c.effective_confidence} />
          <span className="mt-0.5 block max-w-[56ch] text-[12.5px] text-ink-muted">{c.confidence_reason}</span>
          {lowered && (
            <span className="mt-0.5 block text-[12.5px] text-warning">Shown one level below its computed {humanize(c.confidence)} while an open conflict stands.</span>
          )}
        </Fact>
        <Fact label="Scope">{scopeText(c)}</Fact>
        <Fact label="Dates">
          {c.published_at ? `Published ${formatDate(c.published_at)}` : "Publication date not stated"}
          <span className="block text-[12.5px] text-ink-muted">
            Retrieved {formatDateTime(c.retrieved_at)}
            {c.expires_at && ` · expires ${formatDate(c.expires_at)}`}
          </span>
        </Fact>
        <Fact label="State">
          {humanize(c.status)}
          {c.stale && <span className="block text-[12.5px] text-warning">Stale: no observed source under two years old, or past its expiry.</span>}
          <span className="block text-[12.5px] text-ink-muted">{c.shared ? "Shared reference claim" : "Owned by this workspace"} · {humanize(c.category)}</span>
        </Fact>
      </dl>

      <Section title="Sources" meta={`${c.sources.length} ${c.sources.length === 1 ? "source" : "sources"}, ${groups} independent ${groups === 1 ? "group" : "groups"}`}>
        {c.sources.length === 0 ? (
          <p className="text-[13.5px] text-ink-secondary">
            No source is attached. A {c.kind} claim stands without a source and should not be relied on as an observation.
          </p>
        ) : (
          <ul className="ledger-rules rounded-card border border-border bg-surface">
            {c.sources.map((s) => (
              <li key={s.id} className="receipt-corner space-y-1 px-3.5 py-3">
                <p className="text-[13.5px] font-medium text-ink">
                  {s.url ? (
                    <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 text-rose underline-offset-2 hover:underline">
                      <span>{s.title ?? s.publisher ?? humanize(s.source_type)}</span>
                      <ExternalLink aria-hidden className="size-3 shrink-0" />
                      <span className="sr-only">(opens the original source in a new tab)</span>
                    </a>
                  ) : (
                    (s.title ?? s.publisher ?? humanize(s.source_type))
                  )}
                </p>
                <p className="type-ledger text-[12.5px] text-ink-muted">
                  {humanize(s.source_type)}
                  {s.publisher && s.title && s.publisher.toLowerCase() !== humanize(s.source_type).toLowerCase() && ` · ${s.publisher}`} · group <span className="font-mono">{s.independence_group}</span>
                </p>
                <p className="type-ledger text-[12.5px] text-ink-muted">
                  {s.published_at ? `Published ${formatDate(s.published_at)}` : "Undated"} · retrieved {formatDate(s.retrieved_at)}
                </p>
                {s.excerpt && <blockquote className="max-w-[60ch] border-l border-border-strong/60 pl-3 text-[13px] text-ink-body">{s.excerpt}</blockquote>}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Conflicts" meta={involved.length ? `${involved.length} involving this claim` : undefined}>
        {!region ? (
          <p className="text-[13.5px] text-ink-secondary">Conflicts are stored per region, and this claim has no region, so none can be looked up.</p>
        ) : conflicts.isPending ? (
          <LoadingState label="Looking for conflicts…" className="py-2" />
        ) : conflicts.error ? (
          <ErrorState error={conflicts.error} onRetry={() => void conflicts.refetch()} />
        ) : involved.length === 0 ? (
          <p className="text-[13.5px] text-ink-secondary">No stored conflict involves this claim.</p>
        ) : (
          <div className="space-y-4">
            {involved.map((x) => (
              <ConflictOf key={x.id} conflict={x} thisId={claimId} onOpen={onOpen} />
            ))}
          </div>
        )}
      </Section>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
        <span className="font-mono text-[11px] break-all text-ink-muted">{c.id}</span>
        <Button variant="outline" size="sm" onClick={() => void copyLink()}>
          {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
          {copied ? "Link copied" : "Copy link to this claim"}
        </Button>
      </div>
    </div>
  );
}

/** One claim with its five tags, every source and every conflict it is part of. Open state lives in the URL (?claim=). */
export function ClaimDrawer({
  workspaceId,
  mode,
  claimId,
  onOpenClaim,
  onClose,
}: {
  workspaceId: string | null;
  mode: DataMode;
  claimId: string | null;
  onOpenClaim: (claimId: string) => void;
  onClose: () => void;
}) {
  return (
    <Sheet open={Boolean(claimId)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="gap-0 overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-[34rem]">
        <SheetHeader className="pr-12">
          <SheetTitle className="text-[15px] font-semibold">Claim detail</SheetTitle>
          <SheetDescription>Its five tags, where it came from, and any conflict it is part of.</SheetDescription>
        </SheetHeader>
        {claimId && workspaceId ? (
          <Detail key={claimId} workspaceId={workspaceId} mode={mode} claimId={claimId} onOpen={onOpenClaim} />
        ) : claimId ? (
          <p className="px-4 text-[13.5px] text-ink-secondary">This brand has no workspace, so claims cannot be read.</p>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
