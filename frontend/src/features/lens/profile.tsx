"use client";

import { CalendarDays, Hammer, Languages, LoaderCircle, MapPin } from "lucide-react";
import { useState } from "react";

import { EvidenceMeter } from "@/components/evidence/evidence-meter";
import type { ClaimKind } from "@/components/evidence/evidence-row";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { SearchPulse } from "@/features/lens-t3/search-pulse";
import { SectionTitle } from "@/features/workspaces/parts";
import { formatDate } from "@/lib/format";

import { useAutoBuild, useStateProfile, type LensProfileSection, type LensStateProfile } from "./api";
import { BuildPanel, BuildSummary } from "./build-panel";
import { ClaimEntry } from "./claim-entry";
import { ConflictList } from "./conflicts";
import { categoryLabel, languageName, scriptName } from "./format";
import { DataSources, SourcesPanel, StrengthTag, nf, strengthOf } from "./parts";
import { StateDataCard } from "./state-data";
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

function Meter({ data }: { data: LensStateProfile }) {
  const claims = data.meter.claims;
  return (
    <section className="space-y-3 rounded-card border border-border bg-surface px-4 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] font-semibold text-ink">Evidence strength</p>
        <StrengthTag strength={strengthOf(data.meter.strength, claims)} />
      </div>
      {claims > 0 && data.meter.strength_reasons.length > 0 && (
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
  const autoBuild = useAutoBuild(campaignId);
  const [building, setBuilding] = useState(false);
  const data = profile.data;
  const claims = data?.meter.claims ?? 0;
  const queued = autoBuild?.regions.find((r) => r.region_code === data?.region.code && (r.state === "queued" || r.state === "building"));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-3">
        <StateSelect campaignId={campaignId} value={region} onChange={onRegion} className="w-full sm:w-64" />
        {data && !queued && (
          <Button type="button" variant="outline" aria-expanded={building} onClick={() => setBuilding((v) => !v)}>
            <Hammer aria-hidden />
            {data.build ? "Rebuild" : "Build"} evidence
          </Button>
        )}
      </div>

      {!region && <EmptyState title="Choose a state" description="A profile is every published figure and every sourced claim about one state: languages, festivals, food, colours, symbols, humour, customs and sensitivities." />}
      {region && profile.isPending && <LoadingState label="Reading the profile…" />}
      {region && profile.isError && <ErrorState error={profile.error} onRetry={() => void profile.refetch()} />}

      {data && (
        <>
          {building && <BuildPanel key={`build-${data.region.code}`} campaignId={campaignId} mode={data.mode} regionCodes={[data.region.code]} title={`${data.build ? "Rebuild" : "Build"} ${data.region.name}`} />}

          <header className="space-y-1.5 border-b border-border pb-5">
            <h2 className="type-title flex flex-wrap items-center gap-x-3 text-[28px] text-ink">
              {data.region.name}
              {data.campaign_role && (
                <span className="inline-flex items-center gap-1 rounded-full bg-pop-soft px-2.5 py-0.5 text-[12.5px] font-medium text-ink">
                  <MapPin aria-hidden className="size-3.5 text-pop" />
                  Campaign {data.campaign_role}
                </span>
              )}
            </h2>
            <p className="type-meta">
              {data.region.kind === "union_territory" ? "Union territory" : "State"} · {data.region.code} · principal language {languageName(data.region.primary_language)} ({scriptName(data.region.primary_script)} script)
            </p>
          </header>

          <section aria-labelledby="glance" className="grid gap-x-8 gap-y-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
            <div className="min-w-0 space-y-3">
              <SectionTitle id="glance">At a glance</SectionTitle>
              <StateDataCard data={data.data} name={data.region.name} figures={false} onOpenCalendar={() => onNavigate("calendar")} />
            </div>
            <div className="min-w-0 space-y-3">
              <Meter data={data} />
              {data.build && <BuildSummary build={data.build} />}
            </div>
          </section>

          <SearchPulse key={`pulse-${data.region.code}`} campaignId={campaignId} region={data.region.code} />
          <StateFactsPanel key={`facts-${data.region.code}`} campaignId={campaignId} region={data.region.code} regionName={data.region.name} />

          <section aria-labelledby="evidence" className="space-y-6">
            <SectionTitle id="evidence" meta={claims > 0 ? `${nf.format(claims)} cited ${claims === 1 ? "claim" : "claims"}` : undefined}>
              Cited evidence
            </SectionTitle>
            {claims === 0 ? (
              <div role="status" className="flex flex-wrap items-center gap-3 rounded-card border border-dashed border-border-strong/50 bg-surface-muted/50 px-4 py-3 text-[13.5px] text-ink-secondary">
                {queued ? (
                  <>
                    <LoaderCircle aria-hidden className="size-4 animate-spin text-pop motion-reduce:animate-none" />
                    {queued.state === "building" ? `Building ${data.region.name}: cited claims will appear here as soon as they are stored.` : `${data.region.name} is queued to be built.`}
                  </>
                ) : (
                  <>
                    No cited claim about {data.region.name} is stored yet. The figures above are published data; a build gathers cited claims for the Evidence Meter.
                    {!building && (
                      <Button type="button" size="sm" onClick={() => setBuilding(true)}>
                        <Hammer aria-hidden />
                        Build {data.region.name}
                      </Button>
                    )}
                  </>
                )}
              </div>
            ) : (
              <>
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
              </>
            )}
          </section>

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
          <DataSources sources={data.data_sources} />
          <SourcesPanel sources={data.sources} limitations={data.limitations} modeLabel={data.mode_label} />
        </>
      )}
    </div>
  );
}
