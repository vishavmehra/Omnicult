"use client";

import Link from "next/link";
import { useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { SectionTitle } from "@/features/workspaces/parts";
import { formatDateTime, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useMe, useRegionList, useUpdateWorkspace, useUsage, useWorkspaceDetail, type WorkspaceDetail, type WorkspaceUsage } from "./api";
import { SELECT_CLASS, Saved, SettingsFrame } from "./frame";

const CAPABILITY: Record<string, string> = { text: "Text", embeddings: "Embeddings", vision: "Vision", tts: "Text to speech", image_generation: "Image generation", grounded_research: "Grounded research", transcribe: "Transcription" };
const label = (key: string) => CAPABILITY[key] ?? humanize(key);
const usd = (n: number | null) => (n === null ? "Not recorded" : `$${n < 1 ? n.toFixed(4) : n.toFixed(2)}`);
const num = new Intl.NumberFormat("en");

function NameForm({ detail, canEdit }: { detail: WorkspaceDetail; canEdit: boolean }) {
  const update = useUpdateWorkspace(detail.id);
  const [name, setName] = useState(detail.name);
  const changed = name.trim() !== detail.name;
  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (changed && name.trim()) update.mutate({ name: name.trim() });
      }}
    >
      <div className="min-w-0 flex-1 basis-64 space-y-1">
        <label htmlFor="workspace-name" className="type-meta block">
          Workspace name
        </label>
        <Input id="workspace-name" value={name} maxLength={80} disabled={!canEdit} onChange={(e) => setName(e.target.value)} className="h-10" />
      </div>
      {canEdit && (
        <>
          <Button type="submit" variant="outline" size="lg" disabled={!changed || !name.trim() || update.isPending}>
            Save name
          </Button>
          <Saved show={update.isSuccess && !changed} />
        </>
      )}
      {update.error && <ErrorState error={update.error} className="basis-full" />}
    </form>
  );
}

function RegionsForm({ detail, canEdit }: { detail: WorkspaceDetail; canEdit: boolean }) {
  const regions = useRegionList("IN");
  const update = useUpdateWorkspace(detail.id);
  const [picked, setPicked] = useState<string[]>(detail.default_region_codes);
  const [filter, setFilter] = useState("");
  const changed = [...picked].sort().join(",") !== [...detail.default_region_codes].sort().join(",");
  const items = (regions.data?.items ?? []).filter((r) => `${r.name} ${r.code}`.toLowerCase().includes(filter.trim().toLowerCase()));
  const toggle = (code: string) => setPicked((p) => (p.includes(code) ? p.filter((c) => c !== code) : [...p, code]));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <label htmlFor="region-filter" className="type-meta block">
            Find a region
          </label>
          <Input id="region-filter" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Tamil Nadu or IN-TN" className="h-10 w-64" />
        </div>
        <p className="type-meta pb-2.5" aria-live="polite">
          {picked.length} selected
        </p>
      </div>
      {regions.error ? (
        <ErrorState error={regions.error} onRetry={() => void regions.refetch()} />
      ) : !regions.data ? (
        <LoadingState label="Loading regions…" />
      ) : (
        <fieldset disabled={!canEdit} className="min-w-0">
          <legend className="sr-only">Default regions</legend>
          {items.length === 0 ? (
            <p className="text-[13.5px] text-ink-muted">No region matches “{filter}”.</p>
          ) : (
            <ul className="grid max-h-72 gap-px overflow-y-auto rounded-card border border-border bg-border sm:grid-cols-2 xl:grid-cols-3">
              {items.map((r) => (
                <li key={r.code} className="bg-surface">
                  <label className={cn("flex min-h-10 cursor-pointer items-center gap-2.5 px-3 py-1.5 text-[13.5px] hover:bg-surface-muted", !canEdit && "cursor-default")}>
                    <Checkbox checked={picked.includes(r.code)} onCheckedChange={() => toggle(r.code)} aria-label={`${r.name}, ${r.code}`} />
                    <span className="min-w-0 flex-1 truncate text-ink-body">{r.name}</span>
                    <span className="font-mono text-[11px] text-ink-muted">{r.code}</span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </fieldset>
      )}
      <div className="flex flex-wrap items-center gap-3">
        {canEdit && (
          <Button size="lg" disabled={!changed || update.isPending} onClick={() => update.mutate({ default_region_codes: picked })}>
            Save regions
          </Button>
        )}
        <Saved show={update.isSuccess && !changed} />
        <p className="text-[12.5px] text-ink-muted">Saved with the workspace. Campaigns do not use this yet.</p>
      </div>
      {update.error && <ErrorState error={update.error} />}
    </div>
  );
}

function Breakdown({ title, rows }: { title: string; rows: WorkspaceUsage["by_capability"] }) {
  if (!rows.length) return null;
  return (
    <div className="space-y-1.5">
      <h3 className="text-[13px] font-semibold text-ink">{title}</h3>
      <div className="overflow-x-auto rounded-card border border-border bg-surface">
        <table className="type-ledger w-full min-w-[34rem] text-[13px]">
          <thead>
            <tr className="border-b border-border text-left text-ink-muted">
              <th scope="col" className="px-4 py-2 font-normal">{title === "By model" ? "Model" : "Capability"}</th>
              <th scope="col" className="px-3 py-2 text-right font-normal">Calls</th>
              <th scope="col" className="px-3 py-2 text-right font-normal">Failed</th>
              <th scope="col" className="px-3 py-2 text-right font-normal">Input tokens</th>
              <th scope="col" className="px-3 py-2 text-right font-normal">Output tokens</th>
              <th scope="col" className="px-4 py-2 text-right font-normal">Estimated cost</th>
            </tr>
          </thead>
          <tbody className="ledger-rules">
            {rows.map((r) => (
              <tr key={r.key}>
                <th scope="row" className="px-4 py-2 text-left font-normal text-ink-body">{label(r.key)}</th>
                <td className="px-3 py-2 text-right">{num.format(r.calls)}</td>
                <td className="px-3 py-2 text-right">{num.format(r.failed_calls)}</td>
                <td className="px-3 py-2 text-right">{num.format(r.input_tokens)}</td>
                <td className="px-3 py-2 text-right">{num.format(r.output_tokens + r.thinking_tokens)}</td>
                <td className="px-4 py-2 text-right text-ink">{usd(r.estimated_cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function UsagePanel({ workspaceId }: { workspaceId: string }) {
  const [days, setDays] = useState(30);
  const usage = useUsage(workspaceId, days);
  const u = usage.data;
  return (
    <section aria-labelledby="usage" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <SectionTitle id="usage">Usage</SectionTitle>
        <div className="flex items-center gap-2">
          <label htmlFor="usage-days" className="type-meta">
            Period
          </label>
          <select id="usage-days" className={SELECT_CLASS} value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </div>
      </div>
      {usage.error ? (
        <ErrorState error={usage.error} onRetry={() => void usage.refetch()} />
      ) : !u ? (
        <LoadingState label="Loading usage…" />
      ) : u.calls === 0 ? (
        <EmptyState title={`No model calls recorded in the last ${u.days} days`} description="Calls appear here once the model gateway records them for this workspace." />
      ) : (
        <div className="space-y-4">
          <dl className="ledger-rules rounded-card border border-border bg-surface">
            {[
              ["Model calls", `${num.format(u.calls)}${u.failed_calls ? `, ${num.format(u.failed_calls)} failed` : ""}`],
              ["Tokens", `${num.format(u.input_tokens)} in, ${num.format(u.output_tokens)} out${u.thinking_tokens ? `, ${num.format(u.thinking_tokens)} thinking` : ""}`],
              ["Estimated cost", usd(u.estimated_cost_usd)],
              ["Actual cost", "Not reported"],
            ].map(([label, value]) => (
              <div key={label} className="grid gap-1 px-4 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
                <dt className="type-ledger text-[12.5px] text-ink-muted">{label}</dt>
                <dd className={cn("text-[14px]", label === "Actual cost" ? "text-ink-muted" : "text-ink")}>{value}</dd>
              </div>
            ))}
          </dl>
          <Breakdown title="By capability" rows={u.by_capability} />
          <Breakdown title="By model" rows={u.by_model} />
        </div>
      )}
      {u && (
        <p className="text-[12px] text-ink-muted" title={`${formatDateTime(u.since)} to ${formatDateTime(u.until)}`}>
          Estimates from price table {u.price_table_version}; provider invoices are not read.{u.scope === "own" ? " Your own calls only." : ""}{" "}
          <Link href={`/app/usage?w=${workspaceId}`} className="font-medium text-ember-link hover:underline">
            Open the full usage page
          </Link>
        </p>
      )}
    </section>
  );
}

function WorkspacePanel({ workspaceId }: { workspaceId: string }) {
  const me = useMe();
  const detail = useWorkspaceDetail(workspaceId);
  if (detail.error) return <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />;
  if (!detail.data) return <LoadingState label="Loading the workspace…" />;
  const canEdit = detail.data.role === "owner" && !me.data?.is_anonymous;
  return (
    <div className="space-y-8">
      <section aria-labelledby="general" className="space-y-3">
        <SectionTitle id="general" meta={`${detail.data.kind === "personal" ? "Personal" : "Team"} workspace, ${detail.data.member_count} ${detail.data.member_count === 1 ? "member" : "members"}`}>
          Workspace
        </SectionTitle>
        <NameForm key={detail.data.name} detail={detail.data} canEdit={canEdit} />
        {!canEdit && <p className="text-[12.5px] text-ink-muted">Only owners can change these settings.</p>}
      </section>
      <section aria-labelledby="regions" className="space-y-3">
        <SectionTitle id="regions">Default regions</SectionTitle>
        <RegionsForm key={detail.data.default_region_codes.join(",")} detail={detail.data} canEdit={canEdit} />
      </section>
      <UsagePanel workspaceId={workspaceId} />
    </div>
  );
}

/** Workspace settings (name, default regions) and the read-only Usage panel. */
export function WorkspaceScreen() {
  return <SettingsFrame>{(workspace) => <WorkspacePanel key={workspace.id} workspaceId={workspace.id} />}</SettingsFrame>;
}
