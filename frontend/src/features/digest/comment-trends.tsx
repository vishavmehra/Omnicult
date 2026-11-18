"use client";

import { useId } from "react";

import { ConfidenceIndicator } from "@/components/evidence/confidence";
import { formatDay, niceTicks, regionLabel, shortVersion, sortRegions } from "@/features/pulse/logic";
import { Section } from "@/features/pulse/ui";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/utils";

import { shareText } from "./logic";
import { ModelTag } from "./ui";

type Summary = components["schemas"]["CommentSummary"];
type Slice = components["schemas"]["CommentSlice"];

const W = 640;
const H = 168;
const PAD = { l: 30, r: 8, t: 10, b: 24 };

/** Comments per day as bars: one series, direct tick labels, and the same numbers as a table underneath. */
function VolumeChart({ daily }: { daily: Summary["daily"] }) {
  const max = Math.max(1, ...daily.map((d) => d.comments));
  const ticks = niceTicks(max, 4);
  const top = ticks[ticks.length - 1] || 1;
  const plotW = W - PAD.l - PAD.r;
  const plotH = H - PAD.t - PAD.b;
  const step = plotW / Math.max(1, daily.length);
  const y = (v: number) => PAD.t + plotH * (1 - v / top);
  const total = daily.reduce((a, d) => a + d.comments, 0);
  const busiest = daily.reduce((a, d) => (d.comments > a.comments ? d : a), daily[0]);
  return (
    <figure className="space-y-1">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Comments per day, ${total} in total${busiest ? `, the most on ${formatDay(busiest.date)} with ${busiest.comments}` : ""}.`}
        className="block h-auto w-full max-w-[44rem]"
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeWidth={1} />
            <text x={PAD.l - 6} y={y(t) + 3.5} textAnchor="end" className="fill-ink-muted text-[10px] tabular-nums">
              {t}
            </text>
          </g>
        ))}
        {daily.map((d, i) => {
          const h = (plotH * d.comments) / top;
          return (
            <g key={d.date}>
              <rect x={PAD.l + i * step + step * 0.15} y={PAD.t + plotH - h} width={step * 0.7} height={h} rx={1.5} fill="var(--pulse-s1)">
                <title>{`${formatDay(d.date)}: ${d.comments} ${d.comments === 1 ? "comment" : "comments"}`}</title>
              </rect>
              {i % 7 === 0 && (
                <text x={PAD.l + i * step + step * 0.15} y={H - 7} className="fill-ink-muted text-[10px]">
                  {formatDay(d.date)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <details className="text-[12.5px] text-ink-secondary">
        <summary className="w-fit cursor-pointer rounded-sm py-0.5 hover:text-ink">Show the daily counts as a table</summary>
        <div className="mt-2 max-h-56 max-w-sm overflow-auto rounded-card border border-border">
          <table className="type-ledger w-full text-left text-[12.5px]">
            <caption className="sr-only">Comments per day</caption>
            <thead className="sticky top-0 bg-surface-muted text-ink-secondary">
              <tr>
                <th scope="col" className="px-3 py-1.5 font-medium">
                  Day
                </th>
                <th scope="col" className="px-3 py-1.5 text-right font-medium">
                  Comments
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {daily.map((d) => (
                <tr key={d.date}>
                  <th scope="row" className="px-3 py-1 font-normal">
                    {formatDay(d.date)}
                  </th>
                  <td className="px-3 py-1 text-right tabular-nums">{d.comments}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}

export function VolumeSection({ summary, stale }: { summary: Summary; stale: boolean }) {
  return (
    <Section id="volume" title="Volume over time">
      <div className={cn("space-y-4 transition-opacity", stale && "opacity-60")} aria-busy={stale}>
        {summary.daily.length ? <VolumeChart daily={summary.daily} /> : <p className="text-[13.5px] text-ink-secondary">No comments fall in this period.</p>}
        <div className="relative overflow-x-auto rounded-card border border-border bg-surface">
          <table className="type-ledger w-full min-w-[34rem] text-left text-[13px]">
            <caption className="sr-only">Comments, claim mentions, festival mentions and negative share by week of the run</caption>
            <thead className="bg-surface-muted text-[12px] text-ink-secondary">
              <tr>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  Week of the run
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  Comments
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  Claim mentions
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  Festival mentions
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  <span className="inline-flex flex-wrap items-center justify-end gap-1.5">
                    Negative share <ModelTag />
                  </span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border border-t border-border">
              {summary.weekly.map((w, i) => (
                <tr key={w.week_start}>
                  <th scope="row" className="px-3 py-2 font-normal">
                    <span className="block text-ink">Week {i + 1}</span>
                    <span className="block text-[11.5px] text-ink-muted">
                      {formatDay(w.week_start)} to {formatDay(w.week_end)}
                    </span>
                  </th>
                  <td className="px-3 py-2 text-right tabular-nums text-ink">{w.comments}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{w.claim_mentions}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{w.cultural_mentions}</td>
                  <td className="px-3 py-2 text-right tabular-nums" title={w.read ? `Of ${w.read} comments read in the week` : undefined}>
                    {w.negative_share === null || w.negative_share === undefined ? <span className="text-ink-muted">Not read</span> : shareText(w.negative_share)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Section>
  );
}

const SENTIMENT_COLUMNS = ["positive", "neutral", "negative", "mixed"] as const;

function SentimentCell({ slice, kind }: { slice: Slice; kind: (typeof SENTIMENT_COLUMNS)[number] }) {
  if (!slice.sentiment) return <span className="text-ink-muted">Not read</span>;
  const n = slice.sentiment[kind];
  const share = kind === "positive" ? slice.positive_share : kind === "negative" ? slice.negative_share : null;
  return (
    <span className="tabular-nums">
      {n}
      {share !== null && share !== undefined && <span className="ml-1 text-[11.5px] text-ink-muted">({shareText(share)})</span>}
    </span>
  );
}

/** One row per region and version, the unit a reader compares. Counts are code; the four sentiment columns are the model's reading. */
export function SlicesTable({ summary, stale }: { summary: Summary; stale: boolean }) {
  const caption = useId();
  const slices = sortRegions([...summary.slices].sort((a, b) => a.version_label.localeCompare(b.version_label)), (s) => s.region_code);
  return (
    <Section id="slices" title="By region and version">
      <div className={cn("relative overflow-x-auto rounded-card border border-border bg-surface transition-opacity", stale && "opacity-60")} aria-busy={stale}>
        <table className="type-ledger w-full min-w-[46rem] text-left text-[13px]" aria-labelledby={caption}>
          <caption id={caption} className="sr-only">
            Comments, mentions and sentiment by region and version
          </caption>
          <thead className="bg-surface-muted text-[12px] text-ink-secondary">
            <tr>
              <th scope="col" rowSpan={2} className="sticky left-0 bg-surface-muted px-3 py-2.5 align-bottom font-medium">
                Region and version
              </th>
              <th scope="col" rowSpan={2} className="px-3 py-2.5 text-right align-bottom font-medium">
                Comments
              </th>
              <th scope="col" rowSpan={2} className="px-3 py-2.5 text-right align-bottom font-medium">
                Claim
              </th>
              <th scope="col" rowSpan={2} className="px-3 py-2.5 text-right align-bottom font-medium">
                Festival
              </th>
              <th scope="colgroup" colSpan={4} className="px-3 pt-2.5 pb-1 text-right font-medium">
                <span className="inline-flex items-center gap-1.5">
                  Sentiment <ModelTag />
                </span>
              </th>
              <th scope="col" rowSpan={2} className="px-3 py-2.5 align-bottom font-medium">
                Confidence
              </th>
            </tr>
            <tr>
              {SENTIMENT_COLUMNS.map((k) => (
                <th key={k} scope="col" className="px-3 pt-0 pb-2 text-right font-medium capitalize">
                  {k}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border border-t border-border">
            {slices.map((s) => (
              <tr key={`${s.region_code}|${s.version_label}`}>
                <th scope="row" className="sticky left-0 bg-surface px-3 py-2 font-normal">
                  <span className="block text-ink">
                    {regionLabel(s.region_code, { [s.region_code]: s.region_name })}, {shortVersion(s.version_label)}
                  </span>
                  <span className="block font-mono text-[11px] text-ink-muted">
                    {s.region_code} · {s.version_label.split(" ")[0]}
                  </span>
                </th>
                <td className="px-3 py-2 text-right tabular-nums text-ink">{s.comments}</td>
                <td className="px-3 py-2 text-right tabular-nums">{s.claim_mentions || <span className="text-ink-muted">0</span>}</td>
                <td className="px-3 py-2 text-right tabular-nums">{s.cultural_mentions || <span className="text-ink-muted">0</span>}</td>
                {SENTIMENT_COLUMNS.map((k) => (
                  <td key={k} className="px-3 py-2 text-right">
                    <SentimentCell slice={s} kind={k} />
                  </td>
                ))}
                <td className="px-3 py-2">
                  <span title={s.confidence_rule}>
                    <ConfidenceIndicator level={s.confidence} showRule={false} />
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="max-w-[78ch] text-[12.5px] leading-snug text-ink-secondary">
        Sentiment is a model&apos;s label of each comment, and the shares count only the comments it labelled. A slice with few comments is a thin signal; {summary.is_sample ? "comments written for this demo" : "public comments"} never rate above Moderate.
      </p>
    </Section>
  );
}
