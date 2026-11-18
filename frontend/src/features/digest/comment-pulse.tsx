"use client";

import { LoaderCircle, MessagesSquare, RotateCcw, ScanText } from "lucide-react";
import { useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { PULSE_THEME, Segmented, SelectField } from "@/features/pulse/ui";
import { regionLabel, shortVersion, sortRegions } from "@/features/pulse/logic";
import type { components } from "@/lib/api/schema";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { NO_FILTERS, useCommentStatus, useCommentSummary, useLoadComments, useReadComments, type CommentFilters } from "./api";
import { CommentList } from "./comment-list";
import { CommentThemes } from "./comment-themes";
import { SlicesTable, VolumeSection } from "./comment-trends";
import { COMMENT_SOURCE, LANGUAGE_NAME, runWeeks } from "./logic";
import { ModelTag, SourceLine } from "./ui";

type Status = components["schemas"]["CommentDatasetStatus"];
type Summary = components["schemas"]["CommentSummary"];

/** Comment Pulse (feature 46): what viewers write under the campaign's videos. Counts and trends are code; sentiment and themes are a model reading. */
export function CommentPulse({ campaignId }: { campaignId: string }) {
  const status = useCommentStatus(campaignId);
  const loaded = status.data?.loaded === true;
  return (
    <div className={cn("space-y-8", PULSE_THEME)}>
      <header className="space-y-1.5">
        <h2 className="type-title text-[22px] text-ink">Comment Pulse</h2>
        <p className="max-w-[68ch] text-[14.5px] text-ink-secondary">
          What viewers say under the campaign&apos;s videos, by region, language and version. Counts and trends are calculated; sentiment and themes are read by a model and marked as such.
        </p>
        <SourceLine>{COMMENT_SOURCE}</SourceLine>
      </header>
      {status.error ? (
        <ErrorState error={status.error} onRetry={() => void status.refetch()} />
      ) : !status.data ? (
        <LoadingState label="Checking the sample comments…" />
      ) : loaded ? (
        <Loaded campaignId={campaignId} status={status.data} />
      ) : (
        <NotLoaded campaignId={campaignId} />
      )}
    </div>
  );
}

function NotLoaded({ campaignId }: { campaignId: string }) {
  const load = useLoadComments(campaignId);
  return (
    <div className="space-y-3">
      <EmptyState
        title="No comments are loaded"
        description={
          <div className="space-y-2">
            <p>
              Comment Pulse reads public comments under a campaign&apos;s videos. No channel can be connected in this build, so it runs on a set of sample comments written in Marathi, Tamil, Malayalam, Bengali and English, some mixing the
              regional language with English.
            </p>
            <p>Counts, languages and trends are calculated from the comments. Sentiment and themes need a model to read them, and are marked as its interpretation.</p>
          </div>
        }
        needs={[
          { label: "The sample comments: load them below", met: false },
          { label: "A connected channel: roadmap, not available in this build", met: false },
        ]}
        action={
          <div className="space-y-2">
            <Button size="lg" onClick={() => load.mutate()} disabled={load.isPending}>
              {load.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <MessagesSquare aria-hidden />}
              {load.isPending ? "Loading the comments…" : "Load the sample comments"}
            </Button>
            <p className="max-w-[60ch] text-[12.5px] text-ink-muted">Loading writes the sample comments to this campaign. Loading again replaces them with identical ones. Only an owner or editor can load them.</p>
          </div>
        }
      />
      {load.error && <ErrorState error={load.error} onRetry={() => load.mutate()} />}
    </div>
  );
}

function Loaded({ campaignId, status }: { campaignId: string; status: Status }) {
  const [filters, setFilters] = useState<CommentFilters>(NO_FILTERS);
  const summary = useCommentSummary(campaignId, filters, true);
  return (
    <>
      <FilterRow status={status} value={filters} onChange={setFilters} />
      {summary.error && !summary.data ? (
        <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />
      ) : !summary.data ? (
        <LoadingState label="Counting the comments…" />
      ) : (
        <>
          <Facts summary={summary.data} stale={summary.isPlaceholderData} />
          <Reading campaignId={campaignId} summary={summary.data} />
          <VolumeSection summary={summary.data} stale={summary.isPlaceholderData} />
          <SlicesTable summary={summary.data} stale={summary.isPlaceholderData} />
          <CommentThemes campaignId={campaignId} filters={filters} />
          <CommentList campaignId={campaignId} filters={filters} summary={summary.data} />
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------- filters

function FilterRow({ status, value, onChange }: { status: Status; value: CommentFilters; onChange: (f: CommentFilters) => void }) {
  const weeks = runWeeks(status.date_from, status.date_to);
  const active = weeks.find((w) => w.from === value.from && w.to === value.to)?.key ?? (value.from === null && value.to === null ? "all" : null);
  const dirty = JSON.stringify(value) !== JSON.stringify(NO_FILTERS);
  return (
    <div role="group" aria-label="Filters for the sections below" className="flex flex-wrap items-end gap-x-5 gap-y-3 border-b border-border pb-4">
      <div className="space-y-1">
        <p className="text-[12px] font-medium text-ink-secondary">Period</p>
        <Segmented
          label="Period"
          value={active}
          onChange={(k) => {
            const w = weeks.find((x) => x.key === k);
            onChange({ ...value, from: w?.from ?? null, to: w?.to ?? null });
          }}
          options={[{ value: "all", label: "Whole run" }, ...weeks.map((w) => ({ value: w.key, label: w.label, title: `${w.from} to ${w.to}` }))]}
        />
      </div>
      <SelectField
        label="Region"
        className="w-44"
        value={value.region ?? ""}
        onChange={(v) => onChange({ ...value, region: v || null })}
        options={[{ value: "", label: "All regions" }, ...sortRegions(status.regions, (r) => r).map((r) => ({ value: r, label: regionLabel(r) }))]}
      />
      <SelectField
        label="Version"
        className="w-56"
        value={value.version ?? ""}
        onChange={(v) => onChange({ ...value, version: v || null })}
        options={[{ value: "", label: "All versions" }, ...status.versions.map((v) => ({ value: v, label: `${shortVersion(v)} (${v.split(" ")[0]})` }))]}
      />
      <SelectField
        label="Language"
        className="w-40"
        value={value.language ?? ""}
        onChange={(v) => onChange({ ...value, language: v || null })}
        options={[{ value: "", label: "All languages" }, ...status.languages.map((l) => ({ value: l, label: LANGUAGE_NAME[l] ?? l }))]}
      />
      {dirty && (
        <Button variant="ghost" size="sm" onClick={() => onChange(NO_FILTERS)} className="text-ink-secondary">
          <RotateCcw aria-hidden />
          Reset filters
        </Button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- facts and the reading

function Facts({ summary, stale }: { summary: Summary; stale: boolean }) {
  const t = summary.totals;
  const c = summary.coverage;
  const rows: { label: string; value: string; note: string }[] = [
    { label: "Comments in view", value: String(c.comments_in_view), note: c.comments_in_view === c.comments_in_dataset ? "the whole sample" : `of ${c.comments_in_dataset} in the sample` },
    { label: "Languages", value: String(c.languages_in_view), note: summary.languages.map((l) => l.language_name).join(", ") || "none" },
    { label: "Claim mentions", value: String(t.claim_mentions), note: "match a watch term in the text" },
    { label: "Festival mentions", value: String(t.cultural_mentions), note: "name a different festival" },
  ];
  return (
    <dl aria-busy={stale} className={cn("grid divide-y divide-border rounded-card border border-border bg-surface sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4 lg:divide-x", stale && "opacity-60")}>
      {rows.map((r) => (
        <div key={r.label} className="space-y-0.5 px-4 py-3">
          <dt className="type-ledger text-[12.5px] text-ink-muted">{r.label}</dt>
          <dd className="type-title text-[26px] leading-tight text-ink tabular-nums">{r.value}</dd>
          <dd className="text-[12.5px] text-ink-secondary">{r.note}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The model reading that sentiment and themes come from: who made it, with which prompt, what was labelled, and the action to make one. */
function Reading({ campaignId, summary }: { campaignId: string; summary: Summary }) {
  const read = useReadComments(campaignId);
  const a = summary.analysis;
  return (
    <section aria-labelledby="reading" className="space-y-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 id="reading" className="text-[15px] font-semibold text-ink">
          Reading of sentiment and themes
        </h3>
        <ModelTag />
      </div>
      {a ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-surface px-4 py-3">
          <div className="min-w-0 space-y-1 text-[13.5px] text-ink-body">
            <p>
              {a.is_fixture ? "Read from labelled fixtures, not a model" : `Read by ${a.model_id ?? a.provider}`}
              <span className="text-ink-secondary">
                {" "}
                · {a.read_count} of {a.comment_count} comments labelled · {formatDateTime(a.created_at)}
              </span>
            </p>
            <p className="type-meta">
              Prompt <span className="font-mono">{a.prompt_version}</span>
              {a.estimated_cost_usd !== null && a.estimated_cost_usd !== undefined ? ` · estimated cost $${a.estimated_cost_usd.toFixed(4)}` : ""}
            </p>
            {a.notes.length > 0 && (
              <ul className="list-disc space-y-0.5 pl-4 text-[12.5px] text-ink-secondary">
                {a.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            )}
          </div>
          <Button variant="outline" size="sm" onClick={() => read.mutate(true)} disabled={read.isPending}>
            {read.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <ScanText aria-hidden />}
            {read.isPending ? "Reading…" : "Read again"}
          </Button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-dashed border-border-strong/50 bg-surface-muted/50 px-4 py-3">
          <p className="max-w-[60ch] text-[13.5px] text-ink-secondary">
            No reading yet. A model labels each comment&apos;s sentiment and groups themes in one call. The counts and trends on this page do not depend on it.
          </p>
          <Button onClick={() => read.mutate(false)} disabled={read.isPending}>
            {read.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <ScanText aria-hidden />}
            {read.isPending ? "Reading the comments…" : "Read the comments"}
          </Button>
        </div>
      )}
      {read.error && <ErrorState error={read.error} onRetry={() => read.mutate(false)} />}
    </section>
  );
}
