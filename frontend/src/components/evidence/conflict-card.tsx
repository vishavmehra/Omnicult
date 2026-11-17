"use client";

import { Check, ExternalLink, GitCompareArrows, Repeat2, UserRoundSearch } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

export type ConflictSide = {
  value: ReactNode;
  source: string;
  url?: string | null;
  date?: string | null;
  scope: string;
};

function Side({ id, side, recommended }: { id: "A" | "B"; side: ConflictSide; recommended: boolean }) {
  return (
    <div className={cn("min-w-0 space-y-2 px-4 py-3", recommended && "bg-plum/40")}>
      <div className="flex items-center justify-between gap-2">
        <span className="type-meta">Value {id}</span>
        {recommended && (
          <span className="inline-flex items-center gap-1 rounded-stamp border border-double border-pop/70 px-1.5 py-px text-[11px] font-semibold tracking-wide text-pop uppercase">
            <Check aria-hidden className="size-3" />
            Recommended
          </span>
        )}
      </div>
      <p className="text-[17px] leading-snug font-medium text-ink">{side.value}</p>
      <dl className="type-ledger grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-[12.5px]">
        <dt className="text-ink-muted">Source</dt>
        <dd className="truncate text-ink-body">
          {side.url ? (
            <a href={side.url} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 text-rose hover:underline">
              <span className="truncate">{side.source}</span>
              <ExternalLink aria-hidden className="size-3 shrink-0" />
              <span className="sr-only">(opens in a new tab)</span>
            </a>
          ) : (
            side.source
          )}
        </dd>
        <dt className="text-ink-muted">Date</dt>
        <dd className="text-ink-body">{side.date ? formatDate(side.date) : "Undated"}</dd>
        <dt className="text-ink-muted">Scope</dt>
        <dd className="text-ink-body">{side.scope}</dd>
      </dl>
    </div>
  );
}

/**
 * Two sources disagree about the same subject, attribute and scope. Both values stay visible, the rejected one included.
 * Resolution controls render only for the handlers passed in, so a card never shows a button that does nothing.
 */
export function ConflictCard({
  subject,
  a,
  b,
  recommended,
  reason,
  resolved,
  onAccept,
  onSwitch,
  onRequestReview,
  pending,
}: {
  subject: ReactNode;
  a: ConflictSide;
  b: ConflictSide;
  /** Which value the rules recommend, or null when they cannot choose. */
  recommended: "a" | "b" | null;
  reason: ReactNode;
  /** Set when a person already resolved it: the chosen side and who/when, in words. */
  resolved?: ReactNode;
  onAccept?: () => void;
  onSwitch?: () => void;
  onRequestReview?: () => void;
  pending?: boolean;
}) {
  return (
    <section className="overflow-hidden rounded-card border border-warning/45 bg-surface">
      <header className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
        <GitCompareArrows aria-hidden className="size-4 text-warning" />
        <h3 className="text-[14px] font-semibold text-ink">{subject}</h3>
        <span className="ml-auto text-[12px] font-medium text-warning">{resolved ? "Resolved" : "Open conflict"}</span>
      </header>
      <div className="grid divide-y divide-border sm:grid-cols-2 sm:divide-x sm:divide-y-0">
        <Side id="A" side={a} recommended={recommended === "a"} />
        <Side id="B" side={b} recommended={recommended === "b"} />
      </div>
      <div className="space-y-3 border-t border-border px-4 py-3">
        <p className="text-[13px] text-ink-body">
          <span className="font-medium text-ink">{recommended ? "Why this value: " : "No recommendation: "}</span>
          {reason}
        </p>
        {resolved && <p className="text-[13px] text-ink-secondary">{resolved}</p>}
        {!resolved && (onAccept || onSwitch || onRequestReview) && (
          <div className="flex flex-wrap gap-2">
            {onAccept && recommended && (
              <Button size="sm" onClick={onAccept} disabled={pending}>
                <Check aria-hidden />
                Accept value {recommended.toUpperCase()}
              </Button>
            )}
            {onSwitch && recommended && (
              <Button size="sm" variant="outline" onClick={onSwitch} disabled={pending}>
                <Repeat2 aria-hidden />
                Use value {recommended === "a" ? "B" : "A"} instead
              </Button>
            )}
            {onRequestReview && (
              <Button size="sm" variant="ghost" onClick={onRequestReview} disabled={pending}>
                <UserRoundSearch aria-hidden />
                Request review
              </Button>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
