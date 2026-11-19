"use client";

import { LoaderCircle, RefreshCw } from "lucide-react";
import { useId, useState } from "react";

import { ChipToggleGroup, CountUp, Reveal, Sparkline, Stagger } from "@/components/creative";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { SectionTitle } from "@/features/workspaces/parts";
import { cn } from "@/lib/utils";

import { useRefreshSearchPulse, useSearchPulse, type PulseTerm } from "./api";

type Kind = "top" | "rising";

const day = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });
const when = (iso: string) => day.format(new Date(`${iso}T00:00:00Z`));
const gain = (n: number) => `+${new Intl.NumberFormat("en-IN").format(n)}%`;
const scoreAt = (t: PulseTerm, week: string) => t.history.find((h) => h.week === week)?.score ?? null;

/** A term's score in every kept week as small bars; a week with no score is an empty dotted cell, never a zero. */
function WeekStrip({ term, weeks, week }: { term: PulseTerm; weeks: string[]; week: string | null }) {
  return (
    <span aria-hidden className="flex h-5 items-end gap-px">
      {weeks.map((w) => {
        const s = scoreAt(term, w);
        return (
          <span
            key={w}
            className={cn("w-1 rounded-[1px]", s === null ? "h-[3px] border-t border-dotted border-ink-muted/60" : w === week ? "bg-pop" : "bg-ink-secondary/55")}
            style={s === null ? undefined : { height: `${Math.max(3, Math.round((s / 100) * 20))}px` }}
          />
        );
      })}
    </span>
  );
}

function Detail({ term, weeks, week, kind }: { term: PulseTerm; weeks: string[]; week: string | null; kind: Kind }) {
  const scored = term.history.filter((h): h is typeof h & { score: number } => h.score !== null);
  const shown = week ? scoreAt(term, week) : term.score;
  return (
    <div className="space-y-3 rounded-card border border-border bg-surface-raised px-4 py-4" aria-live="polite">
      <div className="space-y-1">
        <p className="type-meta">{kind === "rising" ? `Rising, rank ${term.rank ?? "n/a"}` : `Rank ${term.rank ?? "n/a"}`}</p>
        <p className="text-[17px] leading-snug font-semibold break-words text-ink">{term.term}</p>
      </div>
      <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
        <p className="type-ledger text-ink">
          <span className="text-[28px] font-semibold">{shown === null ? "n/a" : <CountUp value={shown} />}</span>
          <span className="type-meta ml-1.5">score{week ? `, week of ${when(week)}` : ""}</span>
        </p>
        {kind === "rising" && term.percent_gain !== null && <p className="type-ledger text-[15px] font-semibold text-pop-ink">{gain(term.percent_gain)}</p>}
      </div>
      {scored.length >= 2 ? (
        <Sparkline
          values={scored.map((h) => h.score)}
          labels={scored.map((h) => `Week of ${when(h.week)}`)}
          format={(v) => `score ${v}`}
          ariaLabel={`Weekly score of ${term.term}`}
          variant="area"
          height={64}
        />
      ) : (
        <p className="type-meta">{scored.length === 1 ? `Scored in the week of ${when(scored[0].week)} only.` : "No weekly score."}</p>
      )}
      <p className="type-meta">
        Scored in {term.weeks_seen} of {weeks.length} weeks.
      </p>
    </div>
  );
}

function TopRow({ term, weeks, week, pinned, onPin, onHover }: {
  term: PulseTerm; weeks: string[]; week: string | null; pinned: boolean; onPin(): void; onHover(on: boolean): void;
}) {
  const score = week ? scoreAt(term, week) : term.score;
  return (
    <li>
      <button
        type="button"
        aria-pressed={pinned}
        aria-label={`Rank ${term.rank}, ${term.term}, score ${score ?? "none"}`}
        onClick={onPin}
        onPointerEnter={() => onHover(true)}
        onPointerLeave={() => onHover(false)}
        onFocus={() => onHover(true)}
        onBlur={() => onHover(false)}
        className={cn(
          "grid w-full grid-cols-[1.75rem_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-surface-muted/70 focus-visible:bg-surface-muted/70 motion-reduce:transition-none",
          pinned && "bg-pop-soft/60",
        )}
      >
        <span className="type-ledger text-[12.5px] text-ink-muted">{term.rank}</span>
        <span className="min-w-0 space-y-1">
          <span className="block truncate text-[14px] text-ink" title={term.term}>{term.term}</span>
          <span className="block h-1.5 overflow-hidden rounded-full bg-surface-muted">
            <span className="block h-full rounded-full bg-pop transition-[width] duration-500 motion-reduce:transition-none" style={{ width: `${score ?? 0}%` }} />
          </span>
        </span>
        <span className="flex items-center gap-2.5">
          <WeekStrip term={term} weeks={weeks} week={week} />
          <span className="type-ledger w-8 text-right text-[13px] text-ink">{score === null ? "n/a" : <CountUp value={score} duration={600} />}</span>
        </span>
      </button>
    </li>
  );
}

function Bubbles({ items, maxGain, week, pinned, onPin, onHover }: {
  items: PulseTerm[]; maxGain: number; week: string | null; pinned: string | null; onPin(t: string): void; onHover(t: string | null): void;
}) {
  return (
    <Stagger as="ul" className="flex flex-wrap items-center gap-2.5">
      {items.map((t) => {
        const g = t.percent_gain ?? 0;
        const size = 76 + Math.round(60 * (Math.log(g + 1) / Math.log(maxGain + 1)));
        const dim = week !== null && scoreAt(t, week) === null;
        return (
          <li key={t.term}>
            <button
              type="button"
              aria-pressed={pinned === t.term}
              aria-label={`Rising rank ${t.rank}, ${t.term}, ${gain(g)}`}
              onClick={() => onPin(t.term)}
              onPointerEnter={() => onHover(t.term)}
              onPointerLeave={() => onHover(null)}
              onFocus={() => onHover(t.term)}
              onBlur={() => onHover(null)}
              style={{ width: size, height: size }}
              className={cn(
                "flex flex-col items-center justify-center gap-0.5 rounded-full border px-2 text-center transition-transform hover:-translate-y-0.5 motion-reduce:transition-none",
                pinned === t.term ? "border-pop bg-pop-soft text-pop-ink" : "border-border bg-surface-raised text-ink",
                dim && "opacity-40",
              )}
            >
              <span className="line-clamp-2 text-[11.5px] leading-tight break-words" title={t.term}>{t.term}</span>
              <span className="type-ledger text-[12px] font-semibold">{gain(g)}</span>
            </button>
          </li>
        );
      })}
    </Stagger>
  );
}

export function SearchPulse({ campaignId, region, label, limit = 10 }: { campaignId: string; region: string; label?: string; limit?: number }) {
  const pulse = useSearchPulse(campaignId, region);
  const refresh = useRefreshSearchPulse(campaignId, region);
  const [kind, setKind] = useState<Kind>("top");
  const [week, setWeek] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  const titleId = useId();
  const data = pulse.data;

  if (pulse.isPending) return <LoadingState label="Reading the search pulse…" />;
  if (pulse.isError) return <ErrorState error={pulse.error} onRetry={() => void pulse.refetch()} />;
  if (!data || !data.supported || (data.top.length === 0 && data.rising.length === 0)) return null;

  const list = kind === "top" ? data.top : data.rising;
  const visible = week ? list.filter((t) => scoreAt(t, week) !== null) : list;
  const shown = all ? visible : visible.slice(0, limit);
  const focus = list.find((t) => t.term === (hover ?? pinned)) ?? visible[0] ?? list[0];
  const maxGain = Math.max(1, ...data.rising.map((t) => t.percent_gain ?? 0));
  const pin = (term: string) => setPinned((cur) => (cur === term ? null : term));

  return (
    <Reveal as="section" aria-labelledby={titleId} className="space-y-3">
      <SectionTitle id={titleId} meta={data.week ? `Week of ${when(data.week)}` : undefined}>
        {label ? `Search pulse, ${label}` : "Search pulse"}
      </SectionTitle>
      <div className="flex flex-wrap items-center gap-3">
        <ChipToggleGroup
          ariaLabel="Search pulse list"
          size="sm"
          value={kind}
          onChange={(v) => {
            setKind(v as Kind);
            setAll(false);
          }}
          options={[
            { value: "top", label: "Top searches", count: data.top.length },
            { value: "rising", label: "Rising", count: data.rising.length },
          ]}
        />
        {data.can_refresh && (
          <Button type="button" variant="ghost" size="sm" aria-label="Refresh search pulse" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
            {refresh.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <RefreshCw aria-hidden />}
          </Button>
        )}
      </div>
      <div role="group" aria-label="Show one week" className="flex flex-wrap items-center gap-1">
        <button
          type="button"
          aria-pressed={week === null}
          onClick={() => setWeek(null)}
          className={cn("type-meta rounded-full px-2.5 py-1 transition-colors motion-reduce:transition-none", week === null ? "bg-ink text-surface" : "hover:bg-surface-muted")}
        >
          Latest
        </button>
        {data.weeks.map((w) => (
          <button
            key={w}
            type="button"
            aria-pressed={week === w}
            onClick={() => setWeek((cur) => (cur === w ? null : w))}
            className={cn("type-ledger rounded-full px-2 py-1 text-[11.5px] transition-colors motion-reduce:transition-none", week === w ? "bg-ink text-surface" : "text-ink-secondary hover:bg-surface-muted")}
          >
            {when(w)}
          </button>
        ))}
      </div>
      {week && (
        <p className="type-meta" aria-live="polite">
          {visible.length} of {list.length} terms have a score in the week of {when(week)}.
        </p>
      )}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="min-w-0">
          {kind === "top" ? (
            <Stagger as="ul" className="space-y-0.5">
              {shown.map((t) => (
                <TopRow key={t.term} term={t} weeks={data.weeks} week={week} pinned={pinned === t.term} onPin={() => pin(t.term)} onHover={(on) => setHover(on ? t.term : null)} />
              ))}
            </Stagger>
          ) : (
            <Bubbles items={shown} maxGain={maxGain} week={week} pinned={pinned} onPin={pin} onHover={setHover} />
          )}
          {visible.length > limit && (
            <Button type="button" variant="outline" size="sm" className="mt-3" aria-expanded={all} onClick={() => setAll((v) => !v)}>
              {all ? "Show fewer" : `Show all ${visible.length}`}
            </Button>
          )}
        </div>
        {focus && <Detail term={focus} weeks={data.weeks} week={week} kind={kind} />}
      </div>
    </Reveal>
  );
}
