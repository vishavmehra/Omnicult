"use client";

import { CircleCheck, Infinity as InfinityIcon, OctagonX, TriangleAlert, type LucideIcon } from "lucide-react";

import { Tag } from "@/components/evidence/badges";
import { SectionTitle } from "@/features/workspaces/parts";
import { cn } from "@/lib/utils";

import type { UsageBudget } from "./api";
import { num, untilReset, usd } from "./format";

const STATUS: Record<UsageBudget["status"], { label: string; Icon: LucideIcon; tag: string; bar: string }> = {
  ok: { label: "Within the ceiling", Icon: CircleCheck, tag: "border-success/25 bg-success-soft text-success", bar: "bg-success" },
  near: { label: "Near the ceiling", Icon: TriangleAlert, tag: "border-warning/30 bg-warning-soft text-warning", bar: "bg-warning" },
  reached: { label: "Ceiling reached", Icon: OctagonX, tag: "border-danger/30 bg-danger-soft text-danger", bar: "bg-danger" },
  unlimited: { label: "No daily ceiling", Icon: InfinityIcon, tag: "border-border bg-surface-muted text-ink", bar: "bg-ink-secondary" },
};

/**
 * Today (UTC) against the daily ceiling. The headroom is the ceiling minus the recorded estimates, which is the rule the
 * budget guard applies; members who see only their own calls get no headroom, because the ceiling is the workspace's.
 */
export function BudgetPanel({ budget: b }: { budget: UsageBudget }) {
  const s = STATUS[b.status];
  const ceiling = b.daily_budget_usd;
  const own = b.scope === "own";
  const fill = b.used_share === null ? 0 : Math.min(1, b.used_share);
  const limits: [string, string][] = [
    ["Daily ceiling", ceiling === null ? "Off" : `${usd(ceiling)} for the workspace, all calls together`],
    ["One run", b.run_budget_usd === null ? "Off" : `${usd(b.run_budget_usd)} for each run`],
    ["Active runs", `${num.format(b.active_runs)} of ${num.format(b.max_active_runs_per_user)} for you`],
  ];
  return (
    <section aria-labelledby="today" className="rounded-card border border-border bg-surface p-4 sm:p-5">
      <SectionTitle id="today" meta={`Resets in ${untilReset(b.resets_at)}, at 00:00 UTC`}>
        {own ? "Your spend today" : "Today against the daily ceiling"}
      </SectionTitle>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div className="space-y-3">
          <p className="type-ledger flex flex-wrap items-baseline gap-x-2 text-ink">
            <span className="text-[28px] leading-none font-semibold">{usd(b.spent_today_usd)}</span>
            {ceiling !== null && !own && <span className="text-[14px] text-ink-secondary">of {usd(ceiling)} today</span>}
            {own && <span className="text-[14px] text-ink-secondary">from your {num.format(b.calls_today)} {b.calls_today === 1 ? "call" : "calls"} today</span>}
          </p>
          {!own && ceiling !== null && (
            <div
              role="meter"
              aria-label="Spend today against the daily ceiling"
              aria-valuemin={0}
              aria-valuemax={ceiling}
              aria-valuenow={Math.min(b.spent_today_usd ?? 0, ceiling)}
              aria-valuetext={`${usd(b.spent_today_usd)} of ${usd(ceiling)}`}
              className="clay-well h-3 overflow-hidden rounded-full"
            >
              <div className={cn("h-full rounded-full", s.bar)} style={{ width: `${fill * 100}%` }} />
            </div>
          )}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <Tag className={s.tag}>
              <s.Icon aria-hidden />
              {s.label}
            </Tag>
            {!own && b.remaining_usd !== null && <span className="text-[14px] text-ink-body">{usd(b.remaining_usd)} of headroom left today</span>}
            {!own && b.status === "reached" && <span className="text-[13.5px] text-ink-secondary">New AI calls are refused until the ceiling resets.</span>}
          </div>
          {own && <p className="max-w-[60ch] text-[13.5px] text-ink-secondary">{ceiling === null ? "There is no daily ceiling." : `The ${usd(ceiling)} ceiling is shared by the whole workspace, so your calls alone do not show how close it is. Owners see the headroom.`}</p>}
          {b.calls_today_without_cost > 0 && (
            <p className="max-w-[60ch] text-[13.5px] text-ink-secondary">
              {num.format(b.calls_today_without_cost)} {b.calls_today_without_cost === 1 ? "call" : "calls"} today with no recorded cost {b.calls_today_without_cost === 1 ? "is" : "are"} not counted here, and the budget guard does not count {b.calls_today_without_cost === 1 ? "it" : "them"} either.
            </p>
          )}
        </div>
        <dl className="ledger-rules self-start rounded-lg border border-border bg-surface-muted/40">
          {limits.map(([term, value]) => (
            <div key={term} className="grid gap-0.5 px-3.5 py-2 sm:grid-cols-[7rem_minmax(0,1fr)] sm:gap-3">
              <dt className="type-ledger text-[12.5px] text-ink-muted">{term}</dt>
              <dd className="text-[13.5px] text-ink">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
