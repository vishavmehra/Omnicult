"use client";

import { ChevronRight } from "lucide-react";
import { useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { EvidenceRow, type ClaimKind } from "@/components/evidence/evidence-row";
import { ApiError } from "@/lib/api/errors";

import { useClaim } from "./api";
import type { ClaimView } from "./types";

function sourceOf(claim: ClaimView) {
  const first = claim.sources[0];
  if (!first) return null;
  const label = first.title ?? first.publisher ?? first.source_identifier;
  return { label: claim.sources.length > 1 ? `${label} and ${claim.sources.length - 1} more` : label, url: first.url, identifier: first.source_identifier };
}

/** One claim as an Evidence Row (claim, source, date, kind, scope, confidence), then why the confidence is what it is. */
export function ClaimEvidence({ workspaceId, claimId }: { workspaceId: string | null; claimId: string }) {
  const claim = useClaim(workspaceId, claimId);
  if (!workspaceId) return <p className="text-[12.5px] text-ink-muted">This brand has no workspace, so the claim cannot be opened. Claim id <span className="font-mono">{claimId}</span>.</p>;
  if (claim.isPending) return <Skeleton className="h-24 w-full rounded-card" />;
  if (claim.isError) {
    const gone = claim.error instanceof ApiError && claim.error.status === 404;
    return (
      <p role="alert" className="rounded-md border border-dashed border-border-strong/50 px-3 py-2 text-[12.5px] text-ink-secondary">
        {gone ? "This claim is no longer available to this workspace." : "The claim could not be loaded."} <span className="font-mono">{claimId.slice(0, 8)}</span>
      </p>
    );
  }
  const c = claim.data;
  return (
    <div className="space-y-1">
      <EvidenceRow
        claim={c.value_text}
        source={sourceOf(c)}
        published={c.published_at}
        retrieved={c.retrieved_at}
        kind={c.kind as ClaimKind}
        scope={{ region: c.scope.region_code, language: c.scope.language, cityTier: c.scope.city_tier, period: c.scope.period }}
        confidence={c.effective_confidence}
        conflict={c.conflict_ids.length > 0}
        stale={c.stale}
      />
      <p className="px-1 text-[12px] text-ink-muted">{c.confidence_reason}</p>
    </div>
  );
}

/**
 * The claims a result cites, opened in place on demand (nothing is fetched until the disclosure is opened). With no claims
 * it says so: a change that cites nothing is shown as unsupported, never as quietly fine.
 */
export function ClaimsDisclosure({ workspaceId, claimIds, noun = "claim" }: { workspaceId: string | null; claimIds: string[]; noun?: string }) {
  const [open, setOpen] = useState(false);
  if (claimIds.length === 0) return <p className="text-[12.5px] text-ink-muted">Cites no {noun}s. Treat this as unsupported by evidence.</p>;
  return (
    <details onToggle={(e) => setOpen(e.currentTarget.open)} className="group text-[13px]">
      <summary className="inline-flex cursor-pointer items-center gap-1.5 rounded-md py-0.5 font-medium text-ink-body select-none hover:text-ink">
        <ChevronRight aria-hidden className="size-3.5 transition-transform group-open:rotate-90" />
        Evidence: {claimIds.length} {noun}
        {claimIds.length === 1 ? "" : "s"} cited
      </summary>
      {open && (
        <div className="mt-2 space-y-2.5">
          {claimIds.map((id) => (
            <ClaimEvidence key={id} workspaceId={workspaceId} claimId={id} />
          ))}
        </div>
      )}
    </details>
  );
}
