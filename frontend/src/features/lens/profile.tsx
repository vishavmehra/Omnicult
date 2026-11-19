"use client";

import { CalendarDays, Hammer, Languages } from "lucide-react";
import { useState } from "react";

import { EvidenceMeter } from "@/components/evidence/evidence-meter";
import type { ClaimKind } from "@/components/evidence/evidence-row";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { SectionTitle } from "@/features/workspaces/parts";
import { formatDate } from "@/lib/format";

import { useStateProfile, type LensProfileSection, type LensStateProfile } from "./api";
import { BuildPanel, BuildSummary } from "./build-panel";
import { ClaimEntry } from "./claim-entry";
import { ConflictList } from "./conflicts";
import { categoryLabel, languageName, scriptName } from "./format";
import { SourcesPanel, StrengthTag, nf, strengthOf } from "./parts";
import { StateFactsPanel } from "./state-facts";
import { StateSelect } from "./state-select";

export type LensView = "atlas" | "profile" | "calendar" | "compare" | "language-map";

const FIRST = 6;

function kindCounts(profile: LensStateProfile) {
  const counts: Partial<Record<ClaimKind, number>> = {};
  const groups = new Set<string>();
  for (const s of profile.sections) {
    for (const c of s.claims) {
      counts[c.kind] = (counts[c.kind] ?? 0) + 1;
      for (const src of c.sources) groups.add(src.independence_group);
    }
  }
  return { counts, groups: groups.size };
}

function Section({ section, onNavigate }: { section: LensProfileSection; onNavigate(view: LensView): void }) {
  const [all, setAll] = useState(false);
  const shown = all ? section.claims : section.claims.slice(0, FIRST);
  return (
    <section aria-labelledby={`sec-${section.key}`} className="space-y-3">
      <div>
        <SectionTitle id={`sec-${section.key}`} meta={`${section.claims.length} ${section.claims.length === 1 ? "claim" : "claims"}`}>
          {section.title}
        </SectionTitle>
        <p className="max-w-[68ch] text-[13px] text-ink-secondary">{section.description}</p>
      </div>
      {section.claims.length === 0 ? (
        <p className="rounded-card border border-dashed border-border-strong/50 bg-surface-muted/50 px-4 py-3 text-[13.5px] text-ink-secondary">{section.empty_reason}</p>
      ) : (
        <ul className="space-y-3">
          {shown.map((c) => (
            <li key={c.id}>
              <ClaimEntry claim={c} />
            </li>
          ))}
        </ul>
      )}
      {section.claims.length > FIRST && (
        <Button type="button" variant="outline" size="sm" onClick={() => setAll((v) => !v)} aria-expanded={all}>
          {all ? "Show fewer" : `Show all ${section.claims.length}`}
        </Button>
      )}
      {section.elsewhere.map((e) => (
        <p key={e.view} className="flex flex-wrap items-center gap-x-2 text-[13px] text-ink-secondary">
          {e.view === "calendar" ? <CalendarDays aria-hidden className="size-3.5" /> : <Languages aria-hidden className="size-3.5" />}
          {nf.format(e.claims)} {e.label} {e.claims === 1 ? "is" : "are"} shown in the {e.view === "calendar" ? "Moment Calendar" : "Language Map"}.
          <Button type="button" variant="ghost" size="xs" onClick={() => onNavigate(e.view === "calendar" ? "calendar" : "language-map")}>
            Open it
          </Button>
        </p>
      ))}
    </section>
  );
}

function Coverage({ profile }: { profile: LensStateProfile }) {
  const { meter } = profile;
  return (
    <details className="text-[13px]">
      <summary className="cursor-pointer text-ink-secondary hover:text-ink">Coverage by category ({meter.categories_covered} of {meter.categories_total} supported)</summary>
      <table className="type-ledger mt-2 w-full max-w-md text-left text-[12.5px]">
        <thead className="text-ink-muted">
          <tr>
            <th className="py-1 pr-3 font-normal">Category</th>
            <th className="py-1 pr-3 text-right font-normal">Claims</th>
            <th className="py-1 text-right font-normal">Supported</th>
          </tr>
        </thead>
        <tbody className="text-ink-body">
          {meter.coverage.map((c) => (
            <tr key={c.category} className="border-t border-border">
              <td className="py-1 pr-3">{categoryLabel(c.category)}</td>
              <td className="py-1 pr-3 text-right">{c.claims === 0 ? <span className="text-ink-muted">none</span> : c.claims}</td>
              <td className="py-1 text-right">{c.supported_claims === 0 ? <span className="text-ink-muted">none</span> : c.supported_claims}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

export function ProfileView({
  campaignId,
  region,
  onRegion,
  onNavigate,
}: {
  campaignId: string;
  region: string | null;
  onRegion(code: string): void;
  onNavigate(view: LensView): void;
}) {
  const profile = useStateProfile(campaignId, region);
  const [building, setBuilding] = useState(false);
  const data = profile.data;
  const claims = data?.meter.claims ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-3">
        <StateSelect campaignId={campaignId} value={region} onChange={onRegion} className="w-full sm:w-64" />
        {data && (
          <Button type="button" variant="outline" aria-expanded={building} onClick={() => setBuilding((v) => !v)}>
            <Hammer aria-hidden />
            {data.build ? "Rebuild" : "Build"} {data.region.name}
          </Button>
        )}
      </div>

      {!region && <EmptyState title="Choose a state" description="A profile is every sourced claim about one state: languages, festivals, food, colours, symbols, humour, customs and sensitivities, each with its source, date, kind, scope and confidence." />}
      {region && profile.isPending && <LoadingState label="Reading the profile…" />}
      {region && profile.isError && <ErrorState error={profile.error} onRetry={() => void profile.refetch()} />}

      {data && (
        <>
          {building && <BuildPanel key={data.region.code} campaignId={campaignId} mode={data.mode} regionCodes={[data.region.code]} title={`${data.build ? "Rebuild" : "Build"} ${data.region.name}`} />}

          <header className="space-y-1.5 border-b border-border pb-5">
            <h2 className="type-title text-[28px] text-ink">{data.region.name}</h2>
            <p className="type-meta">
              {data.region.kind === "union_territory" ? "Union territory" : "State"} · {data.region.code} · principal language {languageName(data.region.primary_language)} ({scriptName(data.region.primary_script)} script)
            </p>
          </header>

          <StateFactsPanel key={data.region.code} campaignId={campaignId} region={data.region.code} regionName={data.region.name} />

          {claims === 0 ? (
            <EmptyState
              title={`No sourced claims for ${data.region.name} in ${data.mode} mode yet`}
              description={
                <>
                  {data.gaps[0]} A profile is assembled from claims, each with its source, date, kind, scope and confidence. Nothing is filled in to make it look complete: a section with no claims
                  stays empty and says so.
                </>
              }
              needs={[
                { label: "A state selected", met: true },
                { label: "A build for this state, which retrieves claims and computes their confidence", met: false },
              ]}
              action={!building ? <Button type="button" onClick={() => setBuilding(true)}><Hammer aria-hidden />Build {data.region.name}</Button> : undefined}
            />
          ) : (
            <div className="grid gap-x-8 gap-y-8 xl:grid-cols-[minmax(0,1fr)_20rem]">
              <div className="min-w-0 space-y-8">
                {data.conflicts.length > 0 && (
                  <section aria-labelledby="conflicts" className="space-y-3">
                    <SectionTitle id="conflicts" meta={`${data.conflicts.filter((c) => c.status !== "resolved").length} open`}>
                      Where sources disagree
                    </SectionTitle>
                    <ConflictList conflicts={data.conflicts} campaignId={campaignId} workspaceId={data.workspace_id} />
                  </section>
                )}
                {data.sections.map((s) => (
                  <Section key={s.key} section={s} onNavigate={onNavigate} />
                ))}
              </div>
              <aside aria-label="Evidence for this state" className="min-w-0 space-y-5 xl:sticky xl:top-20 xl:self-start">
                <section className="space-y-3 rounded-card border border-border bg-surface px-4 py-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-[13px] font-semibold text-ink">Evidence strength</p>
                    <StrengthTag strength={strengthOf(data.meter.strength, claims)} />
                  </div>
                  {data.meter.strength_reasons.length > 0 && (
                    <ul className="list-disc space-y-0.5 pl-4 text-[12.5px] text-ink-secondary">
                      {data.meter.strength_reasons.map((r) => (
                        <li key={r}>{r}</li>
                      ))}
                    </ul>
                  )}
                  <EvidenceMeter {...kindCounts(data)} independentGroups={kindCounts(data).groups} conflicts={data.meter.open_conflicts} scopeLabel={data.region.name} />
                  <p className="type-ledger text-[12.5px] text-ink-body">
                    Confidence: Low {data.meter.confidence.low} · Moderate {data.meter.confidence.moderate} · High {data.meter.confidence.high}
                  </p>
                  <p className="type-meta">
                    {data.meter.supported_claims} supported by an observed source · {data.meter.stale_claims} older than two years · {data.meter.needs_review_claims} need review.
                    {data.meter.freshness.newest_source_date && ` Newest source ${formatDate(data.meter.freshness.newest_source_date)}.`}
                  </p>
                  <Coverage profile={data} />
                </section>
                {data.build && <BuildSummary build={data.build} />}
              </aside>
            </div>
          )}

          {data.gaps.length > 0 && claims > 0 && (
            <section aria-labelledby="gaps" className="space-y-2">
              <SectionTitle id="gaps">Known gaps</SectionTitle>
              <ul className="list-disc space-y-0.5 pl-5 text-[13.5px] text-ink-body">
                {data.gaps.map((g) => (
                  <li key={g}>{g}</li>
                ))}
              </ul>
            </section>
          )}
          <SourcesPanel sources={data.sources} limitations={data.limitations} modeLabel={data.mode_label} />
        </>
      )}
    </div>
  );
}
