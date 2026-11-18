"use client";

import { GitCompareArrows } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { SectionTitle } from "@/features/workspaces/parts";

import { useLanguageMap, type LensLanguageEntry, type LensLanguageMap } from "./api";
import { ClaimEntry, sourceTypeLabel } from "./claim-entry";
import { ConflictList } from "./conflicts";
import { languageName, scriptName } from "./format";
import { SourcesPanel } from "./parts";
import { StateSelect } from "./state-select";

const ROLE = { primary: "Principal official language", secondary: "Additional official or widely used", code_mixed: "Code-mixed variety" } as const;

/** Share of the state's population, drawn from zero to one hundred percent: the bar is the number, not a rank. */
function Bar({ percent, label }: { percent: number; label: string }) {
  return (
    <div className="flex items-center gap-3">
      <div className="clay-well h-2.5 flex-1 overflow-hidden rounded-[3px] p-[2px]" role="img" aria-label={label}>
        <div className="h-full rounded-[2px] bg-ink-secondary" style={{ width: `${Math.max(percent, 0.6)}%` }} />
      </div>
      <span className="type-ledger w-14 text-right text-[13px] text-ink">{percent.toFixed(2)}%</span>
    </div>
  );
}

function Row({ entry, state }: { entry: LensLanguageEntry; state: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const lang = entry.code ?? undefined;
  return (
    <li className="space-y-2 px-4 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
        <p className="text-[14.5px] font-medium text-ink">
          {entry.name}
          {entry.native_name && entry.native_name !== entry.name && (
            <span lang={lang} className="ml-2 text-[15px] font-normal text-ink-body">
              {entry.native_name}
            </span>
          )}
        </p>
        <p className="type-meta">
          {entry.role ? ROLE[entry.role] : "From the census only"}
          {entry.script ? ` · ${scriptName(entry.script)} script` : ""}
          {entry.code ? ` · ${entry.code}` : ""}
        </p>
      </div>
      {entry.shares.length === 0 ? (
        <p className="text-[12.5px] text-ink-muted">No census share collected for this language in {state}. Roles come from reference data and are not speaker shares.</p>
      ) : (
        <>
          <div className="space-y-1.5">
            {entry.shares.map((s) => (
              <div key={s.claim.id} className="space-y-0.5">
                <Bar percent={s.percent} label={`${entry.name}: ${s.percent}% of the population in the 2011 census, ${sourceTypeLabel(s.claim.sources[0]?.source_type ?? "")}`} />
                {entry.disputed && <p className="type-meta pl-0.5">{s.claim.sources.map((x) => sourceTypeLabel(x.source_type)).join(", ")}</p>}
              </div>
            ))}
          </div>
          {entry.disputed && (
            <p className="flex items-center gap-1.5 text-[12.5px] font-medium text-warning">
              <GitCompareArrows aria-hidden className="size-3.5" />
              Sources disagree on this share. Both values are kept; see the conflict below.
            </p>
          )}
          <Button type="button" variant="ghost" size="xs" aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>
            {open ? "Hide evidence" : entry.disputed ? "Show evidence for both values" : "Show evidence"}
          </Button>
          {open && (
            <div id={id} className="space-y-2.5">
              {entry.shares.map((s) => (
                <ClaimEntry key={s.claim.id} claim={s.claim} />
              ))}
            </div>
          )}
        </>
      )}
    </li>
  );
}

function Detail({ data, region, campaignId }: { data: LensLanguageMap; region: string; campaignId: string }) {
  const r = data.regions.find((x) => x.region_code === region);
  if (!r) return null;
  return (
    <section aria-labelledby="lm-state" className="space-y-3">
      <SectionTitle id="lm-state" meta={r.has_census ? "Census 2011" : "No census shares collected"}>
        {r.region_name}: {languageName(r.primary_language)} in {scriptName(r.primary_script)} script
      </SectionTitle>
      {!r.has_census && (
        <p className="max-w-[68ch] text-[13.5px] text-ink-secondary">
          Census shares are collected for four states. For this one the page lists the languages and scripts from reference data only. Build the four demo states, or add the census table, to see shares.
        </p>
      )}
      <ul className="ledger-rules rounded-card border border-border bg-surface">
        {r.languages.map((l) => (
          <Row key={`${l.code}-${l.name}`} entry={l} state={r.region_name} />
        ))}
      </ul>
      {r.conflicts.length > 0 && <ConflictList conflicts={r.conflicts} campaignId={campaignId} workspaceId={data.workspace_id} />}
    </section>
  );
}

export function LanguageMapView({ campaignId, region, onRegion }: { campaignId: string; region: string | null; onRegion(code: string): void }) {
  const map = useLanguageMap(campaignId);
  const data = map.data;
  const withCensus = data?.regions.filter((r) => r.has_census) ?? [];
  return (
    <div className="space-y-6">
      <StateSelect campaignId={campaignId} value={region} onChange={onRegion} className="w-full sm:w-64" />
      {map.isPending && <LoadingState label="Reading the language map…" />}
      {map.isError && <ErrorState error={map.error} onRetry={() => void map.refetch()} />}
      {data && (
        <>
          <p className="max-w-[68ch] text-[13px] text-ink-secondary">
            Census year {data.period}: mother tongue as reported then, not a current language mix.{" "}
            {withCensus.length > 0 ? `Shares are stored for ${withCensus.map((r) => r.region_name).join(", ")}.` : "No census share is stored in this mode yet."}
          </p>
          {region ? (
            <Detail data={data} region={region} campaignId={campaignId} />
          ) : (
            <EmptyState title="Choose a state" description="See its languages and scripts, and where a build stored them, the 2011 census share of each language with its source." />
          )}
          <p className="max-w-[68ch] text-[13px] text-ink-secondary">
            <span className="font-medium text-ink">Code-mixing.</span> {data.code_mixing.note}
          </p>
          <SourcesPanel sources={data.sources} limitations={data.limitations} modeLabel={data.mode_label} />
        </>
      )}
    </div>
  );
}
