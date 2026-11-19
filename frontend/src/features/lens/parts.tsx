"use client";

import { CircleDashed, SignalHigh, SignalLow, SignalMedium, type LucideIcon } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

import { LimitationList } from "@/components/evidence/limitation-list";
import { formatDate, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { sourceTypeLabel } from "./claim-entry";
import type { LensSourceSummary } from "./api";

export type Strength = "none" | "weak" | "partial" | "solid";

export const STRENGTH: Record<Strength, { label: string; Icon: LucideIcon; meaning: string; cells: number }> = {
  none: { label: "No claims", Icon: CircleDashed, meaning: "Nothing is recorded for this state in this mode yet.", cells: 0 },
  weak: { label: "Weak", Icon: SignalLow, meaning: "Little is recorded, or no claim reaches Moderate confidence.", cells: 1 },
  partial: { label: "Partial", Icon: SignalMedium, meaning: "Enough supported claims to use, with named gaps.", cells: 2 },
  solid: { label: "Solid", Icon: SignalHigh, meaning: "Broad, fresh and mostly Moderate or better, with no open conflict.", cells: 3 },
};

/** Evidence Meter strength, with "none" when the state has no claim at all (the API rates that weak). */
export function strengthOf(strength: "weak" | "partial" | "solid", claims: number): Strength {
  return claims === 0 ? "none" : strength;
}

/** Strength as an icon and a word. The word carries it; the icon and the filled cells only reinforce. */
export function StrengthTag({ strength, className }: { strength: Strength; className?: string }) {
  const { label, Icon, meaning } = STRENGTH[strength];
  return (
    <span className={cn("inline-flex items-center gap-1 text-[12.5px] font-medium text-ink", className)} title={meaning}>
      <Icon aria-hidden className="size-3.5 shrink-0" />
      {label}
    </span>
  );
}

/** What a view rests on: each source family, its newest dates and its limits. Every Lens view ends with this. */
export function SourcesPanel({ sources, limitations }: { sources: LensSourceSummary[]; limitations: string[]; modeLabel?: string }) {
  return (
    <section aria-labelledby="lens-sources" className="space-y-3">
      <h2 id="lens-sources" className="text-[15px] font-semibold text-ink">
        Sources and their dates
      </h2>
      {sources.length === 0 ? (
        <p className="text-[13.5px] text-ink-secondary">No source is behind this view yet: it is empty until a state is built.</p>
      ) : (
        <ul className="ledger-rules rounded-card border border-border bg-surface">
          {sources.map((s) => (
            <li key={s.source_type} className="grid gap-x-6 gap-y-1 px-4 py-3 sm:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
              <div className="min-w-0 space-y-0.5">
                <p className="text-[14px] font-medium text-ink">{s.label || sourceTypeLabel(s.source_type)}</p>
                <p className="text-[13px] text-ink-secondary">{s.description}</p>
              </div>
              <div className="min-w-0 space-y-1 text-[12.5px] text-ink-body">
                <p className="type-ledger">
                  {s.claims} {s.claims === 1 ? "claim" : "claims"} from {s.sources} {s.sources === 1 ? "source" : "sources"}
                </p>
                <p className="type-ledger text-ink-secondary">
                  {s.newest_published_at ? `Newest published ${formatDate(s.newest_published_at)}. ` : "No publication date. "}
                  {s.newest_retrieved_at ? `Retrieved ${formatDateTime(s.newest_retrieved_at)}.` : ""}
                </p>
                {s.limitations.length > 0 && (
                  <ul className="list-disc space-y-0.5 pl-4 text-ink-secondary">
                    {s.limitations.map((l) => (
                      <li key={l}>{l}</li>
                    ))}
                  </ul>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      <LimitationList items={limitations} />
    </section>
  );
}

/** A native select in the app's input style: platform keyboard, platform picker on phones. */
export function NativeSelect({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      {...props}
      className={cn(
        "clay-well h-8 min-w-0 rounded-lg border border-border-strong/55 bg-surface-muted px-2.5 text-[13.5px] text-ink focus-visible:border-pop disabled:opacity-50",
        className,
      )}
    />
  );
}

export function Labelled({ label, htmlFor, children, className }: { label: string; htmlFor: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <label htmlFor={htmlFor} className="type-meta">
        {label}
      </label>
      {children}
    </div>
  );
}

export const nf = new Intl.NumberFormat("en");
