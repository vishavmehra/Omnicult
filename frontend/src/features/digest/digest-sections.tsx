"use client";

import { ArrowUpRight, CircleDollarSign, Repeat, TrendingDown, type LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Tag } from "@/components/evidence/badges";
import { formatDay, formatPctChange, formatValue, judge, regionLabel, shortVersion } from "@/features/pulse/logic";
import { Section } from "@/features/pulse/ui";
import { formatDateTime } from "@/lib/format";

import { changeTotal, PRIORITY_LABEL, SENTIMENT_LABEL, SENTIMENTS, sourceHref, WORKSPACE_LABEL, type DigestContent, type DigestSource } from "./logic";
import { ModelTag, Move, SourceLine } from "./ui";

type Pulse = DigestContent["pulse"];
const ALERT_ICON: Record<Pulse["alerts"][number]["alert_type"], LucideIcon> = { ctr_drop: TrendingDown, frequency_fatigue: Repeat, cost_spike: CircleDollarSign };
const VERDICT_LABEL = { go: "Go", fix: "Fix", rethink: "Rethink" } as const;

function Open({ campaignId, source, label }: { campaignId: string; source: DigestSource; label?: string }) {
  return (
    <Link href={sourceHref(campaignId, source)} className="inline-flex items-center gap-0.5 rounded-sm text-[12.5px] text-rose hover:underline">
      {label ?? `Open ${WORKSPACE_LABEL[source.workspace]}`}
      <ArrowUpRight aria-hidden className="size-3.5" />
    </Link>
  );
}

/** A region label that is not repeated when the version's own label already names the region ("Kerala: unsourced claim replaced"). */
const placed = (region: string, version: string) => (version.includes(region) ? version : `${region}, ${version}`);

const Empty = ({ children }: { children: ReactNode }) => <p className="text-[13.5px] text-ink-secondary">{children}</p>;

// ---------------------------------------------------------------- what changed

export function WhatChanged({ campaignId, content }: { campaignId: string; content: DigestContent }) {
  const w = content.what_changed;
  const c = w.counts;
  const rows: [string, string][] = [
    ["Creative versions created", String(c.creative_versions)],
    ["Readiness verdicts computed", String(c.verdicts)],
    ["Approvals recorded", String(c.approvals)],
    ["Runs started", `${c.agent_runs + c.audience_runs}`],
    ["Evidence conflicts opened and resolved", `${c.conflicts_opened} and ${c.conflicts_resolved}`],
    ["Risk Check findings recorded", String(c.risk_findings)],
  ];
  return (
    <Section id="changed" title="What changed" meta={<span>{content.week.start === content.week.end ? "" : `${formatDay(content.week.start)} to ${formatDay(content.week.end)}`}</span>}>
      {changeTotal(content) === 0 ? (
        <Empty>Nothing was recorded this week: no new creative version, verdict, approval, run or conflict.</Empty>
      ) : (
        <>
          <dl className="ledger-rules rounded-card border border-border bg-surface">
            {rows.map(([label, value]) => (
              <div key={label} className="flex items-baseline justify-between gap-4 px-4 py-2">
                <dt className="type-ledger text-[13px] text-ink-secondary">{label}</dt>
                <dd className="type-ledger text-[14px] text-ink tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
          {w.versions.length > 0 && (
            <ul className="space-y-1 text-[13.5px]">
              {w.versions.map((v) => (
                <li key={v.id} className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-ink">{v.label}</span>
                  <span className="type-meta">
                    {v.actor === "ai" ? "AI operation" : "Person"}
                    {v.region_code ? ` · ${regionLabel(v.region_code)}` : ""}
                  </span>
                  <Open campaignId={campaignId} source={v.source} label="Open version" />
                </li>
              ))}
            </ul>
          )}
          {w.verdicts.length > 0 && (
            <ul className="space-y-1 text-[13.5px]">
              {w.verdicts.map((v) => (
                <li key={`${v.region_code}-${v.computed_at}-${v.version_label}`} className="flex flex-wrap items-baseline gap-x-2">
                  <Tag className="border-border bg-surface-muted text-ink">{VERDICT_LABEL[v.verdict]}</Tag>
                  <span className="text-ink">{placed(v.region_name, v.version_label)}</span>
                  <span className="text-ink-secondary">{v.main_reason}</span>
                </li>
              ))}
            </ul>
          )}
          {w.truncated && <p className="type-meta">Showing the newest records of the week.</p>}
        </>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------- pulse movement and alerts

const METRIC_ORDER = ["impressions", "spend", "ctr", "cpm", "cpa", "roas"];

export function PulseMovement({ campaignId, content }: { campaignId: string; content: DigestContent }) {
  const p = content.pulse;
  return (
    <Section id="pulse" title="Pulse movement and alerts">
      {!p.available ? (
        <Empty>{p.reason ?? "No Live Pulse movement is available."}</Empty>
      ) : (
        <>
          <p className="type-meta">
            The 7 settled days {formatDay(p.window_from!)} to {formatDay(p.window_to!)}
            {p.previous_from ? `, against ${formatDay(p.previous_from)} to ${formatDay(p.previous_to!)}` : ", with no full earlier week to compare"}.
            {p.provisional_days_excluded > 0 ? ` ${p.provisional_days_excluded} provisional ${p.provisional_days_excluded === 1 ? "day is" : "days are"} left out.` : ""}
          </p>
          <div className="relative overflow-x-auto rounded-card border border-border bg-surface">
            <table className="type-ledger w-full min-w-[40rem] text-left text-[13px]">
              <caption className="sr-only">Pulse metrics by region and version for the 7 settled days, with the change against the week before</caption>
              <thead className="bg-surface-muted text-[12px] text-ink-secondary">
                <tr>
                  <th scope="col" className="sticky left-0 bg-surface-muted px-3 py-2.5 font-medium">
                    Region and version
                  </th>
                  {METRIC_ORDER.map((m) => (
                    <th key={m} scope="col" className="px-3 py-2.5 text-right font-medium">
                      {p.slices[0]?.metrics.find((x) => x.metric === m)?.label ?? m}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border border-t border-border">
                {p.slices.map((s) => (
                  <tr key={`${s.region_code}|${s.version_label}`}>
                    <th scope="row" className="sticky left-0 bg-surface px-3 py-2 font-normal">
                      <span className="block text-ink">
                        {s.region_name}, {shortVersion(s.version_label)}
                      </span>
                      <span className="block font-mono text-[11px] text-ink-muted">{s.region_code}</span>
                    </th>
                    {METRIC_ORDER.map((name) => {
                      const m = s.metrics.find((x) => x.metric === name);
                      if (!m) return <td key={name} />;
                      const j = judge(name, m.delta_pct, m.delta);
                      return (
                        <td key={name} className="px-3 py-2 text-right align-top">
                          <span className="block text-ink tabular-nums">{formatValue(m.current, m.unit, { compact: true })}</span>
                          {m.delta_pct !== null && m.delta_pct !== undefined && (
                            <Move text={formatPctChange(m.delta_pct)} direction={m.delta_pct > 0 ? "up" : m.delta_pct < 0 ? "down" : "flat"} judgement={j} />
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {p.alerts.length === 0 ? (
            <Empty>No Pulse alert fired for the data up to {formatDay(p.settled_through!)}.</Empty>
          ) : (
            <ul className="ledger-rules rounded-card border border-border bg-surface">
              {p.alerts.map((a) => {
                const Icon = ALERT_ICON[a.alert_type];
                return (
                  <li key={`${a.alert_type}-${a.region_code}-${a.version_label}`} className="flex gap-3 px-4 py-3">
                    <Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" />
                    <div className="min-w-0 space-y-0.5 text-[13.5px]">
                      <p className="text-ink">
                        {a.region_name}, {shortVersion(a.version_label)}: {a.headline}
                      </p>
                      <p className="text-ink-secondary">{a.suggested_action}</p>
                      <Open campaignId={campaignId} source={{ workspace: "pulse", view: null, ref: null }} />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------- comments

export function CommentsSection({ campaignId, content }: { campaignId: string; content: DigestContent }) {
  const c = content.comments;
  return (
    <Section id="digest-comments" title="Comments">
      {!c.available ? (
        <Empty>{c.reason ?? "No comments are available."}</Empty>
      ) : (
        <>
          <p className="text-[13.5px] text-ink-body">
            {c.comments_in_window} {c.comments_in_window === 1 ? "comment" : "comments"} posted {formatDay(c.window_from!)} to {formatDay(c.window_to!)}: {c.claim_mentions_in_window} mention the unsourced claim and{" "}
            {c.cultural_mentions_in_window} name a different festival.{" "}
            <Open campaignId={campaignId} source={{ workspace: "pulse", view: "comments", ref: null }} label="Open Comment Pulse" />
          </p>
          {c.sentiment && (
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-ink-secondary">
              <ModelTag />
              {SENTIMENTS.map((k) => `${c.sentiment![k]} ${SENTIMENT_LABEL[k].toLowerCase()}`).join(", ")}
              {c.sentiment.unread ? `, ${c.sentiment.unread} unread` : ""}
            </p>
          )}
          {c.themes.length > 0 && (
            <ul className="ledger-rules rounded-card border border-border bg-surface">
              {c.themes.map((t) => (
                <li key={t.id} className="space-y-1 px-4 py-3">
                  <p className="flex flex-wrap items-baseline gap-x-2 text-[14px]">
                    <span className="font-medium text-ink">{t.label}</span>
                    <span className="type-meta">{t.comments} comments</span>
                    <ModelTag />
                  </p>
                  <p className="text-[13.5px] text-ink-secondary">{t.summary}</p>
                  {t.quote && (
                    <blockquote lang={t.quote.language} className="border-l-2 border-border-strong pl-3 text-[13.5px] text-ink-body">
                      {t.quote.text}
                    </blockquote>
                  )}
                </li>
              ))}
            </ul>
          )}
          {c.flagged.length > 0 && (
            <ul className="space-y-2">
              {c.flagged.map((f) => (
                <li key={f.id} className="rounded-lg border border-border bg-surface px-3 py-2">
                  <p lang={f.language} className="text-[14px] text-ink">
                    {f.text}
                  </p>
                  <p className="type-meta mt-0.5">
                    {regionLabel(f.region_code)}, {shortVersion(f.version_label)} · matches {f.label} · {f.likes} {f.likes === 1 ? "like" : "likes"}
                  </p>
                </li>
              ))}
            </ul>
          )}
          <SourceLine>{c.source}</SourceLine>
        </>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------- open items and next actions

export function OpenItems({ campaignId, content }: { campaignId: string; content: DigestContent }) {
  const o = content.open_items;
  const none = !o.conflicts.length && !o.risk_findings.length && !o.not_ready.length;
  return (
    <Section id="open" title="Open conflicts and issues" meta={<span>As of {formatDateTime(o.as_of)}</span>}>
      {none ? (
        <Empty>Nothing is open: no evidence conflict, no open Risk Check finding and no region short of Go.</Empty>
      ) : (
        <ul className="ledger-rules rounded-card border border-border bg-surface">
          {o.not_ready.map((n) => (
            <li key={`${n.region_code}-${n.version_label}`} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-4 py-2.5 text-[13.5px]">
              <Tag className="border-border bg-surface-muted text-ink">{VERDICT_LABEL[n.verdict]}</Tag>
              <span className="text-ink">{placed(n.region_name, n.version_label)} is not ready</span>
              <span className="basis-full text-ink-secondary sm:basis-auto">{n.main_reason}</span>
              <Open campaignId={campaignId} source={n.source} />
            </li>
          ))}
          {o.risk_findings.map((f) => (
            <li key={f.id} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-4 py-2.5 text-[13.5px]">
              <Tag className="border-border bg-surface-muted text-ink">
                {f.severity} severity{f.blocks_go ? ", blocks Go" : ""}
              </Tag>
              <span className="text-ink">{f.element_id}</span>
              <span className="text-ink-secondary">{f.observation}</span>
              <Open campaignId={campaignId} source={f.source} label="Open Risk Check" />
            </li>
          ))}
          {o.conflicts.map((x) => (
            <li key={x.id} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-4 py-2.5 text-[13.5px]">
              <Tag className="border-border bg-surface-muted text-ink">Evidence conflict</Tag>
              <span className="text-ink">{x.region_name ?? "No region"}</span>
              <span className="text-ink-secondary">{x.reason}</span>
              <Open campaignId={campaignId} source={x.source} />
            </li>
          ))}
        </ul>
      )}
      {(o.conflicts_total > o.conflicts.length || o.risk_findings_total > o.risk_findings.length) && (
        <p className="type-meta">
          Showing the first records of {o.conflicts_total} conflicts and {o.risk_findings_total} findings.
        </p>
      )}
    </Section>
  );
}

export function NextActions({ campaignId, content }: { campaignId: string; content: DigestContent }) {
  return (
    <Section id="actions" title="Next actions">
      {content.next_actions.length === 0 ? (
        <Empty>No action is suggested this week.</Empty>
      ) : (
        <ol className="ledger-rules rounded-card border border-border bg-surface">
          {content.next_actions.map((a, i) => (
            <li key={`${a.rule}-${i}`} className="space-y-1 px-4 py-3">
              <p className="flex items-baseline gap-2 text-[14.5px] text-ink">
                <span className="type-ledger w-4 shrink-0 text-[12.5px] text-ink-muted tabular-nums">{i + 1}.</span>
                <span className="min-w-0">{a.text}</span>
              </p>
              <p className="pl-5 text-[13px] text-ink-secondary">{a.why}</p>
              <p className="type-meta flex flex-wrap items-center gap-x-3 pl-5">
                <span>{PRIORITY_LABEL[a.priority]}</span>
                <span title="The fixed rule that produced this action">Rule: {a.rule.replace(/_/g, " ")}</span>
                <Open campaignId={campaignId} source={a.source} />
              </p>
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}

export function Limitations({ content }: { content: DigestContent }) {
  return (
    <details className="text-[12.5px] text-ink-secondary">
      <summary className="w-fit cursor-pointer rounded-sm py-0.5 hover:text-ink">What this digest does not say</summary>
      <ul className="mt-2 max-w-[78ch] list-disc space-y-1 pl-5">
        {content.limitations.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </details>
  );
}
