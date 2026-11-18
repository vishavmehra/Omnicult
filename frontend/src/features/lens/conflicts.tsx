"use client";

import { CircleAlert } from "lucide-react";

import { ConflictCard, type ConflictSide } from "@/components/evidence/conflict-card";
import { ApiError } from "@/lib/api/errors";
import { formatDate, humanize } from "@/lib/format";

import { useResolveConflict, type ClaimView, type Conflict } from "./api";
import { scopeText, sourceName, valueText } from "./claim-entry";

function side(c: ClaimView): ConflictSide {
  const first = c.sources[0];
  const more = c.sources.length - 1;
  return {
    value: valueText(c),
    source: first ? `${sourceName(first)}${more > 0 ? ` (+${more} more)` : ""}` : "No source",
    url: first?.url,
    date: first?.published_at ?? c.published_at ?? c.retrieved_at,
    scope: scopeText(c),
  };
}

function title(conflict: Conflict) {
  const a = conflict.claim_a;
  const subject = a.subject.includes(":") ? a.subject.split(":")[1] : a.subject;
  return `${humanize(subject)}: ${humanize(a.attribute).toLowerCase()}`;
}

function resolvedText(conflict: Conflict) {
  const last = conflict.resolutions[conflict.resolutions.length - 1];
  if (conflict.status !== "resolved" || !last) return undefined;
  const verb = last.decision === "switch" ? "switched to the other value" : "accepted the value in use";
  return `A reviewer ${verb} on ${formatDate(last.decided_at)}. Value ${conflict.current_selection.toUpperCase()} is used; the other is kept.`;
}

/**
 * Conflicts as the evidence components show them: both values with their sources, dates and scope, the rule that picks the
 * one in use, and the resolution controls. Resolving needs the owner, editor or reviewer role: the API refuses anyone else
 * and the refusal is shown here in words.
 */
export function ConflictList({ conflicts, campaignId, workspaceId }: { conflicts: Conflict[]; campaignId: string; workspaceId: string }) {
  const resolve = useResolveConflict(campaignId, workspaceId);
  const error = resolve.error instanceof ApiError ? resolve.error : null;
  if (conflicts.length === 0) return null;
  const act = (conflictId: string, decision: "accept" | "switch" | "request_review") => resolve.mutate({ conflictId, decision });
  return (
    <div className="space-y-3">
      {conflicts.map((c) => {
        const open = c.status === "open";
        return (
          <ConflictCard
            key={c.id}
            subject={title(c)}
            a={side(c.claim_a)}
            b={side(c.claim_b)}
            recommended={c.current_selection}
            reason={
              <>
                {c.selection_reason} {c.reason}
                {c.status === "review_requested" && " A native review has been requested."}
              </>
            }
            resolved={resolvedText(c)}
            onAccept={open || c.status === "review_requested" ? () => act(c.id, "accept") : undefined}
            onSwitch={open || c.status === "review_requested" ? () => act(c.id, "switch") : undefined}
            onRequestReview={open ? () => act(c.id, "request_review") : undefined}
            pending={resolve.isPending}
          />
        );
      })}
      {error && (
        <p role="alert" className="flex items-start gap-2 text-[13px] text-ink">
          <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />
          {error.code === "FORBIDDEN" ? "Your role in this workspace cannot resolve conflicts. Ask an owner, editor or reviewer." : error.message}
        </p>
      )}
    </div>
  );
}
