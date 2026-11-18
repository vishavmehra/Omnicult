"use client";

import { CircleDashed } from "lucide-react";
import { useState } from "react";

import { LimitationList } from "@/components/evidence/limitation-list";
import { cn } from "@/lib/utils";

import { points } from "./bits";
import type { DimensionScore, ScoreCard, ScoreComparison } from "./types";

/**
 * Version identity in the comparison: a letter, in the order the versions were chosen, on a fixed categorical colour.
 * The first four slots of the validated reference palette (blue, orange, aqua, yellow) clear every adjacent-pair check in both
 * themes. Two light slots sit under 3:1 on the surface, so every bar carries its value and the ledger below repeats all of them.
 */
export const SERIES_VARS =
  "[--s1:#2a78d6] [--s2:#eb6834] [--s3:#1baf7a] [--s4:#eda100] [--s1-ink:#ffffff] [--s2-ink:#ffffff] [--s3-ink:#ffffff] [--s4-ink:#0b0b0b] " +
  "dark:[--s1:#3987e5] dark:[--s2:#d95926] dark:[--s3:#199e70] dark:[--s4:#c98500] dark:[--s4-ink:#ffffff]";

export const LETTERS = ["A", "B", "C", "D"] as const;

export function VersionChip({ index, className }: { index: number; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-flex size-[18px] shrink-0 items-center justify-center rounded-[4px] text-[11px] leading-none font-semibold", className)}
      style={{ background: `var(--s${index + 1})`, color: `var(--s${index + 1}-ink)` }}
    >
      {LETTERS[index]}
    </span>
  );
}

/** What fed one dimension: its rules, the inputs it used with their weights, and the inputs it lacked. */
export function DimensionDetail({ dim }: { dim: DimensionScore }) {
  return (
    <div className="space-y-2.5 text-[13px]">
      <p className="max-w-[68ch] text-ink-body">{dim.explanation}</p>
      <p className="type-ledger text-[12.5px] text-ink-muted">
        Rules applied: <span className="font-mono text-ink-body">{dim.rule_ids.join(", ") || "none"}</span>
      </p>
      {dim.inputs_used.length > 0 && (
        <div className="overflow-x-auto">
          <table className="type-ledger w-full min-w-[30rem] text-left text-[12.5px]">
            <caption className="sr-only">Inputs used for {dim.label}</caption>
            <thead>
              <tr className="border-b border-border text-ink-muted">
                <th scope="col" className="py-1 pr-3 font-normal">Input</th>
                <th scope="col" className="py-1 pr-3 text-right font-normal">Value</th>
                <th scope="col" className="py-1 pr-3 text-right font-normal">Weight</th>
                <th scope="col" className="py-1 font-normal">What it counted</th>
              </tr>
            </thead>
            <tbody className="ledger-rules">
              {dim.inputs_used.map((s) => (
                <tr key={s.signal}>
                  <td className="py-1.5 pr-3 align-top font-mono text-[12px] text-ink-body">{s.signal}</td>
                  <td className="py-1.5 pr-3 text-right align-top tabular-nums text-ink">{points(s.value)}</td>
                  <td className="py-1.5 pr-3 text-right align-top tabular-nums text-ink-body">{s.weight}</td>
                  <td className="py-1.5 align-top text-ink-body">{s.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {dim.missing_inputs.length > 0 && (
        <p className="flex items-start gap-1.5 text-warning">
          <CircleDashed aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          <span>
            Missing inputs: <span className="font-mono">{dim.missing_inputs.join(", ")}</span>
            {dim.value === null ? ". With no primary input, this dimension is not assessed; it is never scored as zero." : "."}
          </span>
        </p>
      )}
    </div>
  );
}

/** One version's five dimensions as ruled rows, each opening to its rules and inputs. The overall comes last, with its coverage. */
export function ScoreCardList({ card }: { card: ScoreCard }) {
  const assessed = card.dimensions.filter((d) => d.value !== null).length;
  return (
    <div className="space-y-3">
      <ul className="ledger-rules rounded-card border border-border">
        {card.dimensions.map((d) => (
          <li key={d.dimension}>
            <details className="group">
              <summary className="flex cursor-pointer flex-wrap items-baseline gap-x-4 gap-y-0.5 px-4 py-2.5 hover:bg-surface-muted/60">
                <span className="min-w-0 flex-1 text-[14px] font-medium text-ink">{d.label}</span>
                <span className={cn("type-ledger text-[13.5px] tabular-nums", d.value === null ? "text-ink-muted" : "text-ink")}>
                  {d.value === null ? "Not assessed" : `${points(d.value)} of 100`}
                </span>
                <span className="type-meta w-24 text-right">weight {d.weight.toFixed(2)}</span>
              </summary>
              <div className="border-t border-border bg-surface-muted/40 px-4 py-3">
                <DimensionDetail dim={d} />
              </div>
            </details>
          </li>
        ))}
      </ul>
      <p className="max-w-[68ch] text-[13px] text-ink-body">
        {card.overall === null ? (
          <>
            <span className="font-medium text-ink">No overall score: </span>
            only {assessed} of {card.dimensions.length} dimensions were assessed, under half of the weight (rule A3_min_coverage).
          </>
        ) : (
          <>
            <span className="font-medium text-ink">Overall {points(card.overall)} of 100, </span>
            the weighted mean of the {assessed} assessed {assessed === 1 ? "dimension" : "dimensions"} (rule A2_overall_weighted_utility)
            {card.complete ? "." : `, covering ${assessed} of ${card.dimensions.length}. Not assessed dimensions are left out, not scored as zero.`}
          </>
        )}
      </p>
    </div>
  );
}

/** Dimension names that a comparison leads or trails on, from the API's values (no thresholds of its own beyond the documented ones). */
export function tradeOffs(comparison: ScoreComparison) {
  const { cards, major_differences: majors, methodology } = comparison;
  const major = methodology.thresholds.major_difference ?? 10;
  const leads = cards.map(() => [] as string[]);
  const trails = cards.map(() => [] as { label: string; gap: number }[]);
  let contested = 0;
  cards[0]?.dimensions.forEach((first, i) => {
    const assessed = cards.map((c) => c.dimensions[i]).filter((d) => d.utility !== null);
    if (assessed.length < 2) return;
    contested += 1;
    const best = Math.max(...assessed.map((d) => d.utility!));
    const worst = Math.min(...assessed.map((d) => d.utility!));
    if (best === worst) return; // a tie leads nowhere
    cards.forEach((c, k) => {
      const d = c.dimensions[i];
      if (d.utility === best) leads[k].push(first.label);
      else if (d.utility !== null && best - d.utility >= major) trails[k].push({ label: first.label, gap: Math.round((best - d.utility) * 10) / 10 });
    });
  });
  const everywhere = leads.findIndex((l) => contested > 0 && l.length === contested);
  return { leads, trails, contested, everywhere, majors };
}

/**
 * One version's bar for a dimension. It grows from its left edge when the block first paints and again each time the pointer
 * enters the row (remounting the fill replays the transform-only `grow-x`). The width is the API's value on the 0 to 100 scale.
 */
function VersionBar({ label, k, value }: { label: string; k: number; value: number | null }) {
  const [replay, setReplay] = useState(0);
  return (
    <li className="group/bar flex items-center gap-2.5" onPointerEnter={() => setReplay((n) => n + 1)}>
      <VersionChip index={k} />
      <span className="sr-only">{label}: </span>
      {value === null ? (
        <span className="flex h-2.5 min-w-0 flex-1 items-center rounded-[4px] border border-dashed border-border-strong/60" aria-hidden />
      ) : (
        <span aria-hidden className="relative flex h-2.5 min-w-0 flex-1 items-center rounded-r-[4px] bg-surface-muted">
          <span className="absolute inset-y-0 left-1/2 w-px bg-border-strong/40" />
          <span
            key={replay}
            className="grow-x relative h-full origin-left rounded-r-[4px] transition-transform duration-200 ease-out group-hover/bar:scale-y-[1.6]"
            style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: `var(--s${k + 1})`, animationDelay: replay === 0 ? `${k * 80}ms` : "0ms" }}
          />
        </span>
      )}
      <span className={cn("type-ledger w-[5.5rem] shrink-0 text-right text-[13px] tabular-nums", value === null ? "text-ink-muted" : "text-ink")}>
        {value === null ? "Not assessed" : points(value)}
      </span>
    </li>
  );
}

/**
 * The per-dimension breakdown: one block per dimension, one horizontal bar per version on a shared 0 to 100 scale, the value at
 * each bar's tip, and a disclosure with the rules and inputs behind every number. A dimension without input shows as not assessed.
 */
export function DimensionBars({ comparison }: { comparison: ScoreComparison }) {
  const { cards } = comparison;
  return (
    <div className={cn("space-y-1", SERIES_VARS)}>
      <ul className="flex flex-wrap gap-x-5 gap-y-1.5 pb-2 text-[13px]" aria-label="Versions compared">
        {cards.map((c, i) => (
          <li key={c.version_id} className="inline-flex items-center gap-1.5 text-ink">
            <VersionChip index={i} />
            <span className="font-medium">{c.label}</span>
          </li>
        ))}
      </ul>
      <p className="type-meta pb-1">Each dimension is scored 0 to 100 on its own. The hairline marks 50. A dashed empty track means the dimension was not assessed.</p>
      <div className="ledger-rules border-y border-border">
        {cards[0].dimensions.map((first, i) => {
          const row = cards.map((c) => c.dimensions[i]);
          const assessed = row.filter((d) => d.utility !== null);
          const best = assessed.length ? Math.max(...assessed.map((d) => d.utility!)) : null;
          const leaders = best !== null && assessed.length > 1 && best !== Math.min(...assessed.map((d) => d.utility!)) ? cards.filter((_, k) => row[k].utility === best) : [];
          const values = assessed.map((d) => d.value!);
          const spread = values.length > 1 ? Math.max(...values) - Math.min(...values) : null;
          return (
            <section key={first.dimension} aria-labelledby={`dim-${first.dimension}`} className="grid gap-x-8 gap-y-3 py-4 lg:grid-cols-[14rem_minmax(0,1fr)]">
              <div className="space-y-0.5">
                <h4 id={`dim-${first.dimension}`} className="text-[14.5px] font-semibold text-ink">{first.label}</h4>
                <p className="type-meta">
                  Weight {first.weight.toFixed(2)} · {first.higher_is_better ? "Higher is better" : "Lower is better"}
                </p>
                <p className="type-meta">
                  {assessed.length < 2
                    ? assessed.length === 1
                      ? "Assessed for one version only"
                      : "Not assessed for any version"
                    : leaders.length
                      ? `Leads: ${leaders.map((c) => LETTERS[cards.indexOf(c)]).join(", ")} · spread ${points(spread)} points`
                      : "Tied"}
                </p>
              </div>
              <div className="min-w-0 space-y-3">
                <ul className="space-y-1.5">
                  {cards.map((c, k) => (
                    <VersionBar key={c.version_id} label={c.label} k={k} value={row[k].value} />
                  ))}
                </ul>
                <details>
                  <summary className="cursor-pointer text-[12.5px] text-ink-secondary hover:text-ink">Rules and inputs behind these values</summary>
                  <div className="mt-2 space-y-4 border-t border-border pt-3">
                    {cards.map((c, k) => (
                      <div key={c.version_id} className="space-y-1.5">
                        <p className="flex items-center gap-1.5 text-[13px] font-medium text-ink">
                          <VersionChip index={k} />
                          {c.label}
                        </p>
                        <DimensionDetail dim={row[k]} />
                      </div>
                    ))}
                  </div>
                </details>
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}

export function CardLimitations({ cards }: { cards: ScoreCard[] }) {
  return (
    <div className={cn("space-y-3", SERIES_VARS)}>
      {cards.map((c, i) => (
        <div key={c.version_id} className="space-y-1.5">
          <p className="flex items-center gap-1.5 text-[13px] font-medium text-ink">
            <VersionChip index={i} />
            {c.label}
          </p>
          <LimitationList items={c.limitations} title="Limitations for this version" />
        </div>
      ))}
    </div>
  );
}
