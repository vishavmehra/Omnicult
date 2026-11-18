"use client";

import { Ban, CircleCheck, CircleDashed, FileDown, Info, LoaderCircle, Package, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Tag } from "@/components/evidence/badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Verdict } from "@/components/workflow/verdict";
import { useCampaign } from "@/features/workspaces/campaign-context";
import { LedgerList, SectionTitle } from "@/features/workspaces/parts";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { downloadRegionPlan, useRegionPlan, type PlanCheck, type PlanEvent, type RegionPlan, type RegionPlanEntry } from "./delivery-api";

/** The Launch Room tab keys, as they appear in the address (?tab=). */
export type DeliveryTab = "readiness" | "compare" | "region-plan" | "review-links" | "asset-pack";
export const DELIVERY_TABS: readonly DeliveryTab[] = ["readiness", "compare", "region-plan", "review-links", "asset-pack"];

const CHECK = {
  done: { word: "Done", Icon: CircleCheck, className: "text-success" },
  todo: { word: "To do", Icon: CircleDashed, className: "text-ink-muted" },
  warning: { word: "Check", Icon: TriangleAlert, className: "text-warning" },
  blocked: { word: "Blocked", Icon: Ban, className: "text-danger" },
} as const;

const READY = {
  ready: { word: "Ready", Icon: CircleCheck, className: "border-success/40 bg-success-soft text-success" },
  ready_with_override: { word: "Ready with override", Icon: TriangleAlert, className: "border-warning/40 bg-warning-soft text-warning" },
  not_ready: { word: "Not ready", Icon: CircleDashed, className: "border-border bg-surface-muted text-ink-secondary" },
} as const;

const EVENT_WORD = { campaign_start: "Start", campaign_end: "End", key_moment: "Brief", calendar_moment: "Calendar" } as const;

const day = new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const fmtDay = (iso: string) => day.format(new Date(`${iso}T00:00:00Z`));
const daysBetween = (from: string, to: string) => Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);
const money = (currency: string, amount: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 0 }).format(amount);

function ReadyStamp({ state }: { state: keyof typeof READY }) {
  const { word, Icon, className } = READY[state];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-stamp border-[3px] border-double px-2 py-1 text-[12px] font-semibold tracking-[0.06em] uppercase", className)}>
      <Icon aria-hidden className="size-3.5" />
      {word}
    </span>
  );
}

function Checklist({ items }: { items: PlanCheck[] }) {
  return (
    <ul className="ledger-rules rounded-card border border-border bg-surface" aria-label="Checklist">
      {items.map((c) => {
        const { word, Icon, className } = CHECK[c.status];
        return (
          <li key={c.id} className="grid grid-cols-[1.25rem_minmax(0,1fr)] gap-x-2.5 px-3.5 py-2">
            <Icon aria-hidden className={cn("mt-0.5 size-4", className)} />
            <div className="min-w-0">
              <p className="text-[13.5px] text-ink">
                {c.label}
                <span className={cn("ml-2 text-[11.5px] font-semibold tracking-wide uppercase", className)}>{word}</span>
              </p>
              <p className="text-[12.5px] text-ink-secondary">{c.detail}</p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function Timeline({ events, start }: { events: PlanEvent[]; start: string | null }) {
  if (events.length === 0) return <p className="text-[13px] text-ink-secondary">The brief has no dates, so there is no timeline. Add campaign dates and key moments in Campaign Desk.</p>;
  const total = start ? daysBetween(start, events[events.length - 1].date) : null;
  return (
    <ol className="relative space-y-0 border-l border-border-strong/60 pl-5" aria-label="Timeline">
      {events.map((e, i) => (
        <li key={`${e.date}-${e.kind}-${i}`} className="relative pb-3.5 last:pb-0">
          <span
            aria-hidden
            className={cn(
              "absolute top-1.5 -left-[1.62rem] size-2.5 rounded-full border-2 border-surface",
              e.warning ? "bg-warning" : e.kind === "campaign_start" || e.kind === "campaign_end" ? "bg-ember" : "bg-ink-secondary",
            )}
          />
          <p className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
            <time dateTime={e.date} className="type-ledger text-[13px] text-ink">
              {fmtDay(e.date)}
            </time>
            <span className="text-[13.5px] font-medium text-ink">{e.title}</span>
            <Tag className="border-border text-ink-secondary">{EVENT_WORD[e.kind]}</Tag>
            {start && total !== null && total > 0 && <span className="type-meta">Day {daysBetween(start, e.date) + 1}</span>}
          </p>
          {e.source && <p className="text-[12px] text-ink-muted">{e.source}</p>}
          {e.warning && (
            <p className="mt-0.5 flex items-start gap-1.5 text-[12.5px] text-warning">
              <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              {e.warning}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}

function RegionArticle({ plan, entry, onOpen }: { plan: RegionPlan; entry: RegionPlanEntry; onOpen(tab: DeliveryTab, region?: string): void }) {
  const titleId = `plan-${entry.region_code}`;
  const v = entry.version;
  return (
    <article aria-labelledby={titleId} className="clay overflow-hidden rounded-card border border-border">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border px-5 py-3.5">
        <h3 id={titleId} className="type-title text-[22px] text-ink">
          {entry.region_name}
        </h3>
        <span className="font-mono text-[12px] text-ink-muted">{entry.region_code}</span>
        <Tag className="border-border text-ink-secondary">{entry.role === "origin" ? "Origin" : "Target"}</Tag>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <span className="type-meta" aria-label={`${entry.progress_done} of ${entry.progress_total} checks done`}>
            {entry.progress_done} of {entry.progress_total} checks done
          </span>
          <ReadyStamp state={entry.ready.state} />
        </div>
      </header>

      <div className="grid gap-x-8 gap-y-5 px-5 py-5 xl:grid-cols-[minmax(0,32rem)_minmax(0,1fr)]">
        <div className="space-y-4">
          <LedgerList
            className="bg-transparent"
            rows={[
              { label: "Version", muted: !v, value: v ? <>{v.label} <span className="text-ink-muted">({v.state === "approved" ? "approved by a person" : "candidate, not approved"})</span></> : "None prepared for this region" },
              { label: "Language", muted: entry.languages.length === 0, value: entry.languages.join(", ") || "Not set in the brief", },
              {
                label: "Budget",
                muted: !entry.budget,
                value: entry.budget ? (
                  <>
                    {money(entry.budget.currency, entry.budget.amount)}
                    {entry.budget.share_of_total !== null && <span className="text-ink-muted"> · {(entry.budget.share_of_total * 100).toFixed(0)}% of the total</span>}
                    {entry.budget.sample && <span className="text-ink-muted"> · sample numbers</span>}
                  </>
                ) : (
                  "No amount for this region in the brief"
                ),
              },
              { label: "Channels", muted: entry.channels.length === 0, value: entry.channels.map((c) => c.name).join(", ") || "Not set in the brief" },
              {
                label: "Readiness",
                muted: !entry.readiness,
                value: entry.readiness ? (
                  <span className="flex flex-wrap items-center gap-2">
                    <Verdict value={entry.readiness.verdict} />
                    <span className="min-w-0 text-[13px]">{entry.readiness.main_reason}</span>
                  </span>
                ) : (
                  "Not computed for this version"
                ),
              },
              {
                label: "Decision",
                muted: !entry.approval,
                value: entry.approval ? (
                  <>
                    {entry.approval.decision === "approve" ? "Approved" : entry.approval.decision === "reject" ? "Rejected" : "Changes requested"} by {entry.approval.decided_by_name ?? "a member"},{" "}
                    <span title={formatDateTime(entry.approval.decided_at)}>{formatDateTime(entry.approval.decided_at)}</span>
                    {entry.approval.overrides_recommendation && <span className="text-warning"> · against the recommendation</span>}
                  </>
                ) : (
                  "No decision recorded"
                ),
              },
              {
                label: "Stakeholders",
                muted: !entry.feedback.latest_at,
                value: entry.feedback.latest_at
                  ? `${entry.feedback.counts.approve} approve, ${entry.feedback.counts.request_changes} changes, ${entry.feedback.counts.reject} reject, ${entry.feedback.counts.comment} comment`
                  : "No response through a review link",
              },
            ]}
          />
          <p className="text-[12.5px] text-ink-secondary">{entry.ready.reasons.join(" ")}</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => onOpen("readiness")}>
              Readiness Board
            </Button>
            <Button variant="outline" size="sm" disabled={!entry.pack_available} onClick={() => onOpen("asset-pack", entry.region_code)}>
              <Package aria-hidden />
              {entry.pack_available ? "Asset Pack" : "Asset Pack needs an approval"}
            </Button>
          </div>
        </div>

        <div className="min-w-0 space-y-5">
          <section aria-label={`Checklist for ${entry.region_name}`} className="space-y-2">
            <h4 className="text-[13.5px] font-semibold text-ink">Checklist</h4>
            <Checklist items={entry.checklist} />
          </section>
          <section aria-label={`Timeline for ${entry.region_name}`} className="space-y-2.5">
            <h4 className="text-[13.5px] font-semibold text-ink">Timeline</h4>
            <Timeline events={entry.timeline} start={plan.window?.start ?? null} />
          </section>
          {entry.warnings.length > 0 && (
            <section aria-label="Warnings" className="space-y-1.5 rounded-lg border border-warning/40 bg-warning-soft/50 px-3.5 py-3">
              <h4 className="flex items-center gap-1.5 text-[13px] font-semibold text-ink">
                <TriangleAlert aria-hidden className="size-4 text-warning" />
                To look at before launch
              </h4>
              <ul className="list-disc space-y-1 pl-5 text-[12.5px] text-ink-body">
                {entry.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </section>
          )}
          {entry.info.length > 0 && (
            <section aria-label="Also worth knowing" className="space-y-1">
              <h4 className="text-[12.5px] font-semibold text-ink-secondary">Also worth knowing</h4>
              <ul className="list-disc space-y-0.5 pl-5 text-[12.5px] text-ink-secondary">
                {entry.info.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
    </article>
  );
}

function Summary({ plan }: { plan: RegionPlan }) {
  const ready = plan.regions.filter((r) => r.ready.state !== "not_ready").length;
  const rows = [
    { label: "Campaign dates", muted: !plan.window, value: plan.window ? `${fmtDay(plan.window.start)} to ${fmtDay(plan.window.end)} (${plan.window.timezone})` : "Not set in the brief" },
    {
      label: "Budget",
      muted: plan.total_budget === null,
      value:
        plan.total_budget !== null && plan.currency
          ? `${money(plan.currency, plan.total_budget)} in total${plan.budget_sample ? ", sample numbers" : ""}${plan.unallocated_budget ? `, ${money(plan.currency, plan.unallocated_budget)} not yet split by region` : ""}`
          : "No budget in the brief",
    },
    { label: "Regions ready", value: `${ready} of ${plan.regions.length}${ready < plan.regions.length ? ", the rest wait on the records listed below" : ""}` },
  ];
  return <LedgerList rows={rows} />;
}

/**
 * Region Plan (feature 39): one plan per region, assembled by code from the brief, the Moment Calendar, the readiness verdicts,
 * the approvals and the stakeholder feedback. Nothing is typed here and nothing is stored: it reads the records fresh.
 */
export function RegionPlanTab({ onOpen }: { onOpen(tab: DeliveryTab, region?: string): void }) {
  const { campaign } = useCampaign();
  const query = useRegionPlan(campaign.id);
  const [busy, setBusy] = useState<"markdown" | "pdf" | null>(null);
  const [failed, setFailed] = useState<unknown>(null);

  async function download(format: "markdown" | "pdf") {
    setBusy(format);
    setFailed(null);
    try {
      await downloadRegionPlan(campaign.id, format);
      toast.success(format === "pdf" ? "PDF downloaded." : "Markdown downloaded.");
    } catch (e) {
      setFailed(e);
    } finally {
      setBusy(null);
    }
  }

  const plan = query.data;
  return (
    <div className="space-y-6">
      <section aria-labelledby="plan-title" className="space-y-3">
        <SectionTitle id="plan-title" meta={plan ? `Brief v${plan.brief_version} · plan rules ${plan.rule_version}` : undefined}>
          Region plan
        </SectionTitle>
        <p className="max-w-[72ch] text-[13.5px] text-ink-secondary">
          Which version goes to which region, with what budget and channels, in what order of dates, and what still stands in the way. It is read fresh from your records each time.
        </p>
        {query.error ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : query.isPending ? (
          <LoadingState label="Assembling the region plan…" />
        ) : (
          plan && (
            <>
              <Summary plan={plan} />
              <div className="flex flex-wrap items-center gap-2.5">
                {(["pdf", "markdown"] as const).map((f) => (
                  <Button key={f} variant="outline" disabled={busy !== null} onClick={() => void download(f)}>
                    {busy === f ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <FileDown aria-hidden />}
                    {f === "pdf" ? "Download PDF" : "Download Markdown"}
                  </Button>
                ))}
                <span className="flex max-w-[56ch] items-start gap-1.5 text-[12px] text-ink-muted">
                  <Info aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                  The PDF shows regional-script text as a Latin transliteration and says so on the page. Markdown keeps the original script.
                </span>
              </div>
              {failed ? <ErrorState error={failed} /> : null}
              {plan.gaps.length > 0 && (
                <ul role="status" className="list-disc space-y-1 pl-5 text-[13px] text-ink-body">
                  {plan.gaps.map((g) => (
                    <li key={g}>{g}</li>
                  ))}
                </ul>
              )}
            </>
          )
        )}
      </section>

      {plan &&
        (plan.regions.length === 0 ? (
          <EmptyState
            title="No region to plan yet"
            description="The plan lists the origin and target regions of the brief. Name them in Campaign Desk, or record a verdict or a decision for a region."
            needs={[{ label: "Target regions in the Campaign Brief" }]}
          />
        ) : (
          <div className="space-y-5">
            {plan.regions.map((r) => (
              <RegionArticle key={r.region_code} plan={plan} entry={r} onOpen={onOpen} />
            ))}
          </div>
        ))}

      {plan && (
        <section aria-label="How the plan is made" className="space-y-1.5">
          <h3 className="text-[13px] font-semibold text-ink">How this plan is made</h3>
          <ul className="list-disc space-y-1 pl-5 text-[12.5px] text-ink-secondary">
            {plan.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
          <p className="type-meta">{plan.source_line}</p>
        </section>
      )}
    </div>
  );
}
