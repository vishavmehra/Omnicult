"use client";

import { ChevronRight, CircleAlert, CircleCheck, CircleDashed, FlaskConical, RotateCw } from "lucide-react";
import { useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { RunStatusBadge } from "@/components/workflow/run-status";
import { RUN_TYPE_META } from "@/features/project/workflow";
import { SectionTitle } from "@/features/workspaces/parts";
import type { RunStatus, RunType } from "@/lib/api/types";
import { formatDateTime, formatElapsed, humanize, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

import { RUN_HISTORY_PAGE, useRunDetail, useRunHistory } from "./api";
import { Fact, formatCount, formatUsd, SELECT_CLASS } from "./parts";
import type { RunHistoryDetail, RunHistoryItem, RunHistoryTotals } from "./types";

const STATUSES: RunStatus[] = ["queued", "running", "completed", "partial", "failed", "cancelled"];
const RUN_TYPES = Object.keys(RUN_TYPE_META) as RunType[];
const COST_BASIS = { usage_events: "metered per call", run_steps: "summed from the run's stage traces", none: "nothing recorded" } as const;

/** An estimate is shown with its basis; a missing figure is "not recorded", never zero. */
const estimate = (v: number | null) => (v === null ? "not recorded" : formatUsd(v));

function Totals({ t }: { t: RunHistoryTotals }) {
  const statuses = Object.entries(t.by_status).filter(([, n]) => n > 0);
  const noCost = t.runs > 0 && t.runs_without_cost === t.runs;
  return (
    <section aria-label="Totals for the matching runs" className="space-y-3 rounded-card border border-border bg-surface px-4 py-4">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-4">
        <Fact label="Runs">
          {formatCount(t.runs)}
          {statuses.length > 0 && <span className="block text-[12.5px] text-ink-muted">{statuses.map(([s, n]) => `${humanize(s)} ${n}`).join(" · ")}</span>}
        </Fact>
        <Fact label="Tokens">
          {formatCount(t.input_tokens)} in, {formatCount(t.output_tokens)} out
          <span className="block text-[12.5px] text-ink-muted">{formatCount(t.thinking_tokens)} of the output spent thinking</span>
        </Fact>
        <Fact label="Estimated cost">
          {noCost ? "None recorded" : formatUsd(t.estimated_cost_usd)}
          {!noCost && t.runs_without_cost > 0 && <span className="block text-[12.5px] text-warning">At least this much: {t.runs_without_cost} runs have no recorded cost</span>}
        </Fact>
        <Fact label="Actual cost">
          Not reported
          <span className="block text-[12.5px] text-ink-muted">Provider invoices are not read.</span>
        </Fact>
      </dl>
      {t.unattributed_events > 0 && (
        <p className="text-[12.5px] text-ink-secondary">
          {formatCount(t.unattributed_events)} metered {t.unattributed_events === 1 ? "call belongs" : "calls belong"} to no run (for example search embeddings), about {formatUsd(t.unattributed_cost_usd)} estimated. They are not in the
          totals above.
        </p>
      )}
      <p className="max-w-[72ch] text-[12.5px] text-ink-muted">Costs are estimates from a price table, never invoices. A figure that was not recorded is shown as not recorded, not as zero.</p>
    </section>
  );
}

const STEP: Record<"completed" | "failed" | "skipped", { label: string; Icon: typeof CircleCheck; className: string }> = {
  completed: { label: "Completed", Icon: CircleCheck, className: "text-success" },
  failed: { label: "Failed", Icon: CircleAlert, className: "text-danger" },
  skipped: { label: "Skipped", Icon: CircleDashed, className: "text-ink-muted" },
};

function Th({ children, className }: { children: string; className?: string }) {
  return (
    <th scope="col" className={cn("px-3 py-2 font-medium whitespace-nowrap", className)}>
      {children}
    </th>
  );
}

function Detail({ run }: { run: RunHistoryItem }) {
  const detail = useRunDetail(run.run_id, true);
  if (detail.isPending) return <LoadingState label="Loading the run's stages and metered calls…" />;
  if (detail.error) return <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />;
  const d: RunHistoryDetail = detail.data;
  return (
    <div className="space-y-4 border-t border-border bg-surface-muted/40 px-4 py-4">
      {d.error && (
        <p role="alert" className="flex items-start gap-2 text-[13.5px] text-ink">
          <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />
          <span>
            {d.error.message}
            <span className="type-meta block">
              <span className="font-mono">{d.error.code}</span>
              {d.error.stage && ` · at ${humanize(d.error.stage)}`} · {d.error.retryable ? "can be retried" : "not retryable as it is"}
            </span>
          </span>
        </p>
      )}

      <div className="space-y-1.5">
        <h4 className="text-[13.5px] font-semibold text-ink">Stages</h4>
        {d.steps.length === 0 ? (
          <p className="text-[13px] text-ink-muted">No stage traces were recorded for this run.</p>
        ) : (
          <div className="overflow-x-auto rounded-card border border-border bg-surface">
            <table className="type-ledger w-full min-w-[44rem] text-left text-[12.5px]">
              <thead className="bg-surface-muted text-[11.5px] text-ink-muted">
                <tr>
                  <Th>Stage</Th>
                  <Th>State</Th>
                  <Th>Model</Th>
                  <Th>Prompt version</Th>
                  <Th>Took</Th>
                  <Th>Tokens</Th>
                  <Th>Estimated cost</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {d.steps.map((s, i) => {
                  const st = STEP[s.status];
                  return (
                    <tr key={`${s.stage}-${i}`}>
                      <td className="px-3 py-2">
                        <span className="font-medium text-ink">{humanize(s.stage)}</span>
                        <span className="type-meta block">{s.agent}</span>
                      </td>
                      <td className="px-3 py-2">
                        <span className={cn("inline-flex items-center gap-1 font-medium", st.className)}>
                          <st.Icon aria-hidden className="size-3.5" />
                          {st.label}
                        </span>
                        {s.error_code && <span className="type-meta block font-mono">{s.error_code}</span>}
                        {(s.retries > 0 || s.fallback_used) && (
                          <span className="type-meta block">
                            {s.retries > 0 && `${s.retries} ${s.retries === 1 ? "retry" : "retries"}`}
                            {s.retries > 0 && s.fallback_used && " · "}
                            {s.fallback_used && "fallback model used"}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-ink-secondary">
                        {s.model_id ?? "No model recorded"}
                        {s.provider && <span className="type-meta block">{s.provider}</span>}
                      </td>
                      <td className="px-3 py-2 font-mono text-[11.5px] text-ink-secondary">{s.prompt_version ?? "none"}</td>
                      <td className="px-3 py-2 tabular-nums text-ink-secondary">{s.latency_ms != null ? formatElapsed(s.latency_ms) : "not recorded"}</td>
                      <td className="px-3 py-2 tabular-nums text-ink-secondary">
                        {s.usage?.total_tokens != null ? formatCount(s.usage.total_tokens) : "not recorded"}
                      </td>
                      <td className="px-3 py-2 tabular-nums text-ink-secondary">{estimate(s.usage?.estimated_cost_usd ?? null)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="space-y-1.5">
        <h4 className="text-[13.5px] font-semibold text-ink">Metered calls</h4>
        {d.usage_events.length === 0 ? (
          <p className="text-[13px] text-ink-muted">No model call was metered for this run.</p>
        ) : (
          <div className="overflow-x-auto rounded-card border border-border bg-surface">
            <table className="type-ledger w-full min-w-[44rem] text-left text-[12.5px]">
              <thead className="bg-surface-muted text-[11.5px] text-ink-muted">
                <tr>
                  <Th>Capability</Th>
                  <Th>Model</Th>
                  <Th>Prompt version</Th>
                  <Th>Tokens in, out</Th>
                  <Th>Took</Th>
                  <Th>State</Th>
                  <Th>Estimated cost</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {d.usage_events.map((u) => (
                  <tr key={u.id}>
                    <td className="px-3 py-2">{humanize(u.capability)}</td>
                    <td className="px-3 py-2 text-ink-secondary">
                      {u.model}
                      <span className="type-meta block">{u.provider}</span>
                    </td>
                    <td className="px-3 py-2 font-mono text-[11.5px] text-ink-secondary">{u.prompt_version ?? "none"}</td>
                    <td className="px-3 py-2 tabular-nums text-ink-secondary">
                      {formatCount(u.input_tokens)}, {formatCount(u.output_tokens)}
                    </td>
                    <td className="px-3 py-2 tabular-nums text-ink-secondary">{u.latency_ms != null ? formatElapsed(u.latency_ms) : "not recorded"}</td>
                    <td className="px-3 py-2">
                      {u.status === "ok" ? "OK" : humanize(u.status)}
                      {u.error_code && <span className="type-meta block font-mono">{u.error_code}</span>}
                    </td>
                    <td className="px-3 py-2 tabular-nums text-ink-secondary">{formatUsd(u.estimated_cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-3">
        <Fact label="Inputs">{d.input_ref.fields.length ? `Stored: ${d.input_ref.fields.map(humanize).join(", ")}` : "No stored input fields"}</Fact>
        <Fact label="Result">{d.output_ref ? `${humanize(d.output_ref.resource)} ${d.output_ref.ids.map(shortId).join(", ")}` : "No result stored"}</Fact>
        <Fact label="Actual cost">Not reported</Fact>
      </dl>
    </div>
  );
}

function RunEntry({ run }: { run: RunHistoryItem }) {
  const [open, setOpen] = useState(false);
  const started = run.started_at ?? run.created_at;
  return (
    <li className="relative">
      <span aria-hidden className="absolute top-[22px] -left-[19px] size-[9px] rounded-full border-2 border-border-strong bg-canvas" />
      <article className="overflow-hidden rounded-card border border-border bg-surface">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex w-full items-start gap-2.5 px-4 py-3 text-left hover:bg-surface-muted/50 focus-visible:-outline-offset-2"
        >
          <ChevronRight aria-hidden className={cn("mt-1 size-4 shrink-0 text-ink-muted transition-transform motion-reduce:transition-none", open && "rotate-90")} />
          <span className="min-w-0 flex-1 space-y-1">
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="text-[14.5px] font-medium text-ink">{run.operation}</span>
              <RunStatusBadge status={run.status} />
              {run.mode === "demo" && (
                <span className="inline-flex items-center gap-1 text-[11.5px] text-ink-muted">
                  <FlaskConical aria-hidden className="size-3.5" />
                  Demo fixture
                </span>
              )}
              {run.resumable && (
                <span className="inline-flex items-center gap-1 text-[11.5px] text-ink-secondary">
                  <RotateCw aria-hidden className="size-3.5" />
                  Can resume from a checkpoint
                </span>
              )}
              <span className="font-mono text-[11.5px] text-ink-muted">{shortId(run.run_id)}</span>
            </span>
            <span className="type-ledger flex flex-wrap gap-x-4 gap-y-0.5 text-[12.5px] text-ink-secondary">
              <span title={started}>{formatDateTime(started)}</span>
              <span>Took {run.duration_ms != null ? formatElapsed(run.duration_ms) : run.status === "running" || run.status === "queued" ? "not finished" : "not recorded"}</span>
              <span>{run.models.length ? run.models.join(", ") : "No model recorded"}</span>
              <span>Prompt {run.prompt_versions.length ? run.prompt_versions.join(", ") : "none"}</span>
            </span>
            <span className="type-ledger flex flex-wrap gap-x-4 gap-y-0.5 text-[12.5px] text-ink-secondary">
              <span>
                {formatCount(run.input_tokens)} in, {formatCount(run.output_tokens)} out tokens
              </span>
              <span title={`Cost basis: ${COST_BASIS[run.cost_basis]}. An estimate, not an invoice.`}>Estimated cost {estimate(run.estimated_cost_usd)}</span>
              <span>
                {run.ai_calls} AI {run.ai_calls === 1 ? "call" : "calls"}
                {run.failed_ai_calls > 0 && <span className="text-danger">, {run.failed_ai_calls} failed</span>}
              </span>
              {run.attempt > 1 && <span>Attempt {run.attempt}</span>}
            </span>
            {run.error && (
              <span className="block max-w-[72ch] text-[12.5px] text-danger">
                {run.error.message}
                {run.failed_stages.length > 0 && <span className="text-ink-muted"> Failed at {run.failed_stages.map(humanize).join(", ")}.</span>}
              </span>
            )}
          </span>
        </button>
        {open && <Detail run={run} />}
      </article>
    </li>
  );
}

/** Every run of the campaign, newest first: stages, state, model, prompt version, duration and estimated cost. */
export function RunHistoryPanel({ campaignId }: { campaignId: string }) {
  const [runType, setRunType] = useState<RunType | "">("");
  const [status, setStatus] = useState<RunStatus | "">("");
  const [page, setPage] = useState(0);
  const history = useRunHistory(campaignId, { runType: runType || undefined, status: status || undefined, page });
  const filtered = Boolean(runType || status);

  if (history.isPending) return <LoadingState label="Loading run history…" />;
  if (history.error && !history.data) return <ErrorState error={history.error} onRetry={() => void history.refetch()} />;
  const data = history.data!;
  const first = page * RUN_HISTORY_PAGE;
  const clear = () => {
    setRunType("");
    setStatus("");
    setPage(0);
  };

  return (
    <div className="space-y-4">
      <Totals t={data.totals} />
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <SectionTitle meta={data.total ? `${first + 1} to ${Math.min(first + data.items.length, data.total)} of ${data.total}` : undefined}>Runs, newest first</SectionTitle>
        <div className="mb-2.5 flex flex-wrap items-center gap-2">
          <label htmlFor="rh-type" className="sr-only">
            Filter by run type
          </label>
          <select id="rh-type" value={runType} onChange={(e) => { setRunType(e.target.value as RunType | ""); setPage(0); }} className={SELECT_CLASS}>
            <option value="">All run types</option>
            {RUN_TYPES.map((t) => (
              <option key={t} value={t}>
                {RUN_TYPE_META[t].label}
              </option>
            ))}
          </select>
          <label htmlFor="rh-status" className="sr-only">
            Filter by state
          </label>
          <select id="rh-status" value={status} onChange={(e) => { setStatus(e.target.value as RunStatus | ""); setPage(0); }} className={SELECT_CLASS}>
            <option value="">All states</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {humanize(s === "partial" ? "completed with gaps" : s)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {history.error && <ErrorState error={history.error} onRetry={() => void history.refetch()} />}

      {data.items.length === 0 ? (
        filtered ? (
          <EmptyState
            title="No runs match these filters"
            description="Totals above count only runs that match. Clear the filters to see every run of this campaign."
            action={<Button variant="outline" onClick={clear}>Clear filters</Button>}
          />
        ) : (
          <EmptyState
            title="No runs recorded for this campaign yet"
            description="Every analysis, rehearsal, adaptation and evaluation is listed here with its stages, model, prompt version, duration and estimated cost, whether it finished or failed."
            needs={[{ label: "Start a run from Market Lens, Creative Studio, Audience Lab or Launch Room", met: false }]}
          />
        )
      ) : (
        <ol className="relative space-y-3 pl-5 before:absolute before:top-3 before:bottom-3 before:left-[7px] before:w-px before:bg-border">
          {data.items.map((run) => (
            <RunEntry key={run.run_id} run={run} />
          ))}
        </ol>
      )}

      {data.total > RUN_HISTORY_PAGE && (
        <div className="flex items-center justify-between gap-3">
          <Button variant="outline" disabled={page === 0 || history.isFetching} onClick={() => setPage((p) => p - 1)}>
            Newer
          </Button>
          <span className="type-meta">
            Page {page + 1} of {Math.ceil(data.total / RUN_HISTORY_PAGE)}
          </span>
          <Button variant="outline" disabled={first + RUN_HISTORY_PAGE >= data.total || history.isFetching} onClick={() => setPage((p) => p + 1)}>
            Older
          </Button>
        </div>
      )}
    </div>
  );
}
