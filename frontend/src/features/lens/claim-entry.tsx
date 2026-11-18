"use client";

import { ChevronRight, ExternalLink } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { CONFIDENCE } from "@/components/evidence/confidence";
import { EvidenceRow, type EvidenceScope } from "@/components/evidence/evidence-row";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

import type { ClaimView } from "./api";

type Source = ClaimView["sources"][number];

const SOURCE_TYPE: Record<string, string> = {
  census_2011: "Census of India 2011",
  holidays_package: "python-holidays",
  curated_reference: "Curated reference",
  wikipedia: "Wikipedia",
  wikidata: "Wikidata",
  wikipedia_pageviews: "Wikipedia pageviews",
  gemini_grounding: "Gemini grounded research",
};

export const sourceTypeLabel = (type: string) => SOURCE_TYPE[type] ?? type;

export function sourceName(s: Source) {
  return s.title ?? s.publisher ?? s.source_identifier;
}

export function scopeOf(c: ClaimView): EvidenceScope {
  return { region: c.scope.region_code, language: c.scope.language, cityTier: c.scope.city_tier, period: c.scope.period };
}

/** The same scope as one line, for conflict sides and drawers. */
export function scopeText(c: ClaimView) {
  const parts = [c.scope.region_code, c.scope.language, c.scope.city_tier, c.scope.period].filter(Boolean);
  return parts.length ? parts.join(" · ") : "Country-wide";
}

/** What a value is, as a person reads it: a name, a topic or the plain value. */
export function valueText(c: ClaimView) {
  const v = c.value;
  if (typeof v === "string" || typeof v === "number") return String(v);
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    return String(o.name ?? o.topic ?? o.date ?? c.value_text);
  }
  return c.value_text;
}

/** The source cell shows the newest source and says how many more stand behind the claim. */
function primarySource(c: ClaimView) {
  const first = c.sources[0];
  if (!first) return null;
  const extra = c.sources.length - 1;
  return { label: extra > 0 ? `${sourceName(first)} (+${extra} more)` : sourceName(first), url: first.url, identifier: first.source_identifier };
}

/** Sources, dates and the confidence rule behind a claim, one disclosure under its row. */
function ClaimBasis({ claim }: { claim: ClaimView }) {
  const lowered = claim.effective_confidence !== claim.confidence;
  return (
    <div className="space-y-3 px-3.5 py-3 text-[13px]">
      <p className="text-ink-body">
        <span className="font-medium text-ink">Why {CONFIDENCE[claim.effective_confidence].label}: </span>
        {claim.confidence_reason}
        {lowered && " Lowered one level while a conflict on this claim is open."}
      </p>
      {claim.sources.length === 0 ? (
        <p className="text-ink-secondary">No source is attached, so this stays an unsupported statement.</p>
      ) : (
        <ul className="ledger-rules rounded-lg border border-border">
          {claim.sources.map((s) => (
            <li key={s.id} className="space-y-1 px-3 py-2">
              <p className="flex flex-wrap items-baseline gap-x-2">
                {s.url ? (
                  <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-rose underline-offset-2 hover:underline">
                    {sourceName(s)}
                    <ExternalLink aria-hidden className="size-3" />
                    <span className="sr-only">(opens the original source in a new tab)</span>
                  </a>
                ) : (
                  <span className="font-medium text-ink">{sourceName(s)}</span>
                )}
                <span className="type-meta">{sourceTypeLabel(s.source_type)}</span>
              </p>
              <p className="type-meta">
                {s.publisher ? `${s.publisher} · ` : ""}
                {s.published_at ? `Published ${formatDate(s.published_at)} · ` : ""}Retrieved {formatDate(s.retrieved_at)} · Independence group <span className="font-mono">{s.independence_group}</span>
              </p>
              {s.excerpt && <blockquote className="border-l border-border-strong pl-3 text-[13px] leading-snug text-ink-body">{s.excerpt}</blockquote>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * A claim as a ledger entry: the statement, its five tags, and a disclosure with every source, its dates and the rule
 * behind the confidence label. `statement` replaces the claim's own text when a view has a better headline for it.
 */
export function ClaimEntry({ claim, statement, className }: { claim: ClaimView; statement?: ReactNode; className?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const n = claim.sources.length;
  return (
    <div className={className}>
      <EvidenceRow
        claim={statement ?? claim.value_text}
        source={primarySource(claim)}
        published={claim.sources[0]?.published_at ?? claim.published_at}
        retrieved={claim.retrieved_at}
        kind={claim.kind}
        scope={scopeOf(claim)}
        confidence={claim.effective_confidence}
        conflict={claim.conflict_ids.length > 0}
        stale={claim.stale}
      />
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={id}
        className="mt-1 inline-flex h-7 items-center gap-1 rounded-md px-1.5 text-[12.5px] text-ink-secondary hover:bg-surface-muted hover:text-ink"
      >
        <ChevronRight aria-hidden className={cn("size-3.5 transition-transform motion-reduce:transition-none", open && "rotate-90")} />
        {n === 0 ? "Why this has no source" : `${n} ${n === 1 ? "source" : "sources"} and the confidence rule`}
      </button>
      {open && (
        <div id={id} className="mt-1 rounded-card border border-border bg-surface">
          <ClaimBasis claim={claim} />
        </div>
      )}
    </div>
  );
}

export { ClaimBasis };
