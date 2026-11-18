"use client";

import { CalendarDays, ChevronDown, LoaderCircle, RefreshCw } from "lucide-react";
import { useId, useState } from "react";

import { ConfidenceIndicator } from "@/components/evidence/confidence";
import { Tag } from "@/components/evidence/badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { dayLabel } from "@/features/lens/format";
import { Labelled, NativeSelect } from "@/features/lens/parts";
import { SectionTitle } from "@/features/workspaces/parts";
import { ApiError } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useRefreshRadar, useTrendRadar, type TrendEdition, type TrendItem, type TrendMoment, type TrendRadar, type TrendRegion } from "./api";
import { DirectionTag, Sparkline, SourceChip, monthName, num, percent } from "./parts";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="type-meta">{label}</dt>
      <dd className="type-ledger text-[13px] text-ink">{children}</dd>
    </div>
  );
}

function EditionRow({ e }: { e: TrendEdition }) {
  return (
    <tr className="border-t border-border">
      <td className="py-1 pr-3">
        {e.language_name} {e.is_regional ? "(the state's edition)" : "(read worldwide)"}
      </td>
      <td className="py-1 pr-3">
        <a href={e.article_url} target="_blank" rel="noreferrer" className="underline decoration-border-strong underline-offset-2 hover:text-ink">
          {e.article}
        </a>
      </td>
      <td className="py-1 pr-3 text-right">{num.format(e.total_views)}</td>
      <td className="py-1 pr-3 text-right">{e.recent_mean == null ? "n/a" : num.format(e.recent_mean)}</td>
      <td className="py-1 text-right">
        <DirectionTag direction={e.direction} className="text-[12.5px]" />
      </td>
    </tr>
  );
}

function ItemDetail({ item }: { item: TrendItem }) {
  const p = item.primary;
  const w = item.windows;
  return (
    <div className="space-y-3 border-t border-border bg-surface-muted/40 px-4 py-3.5">
      {w && (
        <p className="text-[13px] text-ink-body">
          The last 12 months ({monthName(w.recent_from)} to {monthName(w.recent_to)}) against the 12 before ({monthName(w.prior_from)} to {monthName(w.prior_to)}).
          {p.normalised ? " Attention is a share of the edition's readership." : " The edition's totals were not read, so this is raw views."}
        </p>
      )}
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2.5 sm:grid-cols-4">
        <Fact label={p.normalised ? "Share of readership, change" : "Views, change"}>{percent(p.change)}</Fact>
        {p.normalised && (
          <Fact label="Per million edition views">
            {p.recent_per_million == null ? "n/a" : num.format(p.recent_per_million)} against {p.prior_per_million == null ? "n/a" : num.format(p.prior_per_million)}
          </Fact>
        )}
        <Fact label="Raw views, change">
          {percent(p.raw_change)} ({p.recent_mean == null ? "n/a" : num.format(p.recent_mean)} a month)
        </Fact>
        {p.normalised && <Fact label="Whole edition, change">{percent(p.edition_change)}</Fact>}
        <Fact label={w ? `Lately: ${monthName(w.quarter_from)} to ${monthName(w.quarter_to)}` : "Lately"}>
          {percent(p.quarter_change)} on the same months a year earlier
        </Fact>
      </dl>
      {item.reasons.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-[13px] text-ink-body">
          {item.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      <p className="text-[13px] text-ink-secondary">
        <span className="font-medium text-ink">Confidence {item.confidence}:</span> {item.confidence_reasons.join(" ")}
      </p>
      <div className="overflow-x-auto">
        <table className="type-ledger w-full min-w-[30rem] text-left text-[12.5px]">
          <thead className="text-ink-muted">
            <tr>
              <th className="py-1 pr-3 font-normal">Edition</th>
              <th className="py-1 pr-3 font-normal">Article</th>
              <th className="py-1 pr-3 text-right font-normal">Views, 24 months</th>
              <th className="py-1 pr-3 text-right font-normal">A month, last 12</th>
              <th className="py-1 text-right font-normal">Direction</th>
            </tr>
          </thead>
          <tbody className="text-ink-body">
            <EditionRow e={item.primary} />
            {item.reference && <EditionRow e={item.reference} />}
          </tbody>
        </table>
      </div>
      {item.history.length > 0 && (
        <p className="text-[13px] text-ink-secondary">
          Earlier readings, read with the same method:{" "}
          {item.history.map((h) => `${formatDateTime(h.taken_at)}: ${h.direction === "insufficient" ? "not enough data" : h.direction}${h.change == null ? "" : ` (${percent(h.change)})`}`).join("; ")}.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <SourceChip label={item.source.label} url={item.source.url} />
        <span className="type-meta">
          Counts observed, direction calculated. Retrieved {formatDateTime(item.source.retrieved_at)}. {item.snapshots} {item.snapshots === 1 ? "reading" : "readings"} kept.
        </span>
      </div>
    </div>
  );
}

function ItemRow({ item, open, onToggle }: { item: TrendItem; open: boolean; onToggle(): void }) {
  const id = useId();
  return (
    <li id={`radar-${item.key}`} className="min-w-0">
      <div className="grid items-center gap-x-4 gap-y-1.5 px-4 py-2.5 sm:grid-cols-[minmax(0,1.5fr)_minmax(0,10rem)_8.5rem_7.5rem_2rem]">
        <div className="min-w-0">
          <p className="truncate text-[14.5px] font-medium text-ink">{item.label}</p>
          <p className="flex flex-wrap items-center gap-x-2 text-[12.5px] text-ink-secondary">
            <span>{item.term_kind === "festival" ? "Festival" : "Category"}</span>
            {item.basis === "english_only" && <Tag className="border-border text-ink-secondary">English edition only</Tag>}
          </p>
        </div>
        <div className="min-w-0">
          <DirectionTag direction={item.direction} />
          <p className="type-ledger text-[12.5px] text-ink-secondary">{item.change == null ? "No change computed" : `${percent(item.change)} on the year before`}</p>
        </div>
        <Sparkline series={item.primary.series} label={`${item.label}, ${item.primary.language_name} Wikipedia`} />
        <ConfidenceIndicator level={item.confidence} />
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-controls={id}
          aria-label={`${open ? "Hide" : "Show"} how ${item.label} was read`}
          className="inline-flex size-8 items-center justify-center justify-self-end rounded-md text-ink-secondary hover:bg-surface-muted hover:text-ink focus-visible:outline-2 focus-visible:outline-pop"
        >
          <ChevronDown aria-hidden className={cn("size-4 transition-transform motion-reduce:transition-none", open && "rotate-180")} />
        </button>
      </div>
      {open && (
        <div id={id}>
          <ItemDetail item={item} />
        </div>
      )}
    </li>
  );
}

function Moments({ region, radar, onOpen }: { region: TrendRegion; radar: TrendRadar; onOpen(key: string): void }) {
  if (region.moments.length === 0) return null;
  const items = new Map(region.items.map((i) => [i.key, i]));
  const window = radar.moments_window;
  return (
    <div className="space-y-1.5">
      <p className="flex items-center gap-1.5 text-[13px] text-ink-secondary">
        <CalendarDays aria-hidden className="size-3.5" />
        {radar.moments_window_basis === "campaign_dates" ? "Moments inside the campaign dates" : "Moments in the next 120 days"} ({dayLabel(window.date_from)} to {dayLabel(window.date_to)})
      </p>
      <ul className="ledger-rules rounded-card border border-border bg-surface">
        {region.moments.map((m: TrendMoment) => {
          const linked = m.term_key ? items.get(m.term_key) : undefined;
          return (
            <li key={`${m.name}-${m.date ?? m.timing_text}`} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-4 py-2 text-[13.5px]">
              <span className="min-w-0 text-ink">
                {m.name} <span className="type-ledger text-ink-secondary">· {m.date ? dayLabel(m.date) : m.timing_text}</span>
              </span>
              <span className="flex items-center gap-3 text-[12.5px] text-ink-secondary">
                {m.date && m.days_until != null && <span className="type-ledger">in {m.days_until} days</span>}
                {linked && (
                  <button type="button" onClick={() => onOpen(linked.key)} className="inline-flex items-center gap-1 underline decoration-border-strong underline-offset-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-pop">
                    Attention: <DirectionTag direction={linked.direction} className="text-[12.5px]" />
                  </button>
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function RegionSection({ region, radar, open, onToggle }: { region: TrendRegion; radar: TrendRadar; open: string | null; onToggle(key: string): void }) {
  return (
    <section aria-labelledby={`radar-${region.region_code}`} className="space-y-3">
      <SectionTitle
        id={`radar-${region.region_code}`}
        meta={region.supported ? `${region.edition_name} Wikipedia${region.refreshed_at ? `, read ${formatDateTime(region.refreshed_at)}` : ""}` : "No regional edition mapped"}
      >
        {region.region_name}
      </SectionTitle>
      <Moments region={region} radar={radar} onOpen={onToggle} />
      {region.items.length > 0 && (
        <ul className="ledger-rules rounded-card border border-border bg-surface">
          {region.items.map((item) => (
            <ItemRow key={item.key} item={item} open={open === item.key} onToggle={() => onToggle(item.key)} />
          ))}
        </ul>
      )}
      {region.gaps.length > 0 && (
        <ul className="space-y-0.5 text-[13px] text-ink-secondary">
          {region.gaps.map((g) => (
            <li key={g}>{g}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function TrendRadarView({ campaignId }: { campaignId: string }) {
  const radar = useTrendRadar(campaignId, []);
  const refresh = useRefreshRadar(campaignId);
  const [only, setOnly] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const selectId = useId();
  const data = radar.data;
  const error = refresh.error instanceof ApiError ? refresh.error : null;
  const shown = (data?.regions ?? []).filter((r) => !only || r.region_code === only);
  const read = shown.flatMap((r) => r.items);
  const live = data?.mode === "live";

  const toggle = (key: string) => {
    setOpen((cur) => (cur === key ? null : key));
    document.getElementById(`radar-${key}`)?.scrollIntoView({ block: "nearest" });
  };

  if (radar.isPending) return <LoadingState label="Reading the Trend Radar…" />;
  if (radar.isError) return <ErrorState error={radar.error} onRetry={() => void radar.refetch()} />;
  if (!data || data.regions.length === 0) {
    return <EmptyState title="No state to read" description="The campaign names no state. Add target regions to the brief, then come back." />;
  }
  const refreshButton = (
    <Button type="button" variant="outline" onClick={() => refresh.mutate(only ? [only] : [])} disabled={refresh.isPending || !data.can_refresh}>
      {refresh.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <RefreshCw aria-hidden />}
      {refresh.isPending ? "Reading…" : data.refreshed_at ? "Refresh attention" : "Read attention"}
    </Button>
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-3">
        <Labelled label="State" htmlFor={selectId}>
          <NativeSelect id={selectId} value={only} onChange={(e) => setOnly(e.target.value)}>
            <option value="">All campaign states</option>
            {data.regions.map((r) => (
              <option key={r.region_code} value={r.region_code}>
                {r.region_name}
              </option>
            ))}
          </NativeSelect>
        </Labelled>
        {refreshButton}
        {refresh.isPending && (
          <p role="status" className="text-[12.5px] text-ink-secondary">
            {live ? "Reading Wikipedia pageviews, paced to stay polite. This can take up to a minute." : "Reading the recording."}
          </p>
        )}
        {!data.can_refresh && <p className="text-[12.5px] text-ink-secondary">Your role can read this view but not refresh it.</p>}
      </div>
      {error && (
        <p role="alert" className="rounded-lg border border-danger/35 bg-danger-soft/60 px-3 py-2 text-[13px] text-ink">
          {error.message}
          {error.details.map((d) => ` ${d.message}`).join("")}
        </p>
      )}

      {read.length === 0 && !data.refreshed_at ? (
        <EmptyState
          title="Attention has not been read yet"
          description="Reading takes the festival articles the state's claims cite and the category's own topics, and keeps each reading so the next one can be compared with it."
          action={data.can_refresh ? refreshButton : undefined}
        />
      ) : (
        <>
          <p className="type-ledger text-[13.5px] text-ink-body" aria-live="polite">
            {read.length} {read.length === 1 ? "article" : "articles"} read: {count(read, "rising")} rising, {count(read, "falling")} falling, {count(read, "steady")} steady, {count(read, "mixed")} mixed, {count(read, "insufficient")} without enough data.
          </p>
          {shown.map((r) => (
            <RegionSection key={r.region_code} region={r} radar={data} open={open} onToggle={toggle} />
          ))}
        </>
      )}

      <details className="rounded-card border border-border bg-surface px-4 py-3 text-[13.5px]">
        <summary className="cursor-pointer font-medium text-ink">How rising and falling is calculated</summary>
        <div className="mt-2 space-y-2 text-ink-body">
          <p className="max-w-[78ch]">{data.method.description}</p>
          <ul className="list-disc space-y-0.5 pl-5 text-ink-secondary">
            {data.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
          <p className="type-meta">Method {data.method.version}.</p>
        </div>
      </details>
      <p className="type-meta">{data.source_line}</p>
    </div>
  );
}

function count(items: TrendItem[], direction: TrendItem["direction"]) {
  return items.filter((i) => i.direction === direction).length;
}
