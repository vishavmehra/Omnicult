"use client";

import { CircleCheck, Info, LoaderCircle, PencilLine, Scale, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { workspaceHref } from "@/components/shell/workspaces";
import { Button, buttonVariants } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useCampaign } from "@/features/workspaces/campaign-context";
import { SectionTitle } from "@/features/workspaces/parts";
import { cn } from "@/lib/utils";

import { useCompareScores, useRegions, useVersionOptions } from "./api";
import { InputSummary, NativeSelect, points, WIDE_SHEET } from "./bits";
import { useInputs } from "./inputs-store";
import { ObservationEditor } from "./observation-editor";
import { GROUP_LABEL, toObservations } from "./observations";
import { CardLimitations, DimensionBars, LETTERS, SERIES_VARS, tradeOffs, VersionChip } from "./score-parts";
import { useRegionChoices } from "./region-choices";
import type { ScoreComparison } from "./types";
import { VersionCopy } from "./version-copy";

const MAX_VERSIONS = 4;

/** Compare and Score (feature 36): choose a region and 2 to 4 versions, supply their observations, read the per-dimension breakdown. */
export function CompareTab() {
  const { campaign } = useCampaign();
  const versions = useVersionOptions();
  const regions = useRegions();
  const choices = useRegionChoices(regions.data);
  const store = useInputs();
  const compare = useCompareScores(campaign.id);
  const [regionCode, setRegionCode] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [editing, setEditing] = useState<string | null>(null);

  const optionById = useMemo(() => new Map(versions.options.map((o) => [o.id, o])), [versions.options]);
  const regionName = regions.data?.find((r) => r.code === regionCode)?.name ?? regionCode;

  // The request exactly as it would be sent now, with per-version problems found before sending.
  const request = useMemo(() => {
    const problems: string[] = [];
    const entries = chosen.map((id) => {
      const { value, problems: p } = toObservations(store.get(id, regionCode));
      const label = optionById.get(id)?.label ?? "Version";
      for (const [group, message] of Object.entries(p)) {
        problems.push(`${label}, ${GROUP_LABEL[group as keyof typeof GROUP_LABEL] ?? "Open conflicts"}: ${message}`);
      }
      return { version_id: id, label: label.slice(0, 60), observations: value };
    });
    return { problems, body: { region_code: regionCode, scoring_version: "mvp-2" as const, versions: entries } };
  }, [chosen, regionCode, store, optionById]);

  if (versions.error) return <ErrorState error={versions.error} onRetry={() => void versions.refetch()} />;
  if (versions.isPending) return <LoadingState label="Reading this campaign’s versions…" />;

  if (versions.options.length < 2) {
    return (
      <EmptyState
        title="Compare and Score needs at least two versions"
        description="It scores versions of the same creative side by side under fixed rules. This campaign has fewer than two, so there is nothing to compare yet."
        needs={[
          { label: `Two or more creative versions (this campaign has ${versions.options.length})`, met: false },
          { label: "A region to score them in", met: Boolean(regions.data?.length) },
          { label: "Observations for each version: a Quick Read, a Risk Check, transcreation checks, objective checks and the region’s Evidence Meter (entered here or gathered)" },
        ]}
        action={
          <Link href={workspaceHref(campaign.id, "studio")} className={buttonVariants({ variant: "outline", size: "sm" })}>
            Open Creative Studio to make a version
          </Link>
        }
      />
    );
  }

  const stale = compare.data && JSON.stringify(compare.variables) !== JSON.stringify(request.body);
  const ready = chosen.length >= 2 && regionCode !== "" && request.problems.length === 0;
  const editingOption = editing ? optionById.get(editing) : undefined;

  function toggle(id: string, on: boolean) {
    setChosen((prev) => (on ? (prev.length < MAX_VERSIONS && !prev.includes(id) ? [...prev, id] : prev) : prev.filter((x) => x !== id)));
  }

  return (
    <div className="space-y-8">
      <section aria-labelledby="compare-setup" className="space-y-4">
        <SectionTitle id="compare-setup">Set up a comparison</SectionTitle>
        <div className="max-w-sm space-y-1.5">
          <label htmlFor="compare-region" className="block text-[13px] font-medium text-ink">Region</label>
          <NativeSelect id="compare-region" value={regionCode} onChange={(e) => setRegionCode(e.target.value)} disabled={regions.isPending}>
            <option value="">{regions.isPending ? "Loading regions…" : "Choose a region"}</option>
            {choices.map((g) => (
              <optgroup key={g.label} label={g.label}>
                {g.regions.map((r) => (
                  <option key={r.code} value={r.code}>{r.name} ({r.code})</option>
                ))}
              </optgroup>
            ))}
          </NativeSelect>
          {regions.error && <p role="alert" className="text-xs font-medium text-danger">The region list could not be loaded. Reload to try again.</p>}
          <p className="text-xs text-ink-secondary">Every version is scored in this one region, so the comparison is like for like.</p>
        </div>

        <fieldset className="space-y-2">
          <legend className="text-[13px] font-medium text-ink">Versions (choose 2 to {MAX_VERSIONS})</legend>
          <ul className="ledger-rules rounded-card border border-border bg-surface">
            {versions.options.map((o) => {
              const index = chosen.indexOf(o.id);
              const on = index >= 0;
              const full = !on && chosen.length >= MAX_VERSIONS;
              return (
                <li key={o.id} className="space-y-2 px-4 py-3">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <label className={cn("flex min-w-0 flex-1 items-center gap-2.5 text-[14px]", full ? "cursor-not-allowed text-ink-muted" : "cursor-pointer text-ink")}>
                      <Checkbox checked={on} disabled={full} onCheckedChange={(v) => toggle(o.id, v === true)} />
                      <span className={cn("flex items-center gap-1.5", SERIES_VARS)}>
                        {on && <VersionChip index={index} />}
                      </span>
                      <span className="min-w-0 truncate font-medium">{o.label}</span>
                      <span className="type-meta shrink-0">{o.source === "studio" ? "Creative Studio" : "Campaign content"}{o.regionCode ? ` · ${o.regionCode}` : ""}</span>
                    </label>
                    {on && (
                      <Button size="sm" variant="outline" disabled={!regionCode} onClick={() => setEditing(o.id)}>
                        <PencilLine aria-hidden />
                        Edit inputs
                      </Button>
                    )}
                  </div>
                  {on && regionCode && <InputSummary draft={store.get(o.id, regionCode)} />}
                  {on && !regionCode && <p className="text-[12.5px] text-ink-secondary">Choose a region first: observations belong to a version in a region.</p>}
                </li>
              );
            })}
          </ul>
          {atLimit(chosen) && <p className="text-xs text-ink-secondary">Four versions is the most one comparison takes.</p>}
        </fieldset>

        {request.problems.length > 0 && (
          <div role="alert" className="max-w-prose rounded-lg border border-danger/35 bg-danger-soft/60 px-3.5 py-2.5 text-[13px] text-ink">
            <p className="font-semibold">Some inputs cannot be sent as typed</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              {request.problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button size="lg" disabled={!ready || compare.isPending} onClick={() => compare.mutate(request.body)}>
            {compare.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <Scale aria-hidden />}
            {compare.isPending ? "Scoring…" : "Compare versions"}
          </Button>
          <p className="max-w-prose text-[13px] text-ink-secondary">
            {chosen.length < 2
              ? "Choose at least two versions."
              : !regionCode
                ? "Choose a region."
                
                : "Nothing is stored and no model is called. A dimension with no input is shown as not assessed, never as zero."}
          </p>
        </div>
      </section>

      {compare.error && <ErrorState error={compare.error} onRetry={() => compare.mutate(request.body)} />}

      {compare.data ? (
        <ComparisonResults comparison={compare.data} regionName={regionName} stale={Boolean(stale)} />
      ) : (
        !compare.isPending && (
          <EmptyState
            title="No comparison yet"
            description={
              <>
                Pick a region and at least two versions, supply or gather each version’s observations, then compare. You get the five dimensions side by side
                (message clarity .25, brand fidelity .20, cultural relevance .25, sensitivity risk .20, objective consistency .10), the trade-offs between the
                versions, and a ranking that says whether the comparison is like for like.
              </>
            }
          />
        )
      )}

      <Sheet open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        <SheetContent className={cn("overflow-y-auto", WIDE_SHEET)}>
          <SheetHeader>
            <SheetTitle>Inputs for {editingOption?.label ?? "version"}</SheetTitle>
            <SheetDescription>Observations for this version in {regionName || "the chosen region"}. They are remembered in this browser and reused by the Readiness Board.</SheetDescription>
          </SheetHeader>
          <div className="px-4">{editing && regionCode && <ObservationEditor versionId={editing} regionCode={regionCode} />}</div>
          <SheetFooter>
            <Button onClick={() => setEditing(null)}>Done</Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </div>
  );
}

const atLimit = (chosen: string[]) => chosen.length >= MAX_VERSIONS;

type Cards = ScoreComparison["cards"];
const recorded = (cards: Cards, key: "model_id" | "prompt_version" | "criteria_version" | "evidence_snapshot") =>
  cards.some((c) => Boolean(c.provenance[key]));

function ComparabilityBlock({ comparison }: { comparison: ScoreComparison }) {
  const { cards, comparability: c } = comparison;
  const letter = (i: number) => LETTERS[i];
  const list = (key: "model_id" | "prompt_version" | "criteria_version" | "evidence_snapshot") =>
    cards.map((card, i) => `${letter(i)}: ${card.provenance[key] ?? "not recorded"}`).join(" · ");
  const rows: { label: string; same: boolean; detail: string }[] = [
    { label: "Scoring version", same: c.same_scoring_version, detail: c.same_scoring_version ? comparison.scoring_version : cards.map((x, i) => `${letter(i)}: ${x.scoring_version}`).join(" · ") },
    ...(
      [
        ["Model", "same_model", "model_id"],
        ["Prompt version", "same_prompt_version", "prompt_version"],
        ["Evaluation criteria", "same_criteria", "criteria_version"],
        ["Evidence", "same_evidence", "evidence_snapshot"],
      ] as const
    ).map(([label, flag, key]) => ({
      label,
      same: c[flag],
      detail: !c[flag] ? list(key) : recorded(cards, key) ? String(cards[0].provenance[key]) : "Not recorded for any version",
    })),
    {
      label: "Dimensions assessed",
      same: c.same_dimensions_assessed,
      detail: c.same_dimensions_assessed
        ? `The same ${cards[0].dimensions.filter((d) => d.value !== null).length} of ${cards[0].dimensions.length}`
        : cards.map((x, i) => `${letter(i)}: ${x.dimensions.filter((d) => d.value !== null).length} of ${x.dimensions.length}`).join(" · "),
    },
  ];
  return (
    <div className="space-y-3">
      <p className={cn("flex items-start gap-2 text-[14px] font-medium", c.comparable ? "text-success" : "text-warning")}>
        {c.comparable ? <CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0" /> : <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />}
        <span>
          {c.comparable ? "Comparable: everything below matches." : "Not like for like: the ranking reflects these differences as well as the creative."}
        </span>
      </p>
      <dl className="ledger-rules rounded-card border border-border bg-surface">
        {rows.map((r) => (
          <div key={r.label} className="grid gap-1 px-4 py-2.5 sm:grid-cols-[11rem_7rem_minmax(0,1fr)] sm:gap-4">
            <dt className="type-ledger text-[12.5px] text-ink-muted">{r.label}</dt>
            <dd className={cn("inline-flex items-center gap-1.5 text-[13px] font-medium", r.same ? "text-ink" : "text-warning")}>
              {r.same ? <CircleCheck aria-hidden className="size-3.5" /> : <TriangleAlert aria-hidden className="size-3.5" />}
              {r.same ? "Same" : "Differs"}
            </dd>
            <dd className="min-w-0 text-[13px] break-words text-ink-body">{r.detail}</dd>
          </div>
        ))}
      </dl>
      {c.notes.length > 0 && (
        <ul className="max-w-prose list-disc space-y-1 pl-5 text-[13px] text-ink-body">
          {c.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ComparisonResults({ comparison, regionName, stale }: { comparison: ScoreComparison; regionName: string; stale: boolean }) {
  const { cards, ranking, methodology } = comparison;
  const index = new Map(cards.map((c, i) => [c.version_id, i]));
  const t = tradeOffs(comparison);
  const margin = methodology.thresholds.meaningful_margin ?? 5;
  const major = methodology.thresholds.major_difference ?? 10;
  const topGap = ranking[0]?.overall !== null && ranking[1]?.overall !== null ? (ranking[0].overall ?? 0) - (ranking[1].overall ?? 0) : null;

  return (
    <div className={cn("space-y-9", SERIES_VARS)} aria-label="Comparison results">
      <div className="space-y-2 border-t border-border pt-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="type-title text-[24px] text-ink">Comparison in {regionName}</h2>
          <span className="type-meta">Scoring {comparison.scoring_version}</span>
        </div>
        {stale && (
          <p role="status" className="flex items-start gap-2 text-[13px] text-warning">
            <Info aria-hidden className="mt-0.5 size-4 shrink-0" />
            The choices or inputs have changed since this comparison. Compare again to refresh it.
          </p>
        )}
      </div>

      <section aria-labelledby="r-breakdown" className="space-y-2">
        <SectionTitle id="r-breakdown" meta="Five dimensions, fixed weights">Per-dimension breakdown</SectionTitle>
        <DimensionBars comparison={comparison} />
      </section>

      <section aria-labelledby="r-tradeoffs" className="space-y-3">
        <SectionTitle id="r-tradeoffs" meta="Derived from the values above">Trade-offs between versions</SectionTitle>
        {t.contested === 0 ? (
          <p className="text-[13.5px] text-ink-secondary">No dimension was assessed for more than one version, so there is nothing to trade off yet.</p>
        ) : (
          <>
            <p className="max-w-[68ch] text-[14px] text-ink">
              {t.everywhere >= 0
                ? `${cards[t.everywhere].label} leads on every dimension assessed for more than one version. That is a lead under fixed rules, not proof it will do better with real people.`
                : "No version leads on every dimension. Read this as a trade-off between versions rather than a single winner."}
            </p>
            <ul className="ledger-rules rounded-card border border-border bg-surface">
              {cards.map((c, i) => (
                <li key={c.version_id} className="grid gap-1.5 px-4 py-3 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-4">
                  <p className="flex min-w-0 items-center gap-2 text-[14px] font-medium text-ink">
                    <VersionChip index={i} />
                    <span className="min-w-0 break-words">{c.label}</span>
                  </p>
                  <div className="space-y-0.5 text-[13.5px] text-ink-body">
                    <p>
                      <span className="text-ink-muted">Leads on: </span>
                      {t.leads[i].length ? t.leads[i].join(", ") : "no dimension"}
                    </p>
                    <p>
                      <span className="text-ink-muted">Trails by {major} points or more on: </span>
                      {t.trails[i].length ? t.trails[i].map((x) => `${x.label} (${points(x.gap)})`).join(", ") : "no dimension"}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section aria-labelledby="r-ranking" className="space-y-3">
        <SectionTitle id="r-ranking" meta="Weighted by the fixed weights">Ranking</SectionTitle>
        <ol className="ledger-rules rounded-card border border-border bg-surface">
          {ranking.map((r) => {
            const card = cards[index.get(r.version_id) ?? 0];
            const assessed = card.dimensions.filter((d) => d.value !== null).length;
            return (
              <li key={r.version_id} className="grid grid-cols-[2rem_minmax(0,1fr)_auto] items-baseline gap-x-3 gap-y-0.5 px-4 py-2.5">
                <span className="font-mono text-[12.5px] text-ink-muted">{r.rank}</span>
                <span className="flex min-w-0 items-center gap-2 text-[14px] font-medium text-ink">
                  <VersionChip index={index.get(r.version_id) ?? 0} />
                  <span className="truncate">{r.label}</span>
                </span>
                <span className="type-ledger text-[13.5px] tabular-nums text-ink">{r.overall === null ? "No overall score" : `${points(r.overall)} of 100`}</span>
                <span />
                <span className="type-meta col-span-2">
                  {card.complete ? `All ${assessed} dimensions assessed` : `${assessed} of ${card.dimensions.length} dimensions assessed, covering weight ${card.coverage.toFixed(2)}`}
                </span>
              </li>
            );
          })}
        </ol>
        <p className="max-w-[68ch] text-[13.5px] text-ink-body">
          {topGap === null
            ? `The top two versions do not both have an overall score, so there is no margin to read.`
            : comparison.meaningful_margin
              ? `The top two differ by ${points(topGap)} points, at least the documented margin of ${margin}.`
              : `The top two differ by ${points(topGap)} points, under the documented margin of ${margin}: treat that as no meaningful difference.`}{" "}
          Ties on the overall score are ordered by lower sensitivity risk.
          {!comparison.comparability.comparable && " This is not a like-for-like comparison; see Comparability below."}
        </p>
      </section>

      <section aria-labelledby="r-major" className="space-y-3">
        <SectionTitle id="r-major" meta={`Gaps of ${major} points or more`}>Major differences</SectionTitle>
        {comparison.major_differences.length === 0 ? (
          <p className="text-[13.5px] text-ink-secondary">No dimension differs by {major} points or more between versions.</p>
        ) : (
          <ul className="ledger-rules rounded-card border border-border bg-surface">
            {comparison.major_differences.map((d) => (
              <li key={d.dimension} className="space-y-1 px-4 py-3">
                <p className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-[14px] font-medium text-ink">{d.label}</span>
                  <span className="type-ledger text-[13px] tabular-nums text-ink">{points(d.spread)} points apart</span>
                </p>
                <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-ink-body">
                  {d.values.map((v) => (
                    <span key={v.version_id} className="inline-flex items-center gap-1.5">
                      <VersionChip index={index.get(v.version_id) ?? 0} />
                      <span className="tabular-nums">{v.value === null ? "Not assessed" : points(v.value)}</span>
                    </span>
                  ))}
                  <span className="text-ink-muted">
                    {d.leader_version_id ? `Leads: ${LETTERS[index.get(d.leader_version_id) ?? 0]}` : ""}
                  </span>
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="r-comparable" className="space-y-3">
        <SectionTitle id="r-comparable" meta="What could explain a gap other than the creative">Comparability</SectionTitle>
        <ComparabilityBlock comparison={comparison} />
      </section>

      <section aria-labelledby="r-copy" className="space-y-3">
        <SectionTitle id="r-copy" meta="The words behind the scores">What each version says</SectionTitle>
        <VersionCopy versionIds={cards.map((c) => c.version_id)} labels={cards.map((c) => c.label)} />
      </section>

      <section aria-labelledby="r-limits" className="space-y-3">
        <SectionTitle id="r-limits">Limitations and method</SectionTitle>
        <details className="rounded-card border border-border bg-surface px-4 py-3">
          <summary className="cursor-pointer text-[14px] font-medium text-ink">Limitations for each version</summary>
          <div className="mt-3">
            <CardLimitations cards={cards} />
          </div>
        </details>
        <details className="rounded-card border border-border bg-surface px-4 py-3">
          <summary className="cursor-pointer text-[14px] font-medium text-ink">Scoring methodology {methodology.version}</summary>
          <div className="mt-3 space-y-4 text-[13px] text-ink-body">
            <p>
              <span className="font-medium text-ink">Scale: </span>
              {methodology.scale}. <span className="font-medium text-ink">Aggregation: </span>
              {methodology.aggregation}
            </p>
            <div className="overflow-x-auto">
              <table className="type-ledger w-full min-w-[32rem] text-left text-[12.5px]">
                <caption className="sr-only">Dimensions and weights</caption>
                <thead>
                  <tr className="border-b border-border text-ink-muted">
                    <th scope="col" className="py-1 pr-3 font-normal">Dimension</th>
                    <th scope="col" className="py-1 pr-3 text-right font-normal">Weight</th>
                    <th scope="col" className="py-1 font-normal">Definition</th>
                  </tr>
                </thead>
                <tbody className="ledger-rules">
                  {methodology.dimensions.map((d) => (
                    <tr key={d.dimension}>
                      <td className="py-1.5 pr-3 align-top text-ink">{d.label}{d.higher_is_better ? "" : " (lower is better)"}</td>
                      <td className="py-1.5 pr-3 text-right align-top tabular-nums">{d.weight.toFixed(2)}</td>
                      <td className="py-1.5 align-top">{d.definition}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="space-y-1">
              {methodology.rules.map((r) => (
                <li key={r.rule_id}>
                  <span className="font-mono text-[12px] text-ink">{r.rule_id}</span> <span className="text-ink-muted">({r.applies_to})</span> {r.description}
                </li>
              ))}
            </ul>
            <p>
              <span className="font-medium text-ink">Thresholds: </span>
              {Object.entries(methodology.thresholds).map(([k, v]) => `${k} ${v}`).join(" · ")}
            </p>
            <ul className="list-disc space-y-1 pl-5">
              {[...methodology.limitations, ...comparison.notes].map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </div>
        </details>
      </section>

      <p className="type-meta">Scores computed by fixed rules ({comparison.scoring_version}).</p>
    </div>
  );
}
