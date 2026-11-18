"use client";

import { CircleAlert, CircleCheck, CircleDashed, Clock3 } from "lucide-react";
import { useState } from "react";

import { Tag } from "@/components/evidence/badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { SectionTitle } from "@/features/workspaces/parts";
import type { DataMode } from "@/lib/api/types";
import { formatDate, formatDateTime, formatRelative, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useDataHealth } from "./api";
import { Absent, Fact, formatCount, StrengthStamp } from "./parts";
import type { DataHealth, RegionCoverage, SourceHealth } from "./types";

const FRESHNESS: Record<SourceHealth["freshness"], { label: string; Icon: typeof CircleCheck; className: string; meaning: string }> = {
  fresh: { label: "Fresh", Icon: CircleCheck, className: "text-success", meaning: "Its claims are inside their expiry and have a source under two years old." },
  aging: { label: "Aging", Icon: Clock3, className: "text-warning", meaning: "Some claims are expired or rest on sources two years old or more." },
  expired: { label: "Expired, refresh due", Icon: CircleAlert, className: "text-danger", meaning: "At least half of its claims are past their stated expiry." },
  unknown: { label: "Unknown", Icon: CircleDashed, className: "text-ink-muted", meaning: "No claim is stored for this source, so freshness cannot be judged." },
};

const CACHE: Record<SourceHealth["cache_state"], string> = {
  fixture: "Demo fixtures only",
  stored_live: "Stored copies of live retrievals",
  mixed: "Fixtures and stored live copies",
  none: "Nothing stored",
};

/** A count that may not be logged: null is "not recorded", never zero. */
const logged = (n: number | null) => (n === null ? <span className="text-ink-muted">not recorded</span> : formatCount(n));

function SourceEntry({ s }: { s: SourceHealth }) {
  const f = FRESHNESS[s.freshness];
  return (
    <li className="space-y-3 px-4 py-3.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <h4 className="text-[14.5px] font-semibold text-ink">{humanize(s.source_type)}</h4>
        <span className={cn("inline-flex items-center gap-1 text-[12.5px] font-medium", f.className)} title={f.meaning}>
          <f.Icon aria-hidden className="size-3.5" />
          {f.label}
        </span>
        <Tag className="border-border bg-surface-muted text-ink-secondary" title="Where the stored copies came from">
          {CACHE[s.cache_state]}
        </Tag>
        <span className="type-meta ml-auto">
          {formatCount(s.sources)} {s.sources === 1 ? "source" : "sources"} · {formatCount(s.claims)} {s.claims === 1 ? "claim" : "claims"}
        </span>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-5">
        <Fact label="Last stored retrieval">
          {s.last_retrieved_at ? (
            <span title={formatDateTime(s.last_retrieved_at)}>{formatRelative(s.last_retrieved_at)}</span>
          ) : (
            <span className="text-ink-muted">none stored</span>
          )}
        </Fact>
        <Fact label="Fresh, aging, expired">
          {s.fresh_claims}, {s.aging_claims}, {s.expired_claims}
          {s.expired_claims > 0 && <span className="block text-[12.5px] text-warning">{s.expired_claims} past expiry</span>}
        </Fact>
        <Fact label="Retrieval attempts">
          {logged(s.attempts)}
          {s.last_attempt_at && <span className="block text-[12.5px] text-ink-muted">last {formatRelative(s.last_attempt_at)}</span>}
        </Fact>
        <Fact label="Errors">{logged(s.errors)}</Fact>
        <Fact label="Cooldown">
          <span className="text-ink-muted">not reported</span>
        </Fact>
      </dl>
      {s.last_error && (
        <p className="flex items-start gap-1.5 text-[13px] text-ink-body">
          <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-danger" />
          <span>
            Last error {s.last_error.code ? <span className="font-mono text-[12px]">{s.last_error.code}</span> : "(no code recorded)"} at {formatDateTime(s.last_error.at)}.
          </span>
        </p>
      )}
      {s.region_codes.length > 0 && <p className="text-[12.5px] text-ink-secondary">Regions with claims from this source: <span className="font-mono">{s.region_codes.join(", ")}</span></p>}
      {s.limitations.length > 0 && (
        <ul className="space-y-0.5 text-[12.5px] text-ink-muted">
          {s.limitations.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
    </li>
  );
}

function Coverage({ regions }: { regions: RegionCoverage[] }) {
  const [all, setAll] = useState(false);
  const withClaims = regions.filter((r) => r.claims > 0);
  const shown = all ? regions : withClaims;
  return (
    <section aria-labelledby="coverage" className="space-y-2.5">
      <SectionTitle id="coverage" meta={`${withClaims.length} of ${regions.length} regions have claims`}>
        Coverage by region
      </SectionTitle>
      {shown.length === 0 ? (
        <Absent title="No region has a stored claim yet">
          Thin or missing coverage is shown as it is, not filled in. Regions fill as Market Lens stores sourced claims.
        </Absent>
      ) : (
        <div className="overflow-x-auto rounded-card border border-border bg-surface">
          <table className="type-ledger w-full min-w-[56rem] text-left text-[13px]">
            <thead className="bg-surface-muted text-[11.5px] text-ink-muted">
              <tr>
                {["Region", "Evidence", "Claims (supported)", "Categories", "Sources", "Newest source", "Open conflicts", "Stale claims"].map((h) => (
                  <th key={h} scope="col" className="px-3 py-2 font-medium whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {shown.map((r) => (
                <tr key={r.region_code} className="align-top">
                  <td className="px-3 py-2">
                    <span className="font-medium text-ink">{r.region_name}</span>
                    <span className="block font-mono text-[11.5px] text-ink-muted">{r.region_code}</span>
                  </td>
                  <td className="px-3 py-2">
                    <StrengthStamp strength={r.strength} />
                    {r.strength_reasons.length > 0 && <span className="mt-1 block max-w-[28ch] text-[12px] text-ink-muted">{r.strength_reasons[0]}</span>}
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {r.claims} <span className="text-ink-muted">({r.supported_claims})</span>
                  </td>
                  <td className="px-3 py-2">
                    <span className="tabular-nums">
                      {r.categories_covered} of {r.categories_total}
                    </span>
                    {r.missing_categories.length > 0 && (
                      <span className="mt-0.5 block max-w-[30ch] text-[12px] text-ink-muted">Missing: {r.missing_categories.map((c) => humanize(c).toLowerCase()).join(", ")}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {r.sources}
                    {r.source_types.length > 0 && <span className="mt-0.5 block text-[12px] text-ink-muted">{r.source_types.map(humanize).join(", ")}</span>}
                  </td>
                  <td className="px-3 py-2 text-ink-secondary">{r.newest_source_date ? formatDate(r.newest_source_date) : "no dated source"}</td>
                  <td className="px-3 py-2 tabular-nums">{r.open_conflicts}</td>
                  <td className="px-3 py-2 tabular-nums">{r.stale_claims}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {regions.length > withClaims.length && (
        <button type="button" onClick={() => setAll((a) => !a)} aria-pressed={all} className="rounded-sm text-[13px] font-medium text-rose underline-offset-2 hover:underline">
          {all ? "Show only regions with claims" : `Also list the ${regions.length - withClaims.length} regions with no claims`}
        </button>
      )}
    </section>
  );
}

function Body({ health }: { health: DataHealth }) {
  return (
    <div className="space-y-6">
      <section aria-labelledby="sources" className="space-y-2.5">
        <SectionTitle id="sources">Sources</SectionTitle>
        {health.sources.length === 0 ? (
          <Absent title="No source has stored anything yet">Sources appear here once claims with their sources are stored for this workspace.</Absent>
        ) : (
          <ul className="ledger-rules rounded-card border border-border bg-surface">
            {health.sources.map((s) => (
              <SourceEntry key={s.source_type} s={s} />
            ))}
          </ul>
        )}
        <p className="max-w-[72ch] text-[12.5px] text-ink-muted">
          Cooldowns (waits after a rate limit) are not reported by this build, and attempts and errors exist only for sources with a call log. Both are shown as not recorded, never as zero.
        </p>
      </section>

      <Coverage regions={health.regions} />

      <section aria-labelledby="rules" className="space-y-2">
        <SectionTitle id="rules">How to read this</SectionTitle>
        <ul className="max-w-[72ch] list-disc space-y-1 pl-5 text-[13px] text-ink-secondary marker:text-ink-muted">
          {health.limitations.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
          <li>
            A source counts as expired when at least {Math.round(health.rules.expired_share_for_expired * 100)}% of its claims are past their expiry; two years is the age at which an observed source starts to count as aging.
          </li>
          {health.rules.notes.map((n, i) => (
            <li key={`n${i}`}>{n}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}

/** Per source: freshness, attempts, errors and cooldown; per region: coverage. Reads stored copies, never calls a source. */
export function DataHealthPanel({ workspaceId, mode }: { workspaceId: string | null; mode: DataMode }) {
  const health = useDataHealth(workspaceId, mode);
  if (!workspaceId) {
    return <Absent title="No workspace for this brand">Data Health reads the workspace&apos;s stored claims, and this brand has no workspace yet.</Absent>;
  }
  if (health.isPending) return <LoadingState label="Reading stored sources…" />;
  if (health.error) return <ErrorState error={health.error} onRetry={() => void health.refetch()} />;
  return (
    <div className="space-y-4">
      {health.data.sources.every((s) => s.claims === 0) && health.data.regions.every((r) => r.claims === 0) ? (
        <EmptyState
          title="Nothing is stored to check yet"
          description="Data Health compares stored claims and their sources against their expiry and against each region's coverage. It never calls a source, so it cannot say a source is reachable. Until claims are stored, every source is unknown and every region is thin."
          needs={[
            { label: "Claims with sources stored for a region (Market Lens)", met: false },
            { label: "Retrieval call logs for the sources that keep one", met: health.data.sources.some((s) => s.attempts_logged) },
          ]}
        />
      ) : null}
      <Body health={health.data} />
    </div>
  );
}
