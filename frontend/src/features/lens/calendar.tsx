"use client";

import { CalendarCheck, GitCompareArrows } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { SectionTitle } from "@/features/workspaces/parts";

import { useCalendar, type LensTimedMoment } from "./api";
import { MomentCalendar } from "./calendar-year";
import { ClaimEntry } from "./claim-entry";
import { ConflictList } from "./conflicts";
import { MONTHS, dayLabel } from "./format";
import { DataSources, Labelled, NativeSelect, SourcesPanel } from "./parts";
import { StateSelect } from "./state-select";

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

/**
 * Moment Calendar: a state's year as a real calendar (every dated moment by kind, the campaign dates as a band, a card for
 * each day), an agenda that reads the same moments as a list, the festivals sources describe without an exact date, and
 * the datasets and sources behind it all.
 */
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
  const validWindow = from !== "" && to !== "" && from <= to;
  const cal = useCalendar(campaignId, region, year, validWindow ? from : null, validWindow ? to : null);
  const data = cal.data;
  const thisYear = new Date().getFullYear();
  const years = Array.from(new Set([thisYear - 1, thisYear, thisYear + 1, thisYear + 2, ...(data?.years_available ?? []), ...(year ? [year] : [])])).sort((a, b) => a - b);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-3">
        <StateSelect campaignId={campaignId} value={region} onChange={onRegion} className="w-full sm:w-64" />
        <Labelled label="Year" htmlFor={yearId}>
          <NativeSelect id={yearId} value={year ?? data?.year ?? thisYear} onChange={(e) => setYear(Number(e.target.value))} className="max-sm:h-11">
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </NativeSelect>
        </Labelled>
        <Labelled label="Campaign window from" htmlFor={fromId}>
          <input id={fromId} type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="clay-well h-11 rounded-lg border border-border-strong/55 bg-surface-muted px-2 text-[13.5px] text-ink sm:h-8" />
        </Labelled>
        <Labelled label="to" htmlFor={toId}>
          <input id={toId} type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} className="clay-well h-11 rounded-lg border border-border-strong/55 bg-surface-muted px-2 text-[13.5px] text-ink sm:h-8" />
        </Labelled>
        {(from || to) && (
          <Button type="button" variant="ghost" className="max-sm:h-11" onClick={() => { setFrom(""); setTo(""); }}>
            Clear window
          </Button>
        )}
      </div>
      {(from || to) && !validWindow && <p role="status" className="text-[13px] text-warning">Give both dates, with the start on or before the end, to compare moments with a campaign window.</p>}

      {!region && (
        <EmptyState
          title="Choose a state"
          description="The calendar shows every dated moment of a state's year: what each one is, why it matters for a campaign and where its date comes from, with the festivals sources describe without an exact date."
        />
      )}
      {region && cal.isPending && <LoadingState label="Reading the calendar…" />}
      {region && cal.isError && <ErrorState error={cal.error} onRetry={() => void cal.refetch()} />}

      {data && (
        <>
          {/* Keyed so a new state, year or window starts on its own opening day and plays its entrance again. */}
          <MomentCalendar key={`${data.region.code}:${data.year}:${data.window?.date_from ?? ""}:${data.window?.date_to ?? ""}`} data={data} />

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
          <DataSources sources={data.data_sources} />
          <SourcesPanel sources={data.sources} limitations={data.limitations} />
        </>
      )}
    </div>
  );
}
