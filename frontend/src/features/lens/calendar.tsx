"use client";

import { CalendarCheck, GitCompareArrows } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { SectionTitle } from "@/features/workspaces/parts";
import { cn } from "@/lib/utils";

import { useCalendar, type LensCalendar, type LensDatedMoment, type LensTimedMoment } from "./api";
import { ClaimEntry } from "./claim-entry";
import { ConflictList } from "./conflicts";
import { MONTHS, dayLabel, dayOfMonth } from "./format";
import { Labelled, NativeSelect, SourcesPanel } from "./parts";
import { StateSelect } from "./state-select";

const BASIS: Record<LensDatedMoment["date_basis"], string> = {
  public_holiday_list: "Public holiday list",
  source_text: "Date stated by a source",
};

function windowMonths(from: string, to: string) {
  const out = new Set<number>();
  const end = new Date(to);
  for (let d = new Date(from); d <= end; d = new Date(d.getFullYear(), d.getMonth() + 1, 1)) out.add(d.getMonth() + 1);
  return out;
}

function MonthGrid({
  calendar,
  selected,
  onSelect,
}: {
  calendar: LensCalendar;
  selected: string | null;
  onSelect(key: string): void;
}) {
  const inWindow = calendar.window ? windowMonths(calendar.window.date_from, calendar.window.date_to) : new Set<number>();
  return (
    <ol aria-label={`Moments in ${calendar.year}`} className="grid gap-px overflow-hidden rounded-card border border-border bg-border sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {calendar.months.map((m) => (
        <li key={m.month} className="min-w-0 bg-surface px-3 py-2.5">
          <div className="mb-1.5 flex items-baseline justify-between gap-2">
            <h3 className="text-[13.5px] font-semibold text-ink">{MONTHS[m.month - 1]}</h3>
            {inWindow.has(m.month) && (
              <span className="inline-flex items-center gap-1 text-[11.5px] font-medium text-ink-secondary">
                <CalendarCheck aria-hidden className="size-3" />
                Campaign window
              </span>
            )}
          </div>
          {m.dated.length === 0 ? (
            <p className="text-[12.5px] text-ink-muted">No dated moment</p>
          ) : (
            <ul className="-mx-1.5 space-y-px">
              {m.dated.map((d) => {
                const on = d.key === selected;
                return (
                  <li key={d.key}>
                    <button
                      type="button"
                      onClick={() => onSelect(d.key)}
                      aria-pressed={on}
                      className={cn(
                        "flex min-h-8 w-full items-start gap-2 rounded-md px-1.5 py-1 text-left text-[13px] hover:bg-surface-muted",
                        on && "bg-surface-raised outline-1 -outline-offset-1 outline-pop",
                      )}
                    >
                      <span className="type-ledger w-5 shrink-0 text-right text-ink-secondary">{dayOfMonth(d.date)}</span>
                      <span className="min-w-0 flex-1 text-ink">
                        {d.name}
                        {d.in_window && <span className="ml-1.5 rounded-stamp border border-border-strong/60 px-1 text-[11px] text-ink-secondary">In window</span>}
                        {d.claim.conflict_ids.length > 0 && <GitCompareArrows aria-label="Open conflict" className="ml-1 inline size-3 text-warning" />}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </li>
      ))}
    </ol>
  );
}

function DatedDetail({ moment }: { moment: LensDatedMoment }) {
  return (
    <section aria-label={`${moment.name} evidence`} className="space-y-3 rounded-card border border-border bg-surface-muted/50 px-4 py-4">
      <div>
        <h3 className="text-[15px] font-semibold text-ink">
          {moment.name}: {dayLabel(moment.date)}
        </h3>
        <p className="type-meta">
          {BASIS[moment.date_basis]}
          {moment.in_window === true && " · inside the campaign window"}
          {moment.in_window === false && " · outside the campaign window"}
        </p>
      </div>
      <ClaimEntry claim={moment.claim} />
      {moment.also_stated_by.length > 0 && (
        <div className="space-y-2">
          <p className="text-[12.5px] text-ink-secondary">Another source gives the same date in its own words. It is a separate claim with its own tags.</p>
          {moment.also_stated_by.map((c) => (
            <ClaimEntry key={c.id} claim={c} />
          ))}
        </div>
      )}
    </section>
  );
}

function TimedRow({ moment }: { moment: LensTimedMoment }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <li className="space-y-2 px-4 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="text-[14.5px] font-medium text-ink">{moment.name}</p>
        <p className="flex flex-wrap items-center gap-x-3 text-[12.5px]">
          {moment.conflict_ids.length > 0 && (
            <span className="inline-flex items-center gap-1 text-warning">
              <GitCompareArrows aria-hidden className="size-3.5" />
              Sources disagree
            </span>
          )}
          {moment.may_overlap_window === true && (
            <span className="inline-flex items-center gap-1 text-ink">
              <CalendarCheck aria-hidden className="size-3.5" />
              May overlap the window
            </span>
          )}
          {moment.may_overlap_window === false && <span className="text-ink-muted">Outside the window</span>}
        </p>
      </div>
      {moment.timings.length === 0 ? (
        <p className="text-[13px] text-ink-muted">The sources collected state no timing for this one.</p>
      ) : (
        <ul className="space-y-1 text-[13.5px] text-ink-body">
          {moment.timings.map((t) => (
            <li key={t.claim.id}>
              “{t.text}”
            </li>
          ))}
        </ul>
      )}
      <p className="type-ledger text-[12.5px] text-ink-secondary">
        {moment.months_named.length > 0 ? `Months named: ${moment.months_named.map((m) => MONTHS[m - 1]).join(", ")}. ` : ""}
        {moment.dated_for_year.length > 0 ? `Dated this year in the public holiday list: ${moment.dated_for_year.map(dayLabel).join("; ")}.` : "No exact date for this year."}
      </p>
      {moment.timings.length > 0 && (
        <>
          <Button type="button" variant="ghost" size="xs" aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>
            {open ? "Hide evidence" : "Show evidence"}
          </Button>
          {open && (
            <div id={id} className="space-y-2.5">
              {moment.timings.map((t) => (
                <ClaimEntry key={t.claim.id} claim={t.claim} />
              ))}
            </div>
          )}
        </>
      )}
    </li>
  );
}

export function CalendarView({
  campaignId,
  region,
  onRegion,
}: {
  campaignId: string;
  region: string | null;
  onRegion(code: string): void;
}) {
  const [year, setYear] = useState<number | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const yearId = useId();
  const fromId = useId();
  const toId = useId();
  const [selected, setSelected] = useState<string | null>(null);
  const validWindow = from !== "" && to !== "" && from <= to;
  const cal = useCalendar(campaignId, region, year, validWindow ? from : null, validWindow ? to : null);
  const data = cal.data;
  const thisYear = new Date().getFullYear();
  const years = Array.from(new Set([...(data?.years_available ?? []), thisYear, thisYear + 1, ...(year ? [year] : [])])).sort();
  const moment = data?.months.flatMap((m) => m.dated).find((d) => d.key === selected) ?? null;
  const total = data?.months.reduce((n, m) => n + m.dated.length, 0) ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-3">
        <StateSelect campaignId={campaignId} value={region} onChange={onRegion} className="w-full sm:w-64" />
        <Labelled label="Year" htmlFor={yearId}>
          <NativeSelect id={yearId} value={year ?? data?.year ?? thisYear} onChange={(e) => setYear(Number(e.target.value))}>
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
                {data && !data.years_available.includes(y) ? " (not built)" : ""}
              </option>
            ))}
          </NativeSelect>
        </Labelled>
        <Labelled label="Campaign window from" htmlFor={fromId}>
          <input id={fromId} type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="clay-well h-8 rounded-lg border border-border-strong/55 bg-surface-muted px-2 text-[13.5px] text-ink" />
        </Labelled>
        <Labelled label="to" htmlFor={toId}>
          <input id={toId} type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} className="clay-well h-8 rounded-lg border border-border-strong/55 bg-surface-muted px-2 text-[13.5px] text-ink" />
        </Labelled>
        {(from || to) && (
          <Button type="button" variant="ghost" onClick={() => { setFrom(""); setTo(""); }}>
            Clear window
          </Button>
        )}
      </div>
      {(from || to) && !validWindow && <p role="status" className="text-[13px] text-warning">Give both dates, with the start on or before the end, to compare moments with a campaign window.</p>}

      {!region && <EmptyState title="Choose a state" description="The calendar shows dated moments for a year, each date a claim with its source, and the festivals sources describe without an exact date." />}
      {region && cal.isPending && <LoadingState label="Reading the calendar…" />}
      {region && cal.isError && <ErrorState error={cal.error} onRetry={() => void cal.refetch()} />}

      {data && (
        <>
          <section aria-labelledby="cal-grid" className="space-y-3">
            <SectionTitle id="cal-grid" meta={`${total} dated ${total === 1 ? "moment" : "moments"} in ${data.region.name}`}>
              {data.region.name} in {data.year}
            </SectionTitle>
            {data.gaps.length > 0 && (
              <ul className="space-y-1 text-[13.5px] text-ink-body">
                {data.gaps.map((g) => (
                  <li key={g}>{g}</li>
                ))}
              </ul>
            )}
            {data.window && (
              <p className="text-[13px] text-ink-secondary">
                Comparing with the campaign window {dayLabel(data.window.date_from)} to {dayLabel(data.window.date_to)}. Moments inside it are marked.
              </p>
            )}
            <MonthGrid calendar={data} selected={selected} onSelect={setSelected} />
            {moment ? <DatedDetail moment={moment} /> : total > 0 && <p className="text-[13px] text-ink-muted">Select a moment to see its source, date and confidence.</p>}
          </section>

          <section aria-labelledby="cal-timed" className="space-y-3">
            <SectionTitle id="cal-timed" meta={`${data.timed.length} festivals and moments`}>
              Timing as sources state it
            </SectionTitle>
            <p className="max-w-[68ch] text-[13px] text-ink-secondary">
              These have no exact date for {data.year}. The wording is the source&apos;s own; months named are read from it as hints for overlap, never as a date.
            </p>
            {data.timed.length === 0 ? (
              <p className="rounded-card border border-dashed border-border-strong/50 bg-surface-muted/50 px-4 py-3 text-[13.5px] text-ink-secondary">No festival or moment is recorded for this state in this mode.</p>
            ) : (
              <ul className="ledger-rules rounded-card border border-border bg-surface">
                {data.timed.map((t) => (
                  <TimedRow key={t.subject} moment={t} />
                ))}
              </ul>
            )}
          </section>

          {data.conflicts.length > 0 && (
            <section aria-labelledby="cal-conflicts" className="space-y-3">
              <SectionTitle id="cal-conflicts">Where sources disagree</SectionTitle>
              <ConflictList conflicts={data.conflicts} campaignId={campaignId} workspaceId={data.workspace_id} />
            </section>
          )}
          <SourcesPanel sources={data.sources} limitations={data.limitations} modeLabel={data.mode_label} />
        </>
      )}
    </div>
  );
}
