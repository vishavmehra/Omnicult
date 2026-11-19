"use client";

import { useMutation } from "@tanstack/react-query";
import { Download, FilePlus2, LoaderCircle, RefreshCw, Sparkles } from "lucide-react";
import { useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { PULSE_THEME } from "@/features/pulse/ui";
import type { components } from "@/lib/api/schema";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { downloadDigest, EXPORT_LABEL, useAddSummary, useCreateDigest, useDigest, useDigests, type ExportFormat } from "./api";
import { CommentsSection, Limitations, NextActions, OpenItems, PulseMovement, WhatChanged } from "./digest-sections";
import { isoWeekLabel, weekChoices, weekSpan, type Digest } from "./logic";
import { ModelTag } from "./ui";

type Row = { start: string; end: string; label: string; digest: components["schemas"]["DigestSummary"] | null };

/** Weekly Digest (feature 48): a plain-language summary of one campaign week, from stored records. Read here or export it; nothing is sent. */
export function WeeklyDigest({ campaignId }: { campaignId: string }) {
  const list = useDigests(campaignId);
  const [selected, setSelected] = useState<string | null>(null);
  const current = list.data?.current_week;
  const week = selected ?? current?.start ?? null;

  const rows: Row[] = [];
  if (list.data && current) {
    const stored = new Map(list.data.items.map((i) => [i.week.start, i]));
    const starts = new Map(weekChoices(current).map((c) => [c.value, c]));
    for (const i of list.data.items) if (!starts.has(i.week.start)) starts.set(i.week.start, { value: i.week.start, label: "" });
    for (const start of [...starts.keys()].sort().reverse()) {
      const item = stored.get(start) ?? null;
      const end = item?.week.end ?? new Date(Date.parse(`${start}T00:00:00Z`) + 6 * 86_400_000).toISOString().slice(0, 10);
      rows.push({ start, end, label: item?.week.label ?? isoWeekLabel(start), digest: item });
    }
  }
  const selectedRow = rows.find((r) => r.start === week) ?? null;

  return (
    <div className={cn("space-y-6", PULSE_THEME)}>
      <header className="space-y-1.5">
        <h2 className="type-title text-[22px] text-ink">Weekly Digest</h2>
        <p className="max-w-[68ch] text-[14.5px] text-ink-secondary">
          What changed in the campaign this week, how Pulse moved, what is open and what to do next. Every number is calculated from stored records. Export it to Markdown or PDF; nothing is sent anywhere.
        </p>
      </header>
      {list.error && !list.data ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : !list.data || !current ? (
        <LoadingState label="Opening the digests…" />
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[16.5rem_minmax(0,1fr)]">
          <nav aria-label="Weeks" className="space-y-2">
            <h3 className="text-[13px] font-semibold text-ink">Weeks</h3>
            <ul className="ledger-rules rounded-card border border-border bg-surface">
              {rows.map((r) => {
                const on = r.start === week;
                return (
                  <li key={r.start}>
                    <button
                      type="button"
                      aria-current={on ? "true" : undefined}
                      onClick={() => setSelected(r.start)}
                      className={cn("block w-full px-3 py-2.5 text-left focus-visible:-outline-offset-2", on ? "bg-surface-raised shadow-clay" : "hover:bg-surface-muted")}
                    >
                      <span className="flex items-baseline justify-between gap-2">
                        <span className="text-[13.5px] font-medium text-ink">{r.label}</span>
                        {r.start === current.start && <span className="type-meta">this week</span>}
                      </span>
                      <span className="type-meta block">{weekSpan(r.start, r.end)}</span>
                      <span className="type-ledger mt-0.5 block text-[12px] text-ink-secondary">
                        {r.digest
                          ? `Revision ${r.digest.revision} · ${r.digest.counts.alerts} alerts · ${r.digest.counts.open_items} open · ${r.digest.counts.actions} actions`
                          : "Not generated"}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>
          <div className="min-w-0">
            {selectedRow?.digest ? (
              <Selected campaignId={campaignId} digestId={selectedRow.digest.id} week={selectedRow.start} narrativeAvailable={list.data.narrative_available} />
            ) : selectedRow ? (
              <Generate campaignId={campaignId} week={selectedRow.start} label={selectedRow.label} span={weekSpan(selectedRow.start, selectedRow.end)} />
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

function Generate({ campaignId, week, label, span }: { campaignId: string; week: string; label: string; span: string }) {
  const create = useCreateDigest(campaignId);
  return (
    <div className="space-y-3">
      <EmptyState
        title={`No digest for ${label} yet`}
        description={`A digest for ${span} is built from what the campaign recorded that week and the Live Pulse data up to its end. It takes a moment and calls no model.`}
        action={
          <Button size="lg" onClick={() => create.mutate({ week_of: week, regenerate: false })} disabled={create.isPending}>
            {create.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <FilePlus2 aria-hidden />}
            {create.isPending ? "Building the digest…" : `Generate the digest for ${label}`}
          </Button>
        }
      />
      {create.error && <ErrorState error={create.error} onRetry={() => create.mutate({ week_of: week, regenerate: false })} />}
    </div>
  );
}

function Selected({ campaignId, digestId, week, narrativeAvailable }: { campaignId: string; digestId: string; week: string; narrativeAvailable: boolean }) {
  const query = useDigest(campaignId, digestId);
  if (query.error && !query.data) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (!query.data) return <LoadingState label="Opening the digest…" />;
  return <DigestView campaignId={campaignId} digest={query.data} week={week} narrativeAvailable={narrativeAvailable} />;
}

function DigestView({ campaignId, digest, week, narrativeAvailable }: { campaignId: string; digest: Digest; week: string; narrativeAvailable: boolean }) {
  const c = digest.content;
  const regenerate = useCreateDigest(campaignId);
  const summary = useAddSummary(campaignId, digest.id);
  const exporter = useMutation({ mutationFn: (format: ExportFormat) => downloadDigest(campaignId, digest, format) });
  const error = regenerate.error ?? summary.error ?? exporter.error;
  return (
    <article aria-label={`Weekly digest ${c.week.label}`} className="space-y-7">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 border-b border-border pb-4">
        <div className="min-w-0 space-y-1">
          <h3 className="type-title text-[24px] text-ink">{c.week.label}</h3>
          <p className="type-ledger text-[13px] text-ink-secondary">
            {weekSpan(c.week.start, c.week.end)} · revision {digest.revision} · {digest.trigger === "scheduler" ? "built by the weekly schedule" : "built on request"} {formatDateTime(digest.generated_at)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {(["md", "pdf"] as const).map((f) => (
            <Button key={f} variant="outline" size="sm" onClick={() => exporter.mutate(f)} disabled={exporter.isPending}>
              {exporter.isPending && exporter.variables === f ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <Download aria-hidden />}
              {EXPORT_LABEL[f]}
            </Button>
          ))}
          <Button variant="ghost" size="sm" onClick={() => regenerate.mutate({ week_of: week, regenerate: true })} disabled={regenerate.isPending} title="Build this week again from the records as they are now">
            {regenerate.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <RefreshCw aria-hidden />}
            Regenerate
          </Button>
          {narrativeAvailable && !digest.narrative && (
            <Button variant="outline" size="sm" onClick={() => summary.mutate()} disabled={summary.isPending} title="A model writes a short summary from the figures below; code rejects it if it holds a number the digest does not">
              {summary.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <Sparkles aria-hidden />}
              {summary.isPending ? "Writing…" : "Add a short summary"}
            </Button>
          )}
        </div>
      </div>
      {error && <ErrorState error={error} />}
      {digest.narrative ? (
        <section aria-labelledby="digest-summary" className="space-y-2 rounded-card border border-border bg-surface px-4 py-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 id="digest-summary" className="text-[15px] font-semibold text-ink">
              Summary
            </h3>
            <ModelTag />
          </div>
          <p className="max-w-[72ch] text-[14.5px] leading-relaxed text-ink-body">{digest.narrative.text}</p>
          <p className="type-meta">
            Written by {digest.narrative.model_id ?? digest.narrative.provider} from the figures below. A hypothesis to judge, not a record.
          </p>
        </section>
      ) : !narrativeAvailable ? (
        <p className="type-meta">The short written summary needs a model and is available in live projects only. This digest is numbers and lists.</p>
      ) : null}
      <WhatChanged campaignId={campaignId} content={c} />
      <PulseMovement campaignId={campaignId} content={c} />
      <CommentsSection campaignId={campaignId} content={c} />
      <OpenItems campaignId={campaignId} content={c} />
      <NextActions campaignId={campaignId} content={c} />
      <Limitations content={c} />
    </article>
  );
}
