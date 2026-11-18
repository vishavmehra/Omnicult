"use client";

import { ArrowRight, GitCompareArrows, Hammer } from "lucide-react";
import { useState } from "react";

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

/**
 * Tile positions (column, row) for the 36 states and union territories, laid out roughly as they sit on the map: north at
 * the top, the north-east at the right. Every state gets the same tile, so a small territory is as readable as a large
 * state. No boundary file is used (see the stream notes: the licence is checked, but a boundary map of India has to
 * match the official external boundary, and a tile grid avoids drawing one).
 */
const TILES: Record<string, [number, number]> = {
  JK: [2, 0], LA: [3, 0],
  PB: [1, 1], HP: [2, 1], UT: [3, 1], SK: [6, 1], AR: [9, 1],
  CH: [1, 2], HR: [2, 2], DL: [3, 2], UP: [4, 2], BR: [5, 2], WB: [6, 2], AS: [8, 2], NL: [9, 2],
  RJ: [2, 3], MP: [4, 3], JH: [5, 3], ML: [8, 3], MN: [9, 3],
  GJ: [1, 4], CG: [4, 4], OD: [5, 4], TR: [8, 4], MZ: [9, 4],
  DH: [2, 5], MH: [3, 5], TS: [4, 5],
  GA: [3, 6], AP: [4, 6],
  KA: [3, 7], PY: [4, 7], AN: [9, 7],
  LD: [2, 8], KL: [3, 8], TN: [4, 8],
};
const COLS = 10;
const ROWS = 9;
const suffix = (code: string) => code.split("-")[1] ?? code;

function stateStrength(s: LensAtlasState): Strength {
  return strengthOf(s.strength, s.claims);
}

function Cells({ strength }: { strength: Strength }) {
  const filled = STRENGTH[strength].cells;
  return (
    <span aria-hidden className="flex gap-[3px]">
      {[0, 1, 2].map((i) => (
        <span key={i} className={cn("h-[3px] w-3.5 rounded-full", i < filled ? "bg-ink" : "bg-border-strong/50")} />
      ))}
    </span>
  );
}

function Tile({ state, selected, onSelect }: { state: LensAtlasState; selected: boolean; onSelect(): void }) {
  const strength = stateStrength(state);
  const [col, row] = TILES[suffix(state.code)] ?? [0, 0];
  return (
    <li style={{ gridColumn: col + 1, gridRow: row + 1 }}>
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        aria-label={`${state.name}: evidence ${STRENGTH[strength].label.toLowerCase()}${state.open_conflicts ? `, ${state.open_conflicts} open conflict` : ""}`}
        title={`${state.name}: ${STRENGTH[strength].label}`}
        className={cn(
          "relative flex aspect-square w-full min-w-[2.75rem] flex-col items-center justify-center gap-1.5 rounded-lg border text-ink",
          strength === "none" ? "border-dashed border-border-strong/45 bg-surface-muted/40 text-ink-secondary hover:bg-surface-muted" : "clay border-border hover:bg-surface-raised",
          selected && "outline-2 outline-offset-2 outline-pop",
        )}
      >
        <span className="font-mono text-[12.5px] leading-none font-medium">{suffix(state.code)}</span>
        <Cells strength={strength} />
        {state.open_conflicts > 0 && <GitCompareArrows aria-hidden className="absolute top-1 right-1 size-3 text-warning" />}
      </button>
    </li>
  );
}

function TileMap({ atlas, selected, onSelect }: { atlas: LensAtlas; selected: string | null; onSelect(code: string): void }) {
  return (
    <ul
      aria-label="States and union territories"
      className="hidden gap-1.5 sm:grid"
      style={{ gridTemplateColumns: `repeat(${COLS}, minmax(0, 1fr))`, gridTemplateRows: `repeat(${ROWS}, auto)` }}
    >
      {atlas.states.map((s) => (
        <Tile key={s.code} state={s} selected={s.code === selected} onSelect={() => onSelect(s.code)} />
      ))}
    </ul>
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

export function AtlasView({ campaignId, selected, onSelect, onOpenProfile }: { campaignId: string; selected: string | null; onSelect(code: string): void; onOpenProfile(code: string): void }) {
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
              ? "Demo mode reads labelled fixtures, so nothing is retrieved until you load them. Loading the four demo states is instant and calls nothing."
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
          <TileMap atlas={data} selected={selected} onSelect={onSelect} />
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
