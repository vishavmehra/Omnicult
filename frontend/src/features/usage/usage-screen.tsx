"use client";

import { ChevronRight, FlaskConical, Radio, User, Users } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { Tag } from "@/components/evidence/badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { SELECT_CLASS } from "@/features/settings/frame";
import { roleLabel, useMe } from "@/features/settings/api";
import { SectionTitle } from "@/features/workspaces/parts";
import { cn } from "@/lib/utils";

import { PERIODS, useUsageReport, type UsageMode, type UsageReport } from "./api";
import { Breakdown } from "./breakdown";
import { BudgetPanel } from "./budget";
import { DayBars, DayTable } from "./chart";
import { Failures } from "./failures";
import { num, usd } from "./format";

function DisclosureLabel({ children }: { children: string }) {
  return (
    <summary className="inline-flex h-9 cursor-pointer list-none items-center gap-1.5 text-[13.5px] text-ember-link underline-offset-2 hover:underline [&::-webkit-details-marker]:hidden">
      <ChevronRight aria-hidden className="size-3.5 transition-transform group-open:rotate-90 motion-reduce:transition-none" />
      {children}
    </summary>
  );
}

/** The one quiet source line: what the numbers are, and what they are not. */
function sourceLine(report: UsageReport | undefined, mode: UsageMode) {
  if (mode === "demo") return "Demo project: these calls are saved fixtures. No model ran, so nothing was billed.";
  return `Estimates from the gateway price table${report ? ` ${report.price_table_version}` : ""}, not invoices.`;
}

function Summary({ report }: { report: UsageReport }) {
  const tokens = `${num.format(report.input_tokens)} in, ${num.format(report.output_tokens)} out${report.thinking_tokens ? `, ${num.format(report.thinking_tokens)} thinking` : ""}`;
  const rows: [string, string, string | null][] = [
    ["Model calls", `${num.format(report.calls)}${report.failed_calls ? `, ${num.format(report.failed_calls)} failed` : ""}`, report.fixture_calls ? `${num.format(report.fixture_calls)} of them fixture calls` : null],
    ["Estimated cost", usd(report.estimated_cost_usd), report.calls_without_cost ? `${num.format(report.calls_without_cost)} ${report.calls_without_cost === 1 ? "call has" : "calls have"} no recorded cost and ${report.calls_without_cost === 1 ? "is" : "are"} left out of this sum` : null],
    ["Tokens", tokens, null],
  ];
  return (
    <dl className="ledger-rules rounded-card border border-border bg-surface">
      {rows.map(([term, value, note]) => (
        <div key={term} className="grid gap-1 px-4 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
          <dt className="type-ledger text-[12.5px] text-ink-muted">{term}</dt>
          <dd className={cn("text-[14px]", report.estimated_cost_usd === null && term === "Estimated cost" ? "text-ink-muted" : "text-ink")}>
            {value}
            {note && <span className="type-meta block">{note}</span>}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Report({ report, days, mode }: { report: UsageReport; days: number; mode: UsageMode }) {
  // A chart of nothing (only fixture calls, which cost nothing) is left out; the calls chart still shows.
  const hasSpend = report.series.some((p) => (p.estimated_cost_usd ?? 0) > 0 || (p.calls > 0 && p.estimated_cost_usd === null));
  return (
    <div className="space-y-8">
      {mode === "live" && <BudgetPanel budget={report.budget} />}
      {report.calls === 0 ? (
        <EmptyState
          title={mode === "demo" ? "The demo project has no recorded calls" : `No model calls recorded in the last ${days} days`}
          description={
            mode === "demo"
              ? "It answers from saved fixtures and calls no model, so there is nothing to meter."
              : report.scope === "own"
                ? "Calls you start appear here once the model gateway records them."
                : "Calls appear here once the model gateway records them for this workspace."
          }
        />
      ) : (
        <>
          <section aria-labelledby="period" className="space-y-3">
            <SectionTitle id="period" meta={report.truncated ? "Newest calls only" : undefined}>
              The last {days} days
            </SectionTitle>
            <Summary report={report} />
            <div className={cn("grid gap-5 rounded-card border border-border bg-surface p-4 sm:p-5", hasSpend && "lg:grid-cols-2")}>
              {hasSpend && <DayBars points={report.series} kind="spend" title="Spend per day" />}
              <DayBars points={report.series} kind="calls" title="Calls per day" />
            </div>
            <details className="group">
              <DisclosureLabel>Show the daily figures as a table</DisclosureLabel>
              <div className="mt-2">
                <DayTable points={report.series} />
              </div>
            </details>
          </section>
          <Breakdown key={`${report.scope}-${mode}`} report={report} />
          <Failures report={report} />
        </>
      )}
      <details className="group">
        <DisclosureLabel>How these numbers are counted</DisclosureLabel>
        <ul className="mt-1 max-w-[72ch] list-disc space-y-1.5 pl-5 text-[13.5px] text-ink-secondary">
          {report.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
          <li>Days are UTC calendar days, and the daily ceiling resets at 00:00 UTC.</li>
        </ul>
      </details>
    </div>
  );
}

/** Usage and Credits: spend and calls over time, where they went, today against the daily ceiling, and what failed. */
export function UsageScreen() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const me = useMe();
  const workspaces = me.data?.workspaces ?? [];
  const selected = workspaces.find((w) => w.id === params.get("w")) ?? workspaces[0] ?? null;
  const asked = Number(params.get("days"));
  const days = (PERIODS as readonly number[]).includes(asked) ? asked : 30;
  const mode: UsageMode = params.get("mode") === "demo" ? "demo" : "live";
  const report = useUsageReport(selected?.id ?? null, days, mode);

  const go = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) next.set(k, v);
    router.replace(`${pathname}?${next}`, { scroll: false });
  };

  return (
    <>
      <header className="mb-5 space-y-1.5 border-b border-border pb-5">
        <h1 className="type-title text-[30px] text-ink sm:text-[34px]">Usage and credits</h1>
        <p className="max-w-[68ch] text-[14.5px] text-ink-secondary">What the model calls cost, how near the workspace is to its daily ceiling, where the spend went, and what failed.</p>
      </header>

      <div className="mb-3 flex flex-wrap items-end gap-x-4 gap-y-3">
        {workspaces.length > 1 && (
          <div className="space-y-1">
            <label htmlFor="usage-workspace" className="type-meta block">Workspace</label>
            <select id="usage-workspace" className={cn(SELECT_CLASS, "h-10 w-[min(22rem,calc(100vw-2rem))]")} value={selected?.id ?? ""} onChange={(e) => go({ w: e.target.value })}>
              {workspaces.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name} ({roleLabel(w.role)})
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="space-y-1">
          <label htmlFor="usage-days" className="type-meta block">Period</label>
          <select id="usage-days" className={cn(SELECT_CLASS, "h-10")} value={days} onChange={(e) => go({ days: e.target.value })}>
            {PERIODS.map((p) => (
              <option key={p} value={p}>
                Last {p} days
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <span id="usage-mode" className="type-meta block">Projects</span>
          <div role="group" aria-labelledby="usage-mode" className="flex gap-1.5">
            {([["live", "Live", Radio], ["demo", "Demo", FlaskConical]] as const).map(([value, label, Icon]) => (
              <button
                key={value}
                type="button"
                aria-pressed={mode === value}
                onClick={() => go({ mode: value })}
                className={cn("flex h-10 items-center gap-1.5 rounded-lg border px-3 text-[14px]", mode === value ? "clay border-border font-medium text-ink" : "border-transparent text-ink-secondary hover:bg-surface-muted hover:text-ink")}
              >
                <Icon aria-hidden className="size-3.5" />
                {label}
              </button>
            ))}
          </div>
        </div>
        {report.data && (
          <Tag className="mb-1.5 border-border bg-surface-muted text-ink" title={report.data.scope === "workspace" ? "You are an owner, so these are everyone's calls in the workspace." : "Only owners see everyone's calls. You see your own."}>
            {report.data.scope === "workspace" ? <Users aria-hidden /> : <User aria-hidden />}
            {report.data.scope === "workspace" ? "Whole workspace" : "Your calls only"}
          </Tag>
        )}
      </div>
      <p className="type-meta mb-6 max-w-[80ch]">{sourceLine(report.data, mode)}</p>

      {me.error ? (
        <ErrorState error={me.error} onRetry={() => void me.refetch()} />
      ) : !selected ? (
        <LoadingState label="Loading your workspaces…" />
      ) : report.error ? (
        <ErrorState error={report.error} onRetry={() => void report.refetch()} />
      ) : !report.data ? (
        <LoadingState label="Reading usage…" />
      ) : (
        <Report report={report.data} days={days} mode={mode} />
      )}
    </>
  );
}
