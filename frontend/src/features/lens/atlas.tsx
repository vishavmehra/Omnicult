"use client";

import { ArrowRight, GitCompareArrows, Hammer } from "lucide-react";
import { useState } from "react";

import { CountUp, IndiaTileMap, roleColor, type TileDatum } from "@/components/creative";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { LedgerList, SectionTitle } from "@/features/workspaces/parts";
import { formatDate, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useAtlas, type LensAtlas, type LensAtlasState } from "./api";
import { BuildPanel, BuildStatus } from "./build-panel";
import { sourceTypeLabel } from "./claim-entry";
import { categoryLabel, languageName, scriptName } from "./format";
import { SourcesPanel, STRENGTH, StrengthTag, nf, strengthOf, type Strength } from "./parts";

const suffix = (code: string) => code.split("-")[1] ?? code;

function stateStrength(s: LensAtlasState): Strength {
  return strengthOf(s.strength, s.claims);
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
 * The 36 states as an `IndiaTileMap` (a tile grid, so no boundary file is drawn). Tint depth encodes the API's strength
 * band (none, weak, partial, solid) and nothing else: the word is in the label, the three cells and the readout. Hover
 * or focus previews a state; click opens its profile when it has claims, otherwise selects it so it can be built.
 */
function TileMap({ atlas, selected, onSelect, onOpen }: { atlas: LensAtlas; selected: string | null; onSelect(code: string | null): void; onOpen(code: string): void }) {
  const byCode = new Map(atlas.states.map((s) => [s.code, s]));
  const tiles: Record<string, TileDatum> = {};
  for (const s of atlas.states) {
    const strength = stateStrength(s);
    tiles[s.code] = {
      tone: strength === "none" ? "muted" : "heat",
      value: STRENGTH[strength].cells / 3,
      label: STRENGTH[strength].label,
      mark: (
        <>
          <Cells strength={strength} />
          {s.open_conflicts > 0 && <GitCompareArrows aria-label="Open conflict" className="absolute top-1 right-1 size-3 text-warning" />}
        </>
      ),
    };
  }
  const readout = (code: string | null) => {
    const s = code ? byCode.get(code) : null;
    if (!s) return <p className="type-meta min-h-[4.5rem] py-2">Hover or focus a state to preview its evidence. Select one to open its profile.</p>;
    const strength = stateStrength(s);
    return (
      <div className="clay min-h-[4.5rem] space-y-1 rounded-card border border-border px-3 py-2">
        <p className="flex flex-wrap items-baseline justify-between gap-x-3 text-[14px] font-medium text-ink">
          {s.name}
          <StrengthTag strength={strength} />
        </p>
        <p className="type-ledger text-[12.5px] text-ink-body">
          {s.claims === 0
            ? "No claims recorded in this mode."
            : `${nf.format(s.claims)} ${s.claims === 1 ? "claim" : "claims"}, ${nf.format(s.supported_claims)} supported by an observed source. ${s.categories_covered} of ${s.categories_total} categories covered.`}
          {s.open_conflicts > 0 && ` ${s.open_conflicts} open ${s.open_conflicts === 1 ? "conflict" : "conflicts"}.`}
        </p>
        <p className="text-[12px] text-ink-secondary">{s.claims > 0 ? "Click to open the state profile." : "Click to select it, then build it."}</p>
      </div>
    );
  };
  return (
    <div className="hidden sm:block">
      <IndiaTileMap
        ariaLabel="States and union territories, by evidence strength"
        tiles={tiles}
        selected={selected}
        color={roleColor("lens", true)}
        onSelect={(code) => {
          if (code && (byCode.get(code)?.claims ?? 0) > 0) onOpen(code);
          else onSelect(code);
        }}
        renderReadout={readout}
      />
    </div>
  );
}

/** Below 640 px a tile map would be tiles under 44 px: a list of the same states is the usable form. */
function StateList({ atlas, selected, onSelect }: { atlas: LensAtlas; selected: string | null; onSelect(code: string): void }) {
  return (
    <ul aria-label="States and union territories" className="ledger-rules rounded-card border border-border bg-surface sm:hidden">
      {atlas.states.map((s) => {
        const strength = stateStrength(s);
        return (
          <li key={s.code}>
            <button
              type="button"
              onClick={() => onSelect(s.code)}
              aria-pressed={s.code === selected}
              className={cn("flex min-h-11 w-full items-center gap-3 px-3 text-left text-[14px]", s.code === selected ? "bg-surface-raised text-ink" : "text-ink-body")}
            >
              <span className="w-7 font-mono text-[12px] text-ink-muted">{suffix(s.code)}</span>
              <span className="min-w-0 flex-1 truncate">{s.name}</span>
              {s.open_conflicts > 0 && <GitCompareArrows aria-label="Open conflict" className="size-3.5 text-warning" />}
              <StrengthTag strength={strength} />
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function Legend() {
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
    <aside aria-label={`${state.name} evidence`} className="min-w-0 space-y-4">
      <div className="space-y-1">
        <h2 className="type-title text-[24px] text-ink">{state.name}</h2>
        <p className="type-meta">
          {state.kind === "union_territory" ? "Union territory" : "State"} · {languageName(state.primary_language)} · {scriptName(state.primary_script)} script
        </p>
      </div>
      <LedgerList
        className="sm:[&>div]:grid-cols-[7.5rem_minmax(0,1fr)]"
        rows={[
          {
            label: "Evidence",
            value: (
              <span className="space-y-1">
                <StrengthTag strength={strength} />
                {strength !== "none" && state.strength_reasons.length > 0 && (
                  <span className="block text-[12.5px] text-ink-secondary">{state.strength_reasons.join(" ")}</span>
                )}
                {strength === "none" && <span className="block text-[12.5px] text-ink-secondary">{STRENGTH.none.meaning}</span>}
              </span>
            ),
          },
          { label: "Claims", value: `${nf.format(state.claims)} (${nf.format(state.supported_claims)} supported by an observed source)` },
          {
            label: "Categories",
            value:
              state.claims === 0 ? (
                "None covered"
              ) : (
                <span>
                  {state.categories_covered} of {state.categories_total} have a supported claim.
                  {state.missing_categories.length > 0 && (
                    <span className="block text-[12.5px] text-ink-secondary">Missing: {state.missing_categories.map(categoryLabel).join(", ")}.</span>
                  )}
                </span>
              ),
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
      <div className="flex flex-wrap gap-2">
        {state.claims > 0 && (
          <Button type="button" onClick={() => onOpen(state.code)}>
            Open {state.name} profile
            <ArrowRight aria-hidden data-icon="inline-end" />
          </Button>
        )}
        <Button type="button" variant={state.claims > 0 ? "outline" : "default"} aria-expanded={building} onClick={() => setBuilding((v) => !v)}>
          <Hammer aria-hidden />
          {build ? "Rebuild" : "Build"} {state.name}
        </Button>
      </div>
      {building && (
        <BuildPanel
          key={state.code}
          campaignId={campaignId}
          mode={mode}
          regionCodes={[state.code]}
          title={`${build ? "Rebuild" : "Build"} ${state.name}`}
        />
      )}
    </aside>
  );
}

const DEMO_STATES = ["IN-MH", "IN-TN", "IN-KL", "IN-WB"];

export function AtlasView({ campaignId, selected, onSelect, onOpenProfile }: { campaignId: string; selected: string | null; onSelect(code: string | null): void; onOpenProfile(code: string): void }) {
  const atlas = useAtlas(campaignId);
  if (atlas.isPending) return <LoadingState label="Reading the evidence for every state…" />;
  if (atlas.isError) return <ErrorState error={atlas.error} onRetry={() => void atlas.refetch()} />;
  const data = atlas.data;
  const state = data.states.find((s) => s.code === selected) ?? null;
  const { summary } = data;
  return (
    <div className="space-y-6">
      {summary.states_with_claims === 0 && (
        <EmptyState
          title={`No state has been built in ${data.mode} mode yet`}
          description={
            data.mode === "demo"
              ? "Nothing is built yet. Load the four demo states to see the evidence map."
              : "Live mode retrieves claims from the sources when you build a state. Until then every state stays empty: nothing is filled in to make the map look complete."
          }
          needs={[
            { label: "A state selected on the map", met: Boolean(state) },
            { label: "A build, which gathers claims with their sources and computes confidence", met: false },
          ]}
          action={data.mode === "demo" ? <BuildPanel campaignId={campaignId} mode="demo" regionCodes={DEMO_STATES} title="Load the four demo states" /> : undefined}
        />
      )}
      <div className="grid gap-x-8 gap-y-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <section aria-labelledby="atlas-map" className="min-w-0 space-y-4">
          <SectionTitle id="atlas-map" meta={`${summary.states_total} states and union territories`}>
            Evidence by state
          </SectionTitle>
          <p className="max-w-[68ch] text-[13.5px] text-ink-secondary">
            {summary.states_with_claims === 0
              ? "Every tile is empty."
              : `${summary.states_with_claims} of ${summary.states_total} have claims: ${summary.solid} solid, ${summary.partial} partial, ${summary.weak - (summary.states_total - summary.states_with_claims)} weak. ${summary.states_total - summary.states_with_claims} have none, which means nothing is recorded, not that nothing exists.`}
            {summary.open_conflicts > 0 && ` ${summary.open_conflicts} open ${summary.open_conflicts === 1 ? "conflict" : "conflicts"}.`}
          </p>
          {summary.states_with_claims > 0 && (
            <dl aria-label="Evidence summary" className="grid grid-cols-2 gap-2 sm:grid-cols-5">
              {[
                { label: `With claims, of ${summary.states_total}`, value: summary.states_with_claims },
                { label: "Solid", value: summary.solid },
                { label: "Partial", value: summary.partial },
                { label: "Weak", value: summary.weak - (summary.states_total - summary.states_with_claims) },
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
          )}
          <TileMap atlas={data} selected={selected} onSelect={onSelect} onOpen={onOpenProfile} />
          <StateList atlas={data} selected={selected} onSelect={onSelect} />
          <Legend />
        </section>
        <div className="min-w-0">
          {state ? (
            <StateAside campaignId={campaignId} state={state} mode={data.mode} onOpen={onOpenProfile} />
          ) : (
            <EmptyState title="Choose a state" description="Select a tile to see what is known about the state, how strong that evidence is and where it came from." />
          )}
        </div>
      </div>
      <SourcesPanel sources={data.sources} limitations={data.limitations} modeLabel={data.mode_label} />
    </div>
  );
}
