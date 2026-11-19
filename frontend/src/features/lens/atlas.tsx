"use client";

import { ArrowRight, GitCompareArrows, Hammer, MapPin } from "lucide-react";
import { useState } from "react";

import { ChipToggleGroup, CountUp, IndiaTileMap, roleColor, type TileDatum } from "@/components/creative";
import { Button } from "@/components/ui/button";
import { ErrorState, LoadingState } from "@/components/states";
import { LedgerList, SectionTitle } from "@/features/workspaces/parts";
import { formatDate, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useAtlas, type LensAtlas, type LensAtlasState } from "./api";
import { BuildPanel, BuildStatus } from "./build-panel";
import { sourceTypeLabel } from "./claim-entry";
import { categoryLabel, languageName, scriptName } from "./format";
import { DataSources, SourcesPanel, STRENGTH, StrengthTag, nf, strengthOf, type Strength } from "./parts";
import { StateDataCard, figureOf, shortFigure } from "./state-data";
import { formatFact, type FactUnit } from "./state-facts-logic";

const suffix = (code: string) => code.split("-")[1] ?? code;

function stateStrength(s: LensAtlasState): Strength {
  return strengthOf(s.strength, s.claims);
}

/** What the map is coloured by: the Evidence Meter, or one published figure (every state has its own value or none). */
type Metric = { key: string; label: string; title: string };
const METRICS: Metric[] = [
  { key: "evidence", label: "Evidence", title: "Evidence strength" },
  { key: "internet_per100", label: "Internet", title: "Internet subscribers per 100 people" },
  { key: "home_no_internet", label: "Homes offline", title: "Households without internet at home" },
  { key: "nsdp", label: "Income", title: "Income per person, per year" },
  { key: "literacy", label: "Literacy", title: "People who can read and write" },
  { key: "tourist_visits_domestic", label: "Visitors", title: "Domestic tourist visits in a year" },
  { key: "holidays", label: "Holidays", title: "Public holidays this year" },
];

type Reading = { value: number; unit: FactUnit | "count"; text: string; period: string; national: number | null };

function reading(s: LensAtlasState, key: string): Reading | null {
  if (key === "holidays") {
    return s.data.holidays > 0 ? { value: s.data.holidays, unit: "count", text: `${s.data.holidays} public holidays`, period: String(s.data.holidays_year), national: null } : null;
  }
  const fig = figureOf(s.data, key);
  if (!fig) return null;
  const unit = fig.unit as FactUnit;
  return { value: fig.value, unit, text: formatFact(unit, fig.value), period: fig.period, national: fig.national };
}

function Cells({ strength }: { strength: Strength }) {
  const filled = STRENGTH[strength].cells;
  return (
    <span aria-hidden className="flex gap-[3px]">
      {[0, 1, 2].map((i) => (
        <span key={i} className={cn("h-[3px] w-3 rounded-full", i < filled ? "bg-ink" : "bg-border-strong/50")} />
      ))}
    </span>
  );
}

/**
 * The 36 states as an `IndiaTileMap` (a tile grid, so no boundary file is drawn). Coloured by the chosen metric: the Evidence
 * Meter's band, or a published figure scaled from the lowest to the highest state (tint depth only; the number is in the
 * label and the readout). Hover or focus previews a state; click selects it.
 */
function TileMap({ atlas, metric, selected, onSelect }: { atlas: LensAtlas; metric: Metric; selected: string | null; onSelect(code: string | null): void }) {
  const byCode = new Map(atlas.states.map((s) => [s.code, s]));
  const values = atlas.states.map((s) => reading(s, metric.key)?.value).filter((v): v is number => v !== undefined);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const tiles: Record<string, TileDatum> = {};
  for (const s of atlas.states) {
    const campaign = s.campaign_role ? <MapPin aria-label={s.campaign_role === "origin" ? "Campaign origin" : "Campaign target"} className="absolute top-1 left-1 size-3 text-pop" /> : null;
    if (metric.key === "evidence") {
      const strength = stateStrength(s);
      tiles[s.code] = {
        tone: strength === "none" ? "muted" : "heat",
        value: STRENGTH[strength].cells / 3,
        label: STRENGTH[strength].label,
        mark: (
          <>
            <Cells strength={strength} />
            {campaign}
            {s.open_conflicts > 0 && <GitCompareArrows aria-label="Open conflict" className="absolute top-1 right-1 size-3 text-warning" />}
          </>
        ),
      };
      continue;
    }
    const r = reading(s, metric.key);
    tiles[s.code] = r
      ? {
          tone: "heat",
          value: hi > lo ? (r.value - lo) / (hi - lo) : 1,
          label: `${metric.title} ${r.text} (${r.period})`,
          mark: (
            <>
              <span className="type-ledger text-[9px] leading-none text-ink-body sm:text-[10.5px]">{shortFigure(r.unit, r.value)}</span>
              {campaign}
            </>
          ),
        }
      : { tone: "muted", label: `${metric.title}: no figure`, mark: campaign };
  }
  const readout = (code: string | null) => {
    const s = code ? byCode.get(code) : null;
    if (!s) return <p className="type-meta min-h-[4.5rem] py-2">Hover or focus a state to preview it. Select one to see its figures, languages, searches and holidays.</p>;
    const strength = stateStrength(s);
    const r = metric.key === "evidence" ? null : reading(s, metric.key);
    return (
      <div className="clay min-h-[4.5rem] space-y-1 rounded-card border border-border px-3 py-2">
        <p className="flex flex-wrap items-baseline justify-between gap-x-3 text-[14px] font-medium text-ink">
          {s.name}
          {metric.key === "evidence" ? <StrengthTag strength={strength} /> : <span className="type-ledger">{r ? r.text : "No figure"}</span>}
        </p>
        <p className="type-ledger text-[12.5px] text-ink-body">
          {metric.key === "evidence"
            ? s.claims === 0
              ? "No cited claims yet. Its published figures, languages and holidays are in the card."
              : `${nf.format(s.claims)} ${s.claims === 1 ? "claim" : "claims"}, ${nf.format(s.supported_claims)} supported by an observed source. ${s.categories_covered} of ${s.categories_total} categories covered.`
            : r
              ? `${metric.title}, ${r.period}${r.national !== null && r.unit !== "count" ? ` · India ${formatFact(r.unit as FactUnit, r.national)}` : ""}`
              : `No published figure for ${metric.title.toLowerCase()}.`}
          {metric.key === "evidence" && s.open_conflicts > 0 && ` ${s.open_conflicts} open ${s.open_conflicts === 1 ? "conflict" : "conflicts"}.`}
        </p>
        <p className="text-[12px] text-ink-secondary">{s.campaign_role ? `Campaign ${s.campaign_role}. ` : ""}Click to see the state.</p>
      </div>
    );
  };
  return (
    <div className="hidden sm:block">
      <IndiaTileMap
        ariaLabel={`States and union territories, by ${metric.title.toLowerCase()}`}
        tiles={tiles}
        selected={selected}
        interactive="all"
        color={roleColor("lens", true)}
        onSelect={onSelect}
        renderReadout={readout}
      />
    </div>
  );
}

/** Below 640 px a tile map would be tiles under 44 px: a list of the same states is the usable form. */
function StateList({ atlas, metric, selected, onSelect }: { atlas: LensAtlas; metric: Metric; selected: string | null; onSelect(code: string): void }) {
  return (
    <ul aria-label="States and union territories" className="ledger-rules rounded-card border border-border bg-surface sm:hidden">
      {atlas.states.map((s) => {
        const strength = stateStrength(s);
        const r = metric.key === "evidence" ? null : reading(s, metric.key);
        return (
          <li key={s.code}>
            <button
              type="button"
              onClick={() => onSelect(s.code)}
              aria-pressed={s.code === selected}
              className={cn("flex min-h-11 w-full items-center gap-3 px-3 text-left text-[14px]", s.code === selected ? "bg-surface-raised text-ink" : "text-ink-body")}
            >
              <span className="w-7 font-mono text-[12px] text-ink-muted">{suffix(s.code)}</span>
              <span className="min-w-0 flex-1 truncate">
                {s.name}
                {s.campaign_role && <MapPin aria-label={`Campaign ${s.campaign_role}`} className="ml-1.5 inline size-3 text-pop" />}
              </span>
              {s.open_conflicts > 0 && metric.key === "evidence" && <GitCompareArrows aria-label="Open conflict" className="size-3.5 text-warning" />}
              {metric.key === "evidence" ? <StrengthTag strength={strength} /> : <span className="type-ledger text-[13px] text-ink">{r ? r.text : "None"}</span>}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function Legend({ atlas, metric }: { atlas: LensAtlas; metric: Metric }) {
  if (metric.key !== "evidence") {
    const readings = atlas.states.map((s) => reading(s, metric.key)).filter((r): r is Reading => r !== null);
    if (readings.length === 0) return null;
    const lo = readings.reduce((a, b) => (b.value < a.value ? b : a));
    const hi = readings.reduce((a, b) => (b.value > a.value ? b : a));
    const periods = [...new Set(readings.map((r) => r.period))];
    return (
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12.5px] text-ink-secondary">
        <span className="type-ledger text-ink">{lo.text}</span>
        <span aria-hidden className="h-2 w-40 rounded-full" style={{ background: `linear-gradient(90deg, color-mix(in oklab, ${roleColor("lens", true)} 18%, var(--surface)), color-mix(in oklab, ${roleColor("lens", true)} 88%, var(--surface)))` }} />
        <span className="type-ledger text-ink">{hi.text}</span>
        <span>
          {readings.length} of {atlas.states.length} states have a figure · {periods.length === 1 ? periods[0] : `periods ${periods.slice(0, 3).join(", ")}${periods.length > 3 ? "…" : ""}`}
        </span>
        <span className="inline-flex items-center gap-1">
          <MapPin aria-hidden className="size-3.5 text-pop" />
          Campaign state
        </span>
      </div>
    );
  }
  return (
    <dl aria-label="Evidence strength key" className="flex flex-wrap gap-x-5 gap-y-1.5 text-[12.5px]">
      {(Object.keys(STRENGTH) as Strength[]).map((k) => (
        <div key={k} className="flex items-center gap-2">
          <dt className="flex items-center gap-2">
            <Cells strength={k} />
            <StrengthTag strength={k} />
          </dt>
          <dd className="sr-only">{STRENGTH[k].meaning}</dd>
        </div>
      ))}
      <div className="flex items-center gap-1.5 text-ink-secondary">
        <GitCompareArrows aria-hidden className="size-3.5 text-warning" />
        Open conflict
      </div>
      <div className="flex items-center gap-1.5 text-ink-secondary">
        <MapPin aria-hidden className="size-3.5 text-pop" />
        Campaign state
      </div>
    </dl>
  );
}

function StateAside({
  campaignId,
  state,
  mode,
  onOpen,
}: {
  campaignId: string;
  state: LensAtlasState;
  mode: LensAtlas["mode"];
  onOpen(code: string): void;
}) {
  const [building, setBuilding] = useState(false);
  const strength = stateStrength(state);
  const build = state.last_build;
  return (
    <aside aria-label={`${state.name} at a glance`} className="min-w-0 space-y-5">
      <div className="space-y-1">
        <h2 className="type-title text-[24px] text-ink">{state.name}</h2>
        <p className="type-meta">
          {state.kind === "union_territory" ? "Union territory" : "State"} · {languageName(state.primary_language)} · {scriptName(state.primary_script)} script
          {state.campaign_role && ` · campaign ${state.campaign_role}`}
        </p>
      </div>
      <StateDataCard data={state.data} name={state.name} />
      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={() => onOpen(state.code)}>
          Open {state.name}
          <ArrowRight aria-hidden data-icon="inline-end" />
        </Button>
        <Button type="button" variant="outline" aria-expanded={building} onClick={() => setBuilding((v) => !v)}>
          <Hammer aria-hidden />
          {build ? "Rebuild" : "Build"} evidence
        </Button>
      </div>
      {building && (
        <BuildPanel key={`build-${state.code}`} campaignId={campaignId} mode={mode} regionCodes={[state.code]} title={`${build ? "Rebuild" : "Build"} ${state.name}`} />
      )}
      <section aria-label="Evidence" className="space-y-2">
        <h3 className="text-[13px] font-semibold text-ink">Evidence</h3>
        <LedgerList
          className="sm:[&>div]:grid-cols-[7.5rem_minmax(0,1fr)]"
          rows={[
            {
              label: "Strength",
              value: (
                <span className="space-y-1">
                  <StrengthTag strength={strength} />
                  {strength !== "none" && state.strength_reasons.length > 0 && <span className="block text-[12.5px] text-ink-secondary">{state.strength_reasons.join(" ")}</span>}
                  {strength === "none" && <span className="block text-[12.5px] text-ink-secondary">No cited claim yet. The figures above are published data, not claims.</span>}
                </span>
              ),
            },
            { label: "Claims", value: `${nf.format(state.claims)} (${nf.format(state.supported_claims)} supported by an observed source)`, muted: state.claims === 0 },
            {
              label: "Categories",
              value:
                state.claims === 0 ? (
                  "None covered"
                ) : (
                  <span>
                    {state.categories_covered} of {state.categories_total} have a supported claim.
                    {state.missing_categories.length > 0 && <span className="block text-[12.5px] text-ink-secondary">Missing: {state.missing_categories.map(categoryLabel).join(", ")}.</span>}
                  </span>
                ),
              muted: state.claims === 0,
            },
            { label: "Sources", value: state.source_types.length ? state.source_types.map(sourceTypeLabel).join(", ") : "None", muted: state.source_types.length === 0 },
            { label: "Newest source", value: state.newest_source_date ? formatDate(state.newest_source_date) : "No dated source", muted: !state.newest_source_date },
            {
              label: "Conflicts",
              value: state.open_conflicts ? `${state.open_conflicts} open: both values are kept and shown in the profile.` : "None open",
              muted: !state.open_conflicts,
            },
            {
              label: "Last build",
              value: build ? (
                <span className="space-y-0.5">
                  <BuildStatus status={build.status} />
                  <span className="block text-[12.5px] text-ink-secondary">
                    Version {build.version}, {formatRelative(build.finished_at)}
                  </span>
                </span>
              ) : (
                "Never built in this mode"
              ),
              muted: !build,
            },
          ]}
        />
      </section>
    </aside>
  );
}

export function AtlasView({ campaignId, selected, onSelect, onOpenProfile }: { campaignId: string; selected: string | null; onSelect(code: string | null): void; onOpenProfile(code: string): void }) {
  const atlas = useAtlas(campaignId);
  const [metricKey, setMetricKey] = useState("internet_per100"); // a figure every state has; Evidence is one click away
  if (atlas.isPending) return <LoadingState label="Reading every state…" />;
  if (atlas.isError) return <ErrorState error={atlas.error} onRetry={() => void atlas.refetch()} />;
  const data = atlas.data;
  const metric = METRICS.find((m) => m.key === metricKey) ?? METRICS[0];
  const origin = data.states.find((s) => s.campaign_role === "origin");
  const state = data.states.find((s) => s.code === selected) ?? origin ?? null;
  const { summary } = data;
  const weakWithClaims = data.states.filter((s) => s.claims > 0 && s.strength === "weak").length;
  return (
    <div className="space-y-6">
      <dl aria-label="What Market Lens holds" className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {[
          { label: `With published data, of ${summary.states_total}`, value: summary.states_with_data },
          { label: `With cited claims, of ${summary.states_total}`, value: summary.states_with_claims },
          { label: "Solid evidence", value: summary.solid },
          { label: "Partial evidence", value: summary.partial },
          { label: "Weak evidence", value: weakWithClaims },
          { label: "Open conflicts", value: summary.open_conflicts },
        ].map((x) => (
          <div key={x.label} className="clay rounded-card border border-border bg-surface px-3 py-2">
            <dt className="type-meta">{x.label}</dt>
            <dd className="text-[26px] leading-tight font-semibold text-ink">
              <CountUp value={x.value} />
            </dd>
          </div>
        ))}
      </dl>
      <div className="grid gap-x-8 gap-y-6 xl:grid-cols-[minmax(0,1fr)_23rem]">
        <section aria-labelledby="atlas-map" className="min-w-0 space-y-4">
          <SectionTitle id="atlas-map" meta={`${summary.states_total} states and union territories`}>
            {metric.key === "evidence" ? "Evidence by state" : `${metric.title}, by state`}
          </SectionTitle>
          <ChipToggleGroup ariaLabel="Colour the map by" size="sm" value={metric.key} onChange={setMetricKey} options={METRICS.map((m) => ({ value: m.key, label: m.label }))} />
          <p className="max-w-[68ch] text-[13.5px] text-ink-secondary">
            {metric.key === "evidence"
              ? `${summary.states_with_claims} of ${summary.states_total} have cited claims: ${summary.solid} solid, ${summary.partial} partial, ${weakWithClaims} weak. Every state also has published figures, languages and holidays; pick a figure above to colour the map by it.`
              : "Tint runs from the lowest to the highest state with a figure. A state with no figure stays grey: the dataset has none for it."}
            {metric.key === "evidence" && summary.open_conflicts > 0 && ` ${summary.open_conflicts} open ${summary.open_conflicts === 1 ? "conflict" : "conflicts"}.`}
          </p>
          <TileMap atlas={data} metric={metric} selected={state?.code ?? null} onSelect={onSelect} />
          <StateList atlas={data} metric={metric} selected={state?.code ?? null} onSelect={onSelect} />
          <Legend atlas={data} metric={metric} />
        </section>
        <div className="min-w-0">{state && <StateAside key={state.code} campaignId={campaignId} state={state} mode={data.mode} onOpen={onOpenProfile} />}</div>
      </div>
      <DataSources sources={data.data_sources} />
      <SourcesPanel sources={data.sources} limitations={data.limitations} modeLabel={data.mode_label} />
    </div>
  );
}
