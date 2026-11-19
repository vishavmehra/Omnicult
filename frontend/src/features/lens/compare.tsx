"use client";

import { GitCompareArrows, X } from "lucide-react";
import { useState } from "react";

import { ConfidenceIndicator } from "@/components/evidence/confidence";
import { KindTag } from "@/components/evidence/evidence-row";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { SectionTitle } from "@/features/workspaces/parts";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useAtlas, useClaim, useCompare, type LensCompare, type LensCompareItem } from "./api";
import { ClaimEntry } from "./claim-entry";
import { categoryLabel, dayLabel } from "./format";
import { DataSources, SourcesPanel, StrengthTag, nf, strengthOf } from "./parts";
import { formatFact, type FactUnit } from "./state-facts-logic";
import { StateSelect } from "./state-select";

/**
 * Published figures side by side: one row per figure any compared state has, each cell with its own period. The bar is the
 * value against the largest value in the row; "Highest" names the largest number, which is not always the better one.
 */
function DataTable({ data }: { data: LensCompare }) {
  const cols = data.regions.length;
  const grid = { gridTemplateColumns: `minmax(9rem, 15rem) repeat(${cols}, minmax(11rem, 1fr))` };
  const lead = (label: string, meta?: string) => (
    <div role="rowheader" className="sticky left-0 z-10 bg-surface px-3 py-2.5">
      <p className="text-[13px] font-medium text-ink">{label}</p>
      {meta && <p className="type-meta">{meta}</p>}
    </div>
  );
  return (
    <div className="overflow-x-auto rounded-card border border-border bg-surface" role="region" aria-label="Published figures, side by side" tabIndex={0}>
      <div role="table" className="min-w-max">
        <div role="row" className="grid border-b border-border bg-surface-muted/60" style={grid}>
          <div role="columnheader" className="type-meta sticky left-0 z-10 bg-surface-muted px-3 py-2.5">
            Figure
          </div>
          {data.regions.map((r) => (
            <div key={r.region.code} role="columnheader" className="border-l border-border px-3 py-2.5">
              <p className="type-title text-[19px] text-ink">{r.region.name}</p>
            </div>
          ))}
        </div>
        <div role="row" className="grid border-b border-border" style={grid}>
          {lead("Mother tongues", "Census 2011, or the official languages")}
          {data.regions.map((r) => (
            <div key={r.region.code} role="cell" className="space-y-0.5 border-l border-border px-3 py-2.5 text-[13px] text-ink-body">
              {r.data.languages.slice(0, 2).map((l) => (
                <p key={`${l.code}-${l.name}`}>
                  {l.name}
                  {l.share !== null && <span className="type-ledger text-ink-secondary"> {l.share}%</span>}
                </p>
              ))}
            </div>
          ))}
        </div>
        <div role="row" className="grid border-b border-border" style={grid}>
          {lead("Top searches", "Newest week, where the state scores highest")}
          {data.regions.map((r) => (
            <div key={r.region.code} role="cell" className="space-y-0.5 border-l border-border px-3 py-2.5 text-[13px] text-ink-body">
              {r.data.searches.length === 0 ? (
                <p className="text-ink-muted">No search data</p>
              ) : (
                r.data.searches.slice(0, 2).map((t) => (
                  <p key={t.term}>
                    {t.term} <span className="type-ledger text-ink-secondary">{t.score}</span>
                  </p>
                ))
              )}
            </div>
          ))}
        </div>
        <div role="row" className="grid border-b border-border" style={grid}>
          {lead("Public holidays", data.regions[0] ? `On each state's ${data.regions[0].data.holidays_year} list` : undefined)}
          {data.regions.map((r) => (
            <div key={r.region.code} role="cell" className="space-y-0.5 border-l border-border px-3 py-2.5 text-[13px] text-ink-body">
              <p className="type-ledger text-ink">{r.data.holidays}</p>
              {r.data.next_holidays[0] && (
                <p className="text-ink-secondary">
                  Next: {r.data.next_holidays[0].name}, {dayLabel(r.data.next_holidays[0].date)}
                </p>
              )}
            </div>
          ))}
        </div>
        {data.data_rows.map((row) => {
          const top = Math.max(...row.cells.map((c) => c.value ?? 0));
          return (
            <div key={row.key} role="row" className="grid border-b border-border last:border-b-0" style={grid}>
              {lead(row.label)}
              {row.cells.map((cell) => (
                <div key={cell.region_code} role="cell" className="min-w-0 space-y-1 border-l border-border px-3 py-2.5">
                  {cell.value === null ? (
                    <p className="text-[12.5px] text-ink-muted">No figure</p>
                  ) : (
                    <>
                      <p className="flex flex-wrap items-baseline gap-x-2">
                        <span className="type-ledger text-[14px] font-semibold text-ink">{formatFact(row.unit as FactUnit, cell.value)}</span>
                        <span className="rounded-full bg-surface-muted px-1.5 text-[10.5px] tabular-nums text-ink-secondary">{cell.period}</span>
                        {row.highest.includes(cell.region_code) && <span className="text-[11px] font-medium text-pop">Highest</span>}
                      </p>
                      <span className="clay-well block h-1.5 overflow-hidden rounded-full p-px" aria-hidden>
                        <span className="block h-full rounded-full bg-[var(--role-lens-strong)]" style={{ width: `${top > 0 ? Math.max(2, (cell.value / top) * 100) : 0}%` }} />
                      </span>
                    </>
                  )}
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export const COMPARE_MIN = 2;
export const COMPARE_MAX = 4;

function ItemRow({ item, names, onOpen }: { item: LensCompareItem; names: Record<string, string>; onOpen(id: string): void }) {
  return (
    <li>
      <button
        type="button"
        onClick={() => onOpen(item.claim_id)}
        className="group block min-h-9 w-full rounded-md px-1.5 py-1 text-left hover:bg-surface-muted"
        aria-label={`${item.label}: open the evidence`}
      >
        <span className="block text-[13.5px] leading-snug text-ink">
          {item.label}
          {item.in_conflict && <GitCompareArrows aria-label="Open conflict" className="ml-1 inline size-3 text-warning" />}
        </span>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px] text-ink-secondary">
          <KindTag kind={item.kind} />
          <ConfidenceIndicator level={item.confidence} showRule={false} />
          <span>
            {item.source_count} {item.source_count === 1 ? "source" : "sources"}
          </span>
          {item.also_in.length > 0 && <span>also sourced in {item.also_in.map((c) => names[c] ?? c).join(", ")}</span>}
        </span>
      </button>
    </li>
  );
}

function ClaimSheet({ workspaceId, claimId, onClose }: { workspaceId: string; claimId: string | null; onClose(): void }) {
  const claim = useClaim(workspaceId, claimId);
  return (
    <Sheet open={claimId !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="gap-0 bg-surface data-[side=right]:w-full data-[side=right]:sm:max-w-[34rem]">
        <SheetHeader className="border-b border-border pr-12">
          <SheetTitle className="text-[15px] font-semibold text-ink">Evidence</SheetTitle>
          <SheetDescription className="text-[13px] text-ink-secondary">The claim with its five tags, every source and the rule behind its confidence.</SheetDescription>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto px-4 py-4">
          {claim.isPending && <LoadingState label="Reading the claim…" />}
          {claim.isError && <ErrorState error={claim.error} onRetry={() => void claim.refetch()} />}
          {claim.data && <ClaimEntry claim={claim.data} />}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Table({ data, onOpen }: { data: LensCompare; onOpen(id: string): void }) {
  const names = Object.fromEntries(data.regions.map((r) => [r.region.code, r.region.name]));
  const cols = data.regions.length;
  const grid = { gridTemplateColumns: `8.5rem repeat(${cols}, minmax(14rem, 1fr))` };
  return (
    <div className="overflow-x-auto rounded-card border border-border bg-surface" role="region" aria-label="Comparison table" tabIndex={0}>
      <div role="table" className="min-w-max">
        <div role="row" className="grid border-b border-border bg-surface-muted/60" style={grid}>
          <div role="columnheader" className="type-meta sticky left-0 z-10 bg-surface-muted px-3 py-2.5">
            Dimension
          </div>
          {data.regions.map((r) => (
            <div key={r.region.code} role="columnheader" className="space-y-1 border-l border-border px-3 py-2.5">
              <p className="type-title text-[19px] text-ink">{r.region.name}</p>
              <StrengthTag strength={strengthOf(r.strength, r.claims)} />
            </div>
          ))}
        </div>
        <div role="row" className="grid border-b border-border" style={grid}>
          <div role="rowheader" className="sticky left-0 z-10 bg-surface px-3 py-2.5 text-[13px] font-medium text-ink">
            Evidence
          </div>
          {data.regions.map((r) => (
            <div key={r.region.code} role="cell" className="type-ledger space-y-0.5 border-l border-border px-3 py-2.5 text-[12.5px] text-ink-body">
              {r.claims === 0 ? (
                <p className="text-ink-muted">No claims{r.built ? " stored" : " yet"}</p>
              ) : (
                <>
                  <p>
                    {nf.format(r.claims)} claims, {nf.format(r.supported_claims)} supported
                  </p>
                  <p>
                    {r.categories_covered} of {r.categories_total} categories
                  </p>
                  <p>
                    Low {r.low} · Moderate {r.moderate} · High {r.high}
                  </p>
                  <p>{r.open_conflicts > 0 ? `${r.open_conflicts} open conflict` : "No open conflict"}</p>
                  <p className="text-ink-secondary">{r.newest_source_date ? `Newest source ${formatDate(r.newest_source_date)}` : "No dated source"}</p>
                  {r.missing_categories.length > 0 && <p className="text-ink-secondary">Missing: {r.missing_categories.map(categoryLabel).join(", ")}</p>}
                </>
              )}
            </div>
          ))}
        </div>
        {data.rows.map((row) => (
          <div key={row.key} role="row" className="grid border-b border-border last:border-b-0" style={grid}>
            <div role="rowheader" className="sticky left-0 z-10 bg-surface px-3 py-2.5">
              <p className="text-[13px] font-medium text-ink">{row.title}</p>
              <p className="type-meta">{row.shared_subjects > 0 ? `${row.shared_subjects} sourced in every state` : "None shared"}</p>
            </div>
            {row.cells.map((cell) => (
              <div key={cell.region_code} role="cell" className={cn("min-w-0 border-l border-border px-1.5 py-2", cell.missing && "bg-surface-muted/40")}>
                {cell.missing ? (
                  <p className="px-1.5 py-1 text-[12.5px] text-ink-muted">No claim found. This is a gap in the evidence, not a statement about the state.</p>
                ) : (
                  <>
                    <ul>
                      {cell.items.map((item) => (
                        <ItemRow key={item.claim_id} item={item} names={names} onOpen={onOpen} />
                      ))}
                    </ul>
                    {cell.total > cell.items.length && <p className="px-1.5 pt-1 text-[12px] text-ink-muted">{cell.total - cell.items.length} more in the state profile.</p>}
                  </>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export function CompareView({ campaignId, regions, onRegions }: { campaignId: string; regions: string[]; onRegions(codes: string[]): void }) {
  const atlas = useAtlas(campaignId);
  const compare = useCompare(campaignId, regions);
  const [claimId, setClaimId] = useState<string | null>(null);
  const names = Object.fromEntries((atlas.data?.states ?? []).map((s) => [s.code, s.name]));
  const data = compare.data;
  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <ul aria-label="States being compared" className="flex flex-wrap items-center gap-2">
          {regions.map((code) => (
            <li key={code} className="clay inline-flex h-8 items-center gap-1.5 rounded-lg border border-border pr-1 pl-3 text-[13.5px] text-ink">
              {names[code] ?? code}
              <Button type="button" variant="ghost" size="icon-xs" aria-label={`Remove ${names[code] ?? code} from the comparison`} onClick={() => onRegions(regions.filter((c) => c !== code))}>
                <X aria-hidden />
              </Button>
            </li>
          ))}
          {regions.length < COMPARE_MAX && (
            <li>
              <StateSelect
                campaignId={campaignId}
                value={null}
                label="Add a state"
                placeholder="Add a state"
                exclude={regions}
                onChange={(code) => onRegions([...regions, code])}
                className="[&>label]:sr-only"
              />
            </li>
          )}
        </ul>
        <p className="text-[12.5px] text-ink-secondary">Compare {COMPARE_MIN} to {COMPARE_MAX} states on the same dimensions. A claim in two columns means two sources were found; it does not mean the two things are the same.</p>
      </div>

      {regions.length < COMPARE_MIN && (
        <EmptyState title="Choose at least two states" description="The comparison puts states side by side on the same evidence, with missing evidence shown as missing." needs={[{ label: `${COMPARE_MIN} to ${COMPARE_MAX} states`, met: regions.length >= COMPARE_MIN }]} />
      )}
      {regions.length >= COMPARE_MIN && compare.isPending && <LoadingState label="Comparing the states…" />}
      {compare.isError && <ErrorState error={compare.error} onRetry={() => void compare.refetch()} />}
      {data && (
        <>
          <section aria-labelledby="cmp-data" className="space-y-3">
            <SectionTitle id="cmp-data" meta={`${data.data_rows.length} published figures`}>
              {data.regions.map((r) => r.region.name).join(" and ")}: the numbers
            </SectionTitle>
            <DataTable data={data} />
          </section>
          <section aria-labelledby="cmp" className="space-y-3">
            <SectionTitle id="cmp" meta="Select a claim for its sources">
              Cited evidence
            </SectionTitle>
            <Table data={data} onOpen={setClaimId} />
          </section>
          <DataSources sources={data.data_sources} />
          <SourcesPanel sources={data.sources} limitations={data.limitations} modeLabel={data.mode_label} />
          <ClaimSheet workspaceId={data.workspace_id} claimId={claimId} onClose={() => setClaimId(null)} />
        </>
      )}
    </div>
  );
}
