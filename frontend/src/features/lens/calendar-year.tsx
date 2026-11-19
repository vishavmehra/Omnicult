"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { CalendarCheck, ChevronLeft, ChevronRight, X } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type FocusEvent, type KeyboardEvent, type MouseEvent } from "react";
import { flushSync } from "react-dom";

import { useReducedMotion } from "@/components/creative";
import { Button } from "@/components/ui/button";
import { SectionTitle } from "@/features/workspaces/parts";
import { cn } from "@/lib/utils";

import type { LensCalendar } from "./api";
import {
  KINDS,
  bandRun,
  byDate,
  countLine,
  dayAriaLabel,
  dayOf,
  inWindow,
  isoDate,
  isoOf,
  longDate,
  monthOf,
  monthSpan,
  monthWeeks,
  moments,
  moveDate,
  nearest,
  startDay,
  strongestKind,
  weekdayName,
} from "./calendar-logic";
import { KIND_COLOR, KIND_LABEL, KindMark, MomentBody } from "./calendar-moment";
import { MONTHS, dayLabel } from "./format";

gsap.registerPlugin(useGSAP);

/**
 * The moment calendar of one state for one year: twelve clay month tiles (one at a time below 640px), every day with a
 * dated moment marked by the colour and shape of its kind, the campaign window drawn as one continuous band across the days
 * it covers. Hover or keyboard focus on a marked day opens its card (anchored to the day on wide screens, a panel under the
 * grid on phones); click, Enter or Space pins it and Escape closes it. Each month is an ARIA grid with a roving tab stop:
 * arrows move by day, Home and End to the ends of the week, PageUp and PageDown by month. An agenda under the grid gives the
 * same moments as a list.
 */

const WEEK = [
  ["M", "Monday"],
  ["T", "Tuesday"],
  ["W", "Wednesday"],
  ["T", "Thursday"],
  ["F", "Friday"],
  ["S", "Saturday"],
  ["S", "Sunday"],
] as const;
const MONTH_NUMBERS = Array.from({ length: 12 }, (_, i) => i + 1);

/** The window band in both themes: mint clay on the light ground, a low glow on graphite, with a stronger edge. */
const BAND =
  "[--band:color-mix(in_oklab,var(--role-lens)_70%,transparent)] [--band-edge:color-mix(in_oklab,var(--role-lens-strong)_55%,transparent)] dark:[--band:color-mix(in_oklab,var(--role-lens)_22%,transparent)]";

type Peek = { iso: string; via: "hover" | "focus" };
type Scope = "month" | "window";

function MonthStepper({ month, year, count, onMonth, big, className }: { month: number; year: number; count: number; onMonth(m: number): void; big?: boolean; className?: string }) {
  const step = cn(big && "size-11");
  return (
    <div className={cn("flex items-center gap-1.5", className)}>
      <Button type="button" variant="outline" size="icon" className={step} aria-label="Previous month" disabled={month === 1} focusableWhenDisabled onClick={() => onMonth(month - 1)}>
        <ChevronLeft aria-hidden />
      </Button>
      <p aria-live="polite" className={cn("min-w-0 text-center", big ? "flex-1" : "w-36")}>
        <span className={cn("type-title block text-ink", big ? "text-[19px]" : "text-[15px]")}>
          {MONTHS[month - 1]} {year}
        </span>
        <span className="type-meta block">{count > 0 ? moments(count) : "No dated moment"}</span>
      </p>
      <Button type="button" variant="outline" size="icon" className={step} aria-label="Next month" disabled={month === 12} focusableWhenDisabled onClick={() => onMonth(month + 1)}>
        <ChevronRight aria-hidden />
      </Button>
    </div>
  );
}

export function MomentCalendar({ data }: { data: LensCalendar }) {
  const year = data.year;
  const w = data.window;
  const windowName = data.window_basis === "campaign" ? "Campaign dates" : "Campaign window";
  const insideName = windowName.toLowerCase();
  const days = useMemo(() => byDate(data.entries), [data.entries]);
  const marked = useMemo(() => [...days.keys()], [days]);
  const undated = data.typical.filter((t) => !t.dated);

  const [today] = useState(() => isoOf(new Date()));
  const [cursor, setCursor] = useState(() => startDay(marked, year, w, today));
  const [pin, setPin] = useState<string | null>(null);
  const [peek, setPeek] = useState<Peek | null>(null);
  const [inside, setInside] = useState(false);
  const [scope, setScope] = useState<Scope>(() => (w && data.entries.some((e) => e.in_window) ? "window" : "month"));
  const reduce = useReducedMotion();
  const uid = useId();
  const cardId = `${uid}-card`;

  const rootRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const closeTimer = useRef<number | undefined>(undefined);
  const muted = useRef<string | null>(null);

  const month = monthOf(cursor);
  const shown = peek?.iso ?? pin;
  const shownList = shown ? days.get(shown) : undefined;
  // The one tab stop: the focused day while focus is in the grid, otherwise the nearest day with a moment.
  const stop = inside || days.has(cursor) ? cursor : (nearest(cursor, marked.filter((d) => monthOf(d) === month)) ?? nearest(cursor, marked));
  const monthEntries = data.entries.filter((e) => monthOf(e.date) === month);
  const windowEntries = data.entries.filter((e) => e.in_window);
  const agenda = scope === "window" && w ? windowEntries : monthEntries;
  const windowInYear = Boolean(w) && w!.date_to >= `${year}-01-01` && w!.date_from <= `${year}-12-31`;

  // --- card: what opens it, what closes it -------------------------------------------------------------------------
  const focusedDay = (): Peek | null => {
    const el = document.activeElement;
    const iso = el instanceof HTMLElement ? el.dataset.iso : undefined;
    return iso && days.has(iso) && el!.matches(":focus-visible") ? { iso, via: "focus" } : null;
  };
  const hoverOn = (iso: string) => {
    window.clearTimeout(closeTimer.current);
    if (cardRef.current?.contains(document.activeElement)) return; // the keyboard is reading the card: leave it in place
    setPeek({ iso, via: "hover" });
  };
  const hoverOff = () => {
    window.clearTimeout(closeTimer.current);
    // A short grace lets the pointer cross from the day into its card.
    closeTimer.current = window.setTimeout(() => {
      const back = focusedDay();
      setPeek((p) => (p?.via === "hover" ? back : p));
    }, 140);
  };
  const close = () => {
    window.clearTimeout(closeTimer.current);
    setPeek(null);
    setPin(null);
  };
  const closeAndReturn = () => {
    const at = shown;
    close();
    if (at) {
      muted.current = at; // the day takes the focus back without reopening its card
      buttons.current.get(at)?.focus();
    }
  };
  const go = (iso: string) => {
    flushSync(() => setCursor(iso)); // on phones the target month must be shown before it can take the focus
    buttons.current.get(iso)?.focus();
  };
  const goMonth = (m: number) => {
    close();
    setCursor(marked.find((d) => monthOf(d) === m) ?? isoDate(year, m, 1));
  };

  const onDayFocus = (e: FocusEvent<HTMLButtonElement>, iso: string) => {
    setCursor(iso);
    if (muted.current === iso) {
      muted.current = null;
      return;
    }
    muted.current = null;
    if (days.has(iso) && e.currentTarget.matches(":focus-visible")) {
      window.clearTimeout(closeTimer.current);
      setPeek({ iso, via: "focus" });
    }
  };
  const onDayBlur = (e: FocusEvent<HTMLButtonElement>, iso: string) => {
    if (e.relatedTarget instanceof Node && cardRef.current?.contains(e.relatedTarget)) return;
    setPeek((p) => (p?.via === "focus" && p.iso === iso ? null : p));
  };
  const onDayClick = (e: MouseEvent<HTMLButtonElement>, iso: string) => {
    setCursor(iso);
    if (!days.has(iso)) {
      close();
      return;
    }
    if (e.detail === 0) {
      // Enter or Space: pin the card and move the focus into it, so its text and links come next.
      flushSync(() => {
        setPin(iso);
        setPeek(null);
      });
      cardRef.current?.focus();
      return;
    }
    setPin((p) => (p === iso ? null : iso));
    if (window.matchMedia("(max-width: 639.98px)").matches) {
      requestAnimationFrame(() => cardRef.current?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" }));
    }
  };
  const onDayKey = (e: KeyboardEvent<HTMLButtonElement>, iso: string) => {
    if (e.key === "Escape") {
      if (shown) {
        e.preventDefault();
        close();
      }
      return;
    }
    const next = moveDate(e.key, iso, year);
    if (next === null) return;
    e.preventDefault();
    go(next);
  };
  const onCardKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Escape") return;
    e.preventDefault();
    closeAndReturn();
  };
  const onCardBlur = (e: FocusEvent<HTMLDivElement>) => {
    const to = e.relatedTarget;
    if (!(to instanceof Node) || e.currentTarget.contains(to) || gridRef.current?.contains(to)) return;
    close();
  };

  // Anchor the card under its day (over it when the viewport has more room above), inside the calendar's width. It sits
  // 2px off the day, the gap between week rows, so a pointer moving into it never crosses the next row's day. On phones
  // the card is a static panel under the grid and the offsets do nothing.
  useLayoutEffect(() => {
    const card = cardRef.current;
    const wrap = wrapRef.current;
    const day = shown ? buttons.current.get(shown) : undefined;
    if (!card || !wrap || !day) return;
    const place = () => {
      if (getComputedStyle(card).position !== "absolute") return;
      const d = day.getBoundingClientRect();
      const b = wrap.getBoundingClientRect();
      const room = window.innerHeight - d.bottom;
      const below = room >= card.offsetHeight + 12 || room >= d.top;
      const right = d.left - b.left + card.offsetWidth > b.width;
      card.style.top = below ? `${d.bottom - b.top + 2}px` : "";
      card.style.bottom = below ? "" : `${b.bottom - d.top + 2}px`;
      card.style.left = right ? "" : `${Math.max(0, d.left - b.left)}px`;
      card.style.right = right ? `${Math.max(0, b.right - d.right)}px` : "";
      card.style.transformOrigin = `${right ? "right" : "left"} ${below ? "top" : "bottom"}`;
    };
    place();
    const ro = new ResizeObserver(place);
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [shown]);

  // An open card closes on a press anywhere outside the card and the calendar.
  const cardOpen = shown !== null;
  useEffect(() => {
    if (!cardOpen) return;
    const down = (e: PointerEvent) => {
      const t = e.target;
      if (t instanceof Node && (cardRef.current?.contains(t) || gridRef.current?.contains(t))) return;
      window.clearTimeout(closeTimer.current);
      setPeek(null);
      setPin(null);
    };
    document.addEventListener("pointerdown", down);
    return () => document.removeEventListener("pointerdown", down);
  }, [cardOpen]);

  useEffect(() => {
    const timer = closeTimer;
    return () => window.clearTimeout(timer.current);
  }, []);

  // Motion (none under reduced motion): the month tiles cascade in, the marked days land, the window band sweeps across.
  useGSAP(
    () => {
      const root = rootRef.current;
      if (!root) return;
      // Only what is on screen (one month on phones), and nothing when a set is empty (a year with no campaign dates).
      const play = (selector: string, vars: gsap.TweenVars) => {
        const targets = Array.from(root.querySelectorAll<HTMLElement>(selector)).filter((el) => el.offsetParent !== null);
        if (targets.length > 0) gsap.from(targets, vars);
      };
      gsap.matchMedia().add("(prefers-reduced-motion: no-preference)", () => {
        play("[data-cal-month]", { opacity: 0, y: 26, scale: 0.97, duration: 0.7, ease: "expo.out", stagger: 0.05, clearProps: "opacity,transform" });
        play("[data-cal-marked]", { opacity: 0, scale: 0.3, duration: 0.5, ease: "back.out(2.4)", stagger: 0.012, delay: 0.3, clearProps: "opacity,transform" });
        play("[data-cal-band]", { scaleX: 0, transformOrigin: "0% 50%", duration: 0.65, ease: "power3.inOut", stagger: 0.06, delay: 0.5, clearProps: "transform" });
      });
    },
    { scope: rootRef },
  );

  // The card pops from its day each time it opens on one.
  useGSAP(
    () => {
      const card = cardRef.current;
      if (!shown || !card) return;
      const above = card.style.transformOrigin.endsWith("bottom"); // set by the placement above, which runs first
      gsap.matchMedia().add("(prefers-reduced-motion: no-preference)", () => {
        gsap.fromTo(card, { opacity: 0, scale: 0.93, y: above ? 6 : -6 }, { opacity: 1, scale: 1, y: 0, duration: 0.28, ease: "back.out(1.8)", clearProps: "opacity,transform" });
      });
    },
    { dependencies: [shown], revertOnUpdate: true },
  );

  // --- drawing -----------------------------------------------------------------------------------------------------
  const dayButton = (iso: string) => {
    const list = days.get(iso);
    const kind = list ? strongestKind(list) : null;
    const pinned = pin === iso;
    const open = shown === iso;
    const isToday = iso === today;
    const within = inWindow(iso, w);
    return (
      <button
        ref={(el) => {
          if (el) buttons.current.set(iso, el);
          else buttons.current.delete(iso);
        }}
        type="button"
        data-iso={iso}
        data-cal-marked={list ? "" : undefined}
        tabIndex={iso === stop ? 0 : -1}
        aria-label={dayAriaLabel(iso, list, within ? insideName : null, isToday)}
        aria-disabled={list ? undefined : true}
        aria-expanded={list ? open : undefined}
        aria-controls={open ? cardId : undefined}
        onFocus={(e) => onDayFocus(e, iso)}
        onBlur={(e) => onDayBlur(e, iso)}
        onClick={(e) => onDayClick(e, iso)}
        onKeyDown={(e) => onDayKey(e, iso)}
        onPointerEnter={list ? (e) => e.pointerType !== "touch" && hoverOn(iso) : undefined}
        onPointerLeave={list ? (e) => e.pointerType !== "touch" && hoverOff() : undefined}
        style={kind ? ({ "--k": KIND_COLOR[kind] } as CSSProperties) : undefined}
        className={cn(
          "group relative flex h-11 w-full flex-col items-center justify-center gap-[3px] rounded-[10px] text-[13.5px] leading-none tabular-nums sm:h-8 sm:text-[12.5px]",
          "transition-[translate] duration-150 ease-out focus-visible:z-20 motion-reduce:transition-none",
          list ? "font-semibold hover:z-10 hover:-translate-y-px" : "cursor-default",
          list ? (pinned ? "z-10 text-pop-ink" : "text-ink") : within ? "text-ink-secondary" : "text-ink-muted",
          open && !pinned && "z-10 -translate-y-px",
          isToday && "ring-[1.5px] ring-ink ring-inset",
        )}
      >
        {list && (
          <span
            aria-hidden
            className={cn(
              "absolute inset-[3px] rounded-[7px] transition-shadow duration-150 motion-reduce:transition-none",
              pinned
                ? "bg-pop shadow-float"
                : "bg-[color-mix(in_oklab,var(--k)_20%,var(--surface-raised))] shadow-clay group-hover:shadow-float dark:bg-[color-mix(in_oklab,var(--k)_32%,var(--surface-raised))]",
              open && !pinned && "shadow-float",
            )}
          />
        )}
        <span className="relative">{dayOf(iso)}</span>
        {list && (
          <span aria-hidden className="relative flex h-1.5 items-center gap-0.5">
            {list.slice(0, 3).map((e) => (
              <KindMark key={e.key} kind={e.kind} color={pinned ? "currentColor" : undefined} className="size-[7px] sm:size-1.5" />
            ))}
          </span>
        )}
      </button>
    );
  };

  const monthTile = (m: number) => {
    const weeks = monthWeeks(year, m);
    const inMonth = data.entries.filter((e) => monthOf(e.date) === m);
    const holds = weeks.some((wk) => wk.some((d) => d !== null && inWindow(d, w)));
    const usual = undated.filter((t) => t.months.includes(m));
    const head = `${uid}-m${m}`;
    return (
      <section
        key={m}
        data-cal-month
        aria-labelledby={head}
        className={cn(
          "flex min-w-0 flex-col gap-2 rounded-card border border-border bg-surface p-2.5",
          holds && "shadow-float ring-[1.5px] ring-(--band-edge)",
          m !== month && "max-sm:hidden",
        )}
      >
        <div className="flex items-baseline justify-between gap-2 px-0.5">
          <h3 id={head} className="type-title text-[17px] text-ink">
            {MONTHS[m - 1]}
            <span className="sr-only"> {year}</span>
          </h3>
          <p className="flex items-center gap-2.5 text-[11px]">
            {holds && (
              <span className="inline-flex items-center gap-1 font-medium text-ink">
                <CalendarCheck aria-hidden className="size-3 text-role-lens-strong" />
                {windowName}
              </span>
            )}
            {inMonth.length > 0 && (
              <span className="inline-flex items-center gap-1.5 font-semibold text-ink-secondary tabular-nums">
                <span className="sr-only">{moments(inMonth.length)}</span>
                {KINDS.map((k) => {
                  const n = inMonth.filter((e) => e.kind === k).length;
                  return n > 0 ? (
                    <span key={k} aria-hidden className="inline-flex items-center gap-0.5">
                      <KindMark kind={k} className="size-2" />
                      {n}
                    </span>
                  ) : null;
                })}
              </span>
            )}
          </p>
        </div>
        <div role="grid" aria-labelledby={head} className="space-y-0.5">
          <div role="row" className="grid grid-cols-7 gap-0.5">
            {WEEK.map(([short, full], i) => (
              <div key={full} role="columnheader" className={cn("py-0.5 text-center text-[10.5px] font-semibold", i > 4 ? "text-ink-secondary" : "text-ink-muted")}>
                <span aria-hidden>{short}</span>
                <span className="sr-only">{full}</span>
              </div>
            ))}
          </div>
          {weeks.map((week, r) => {
            const run = w ? bandRun(week, w) : null;
            return (
              <div key={r} role="row" className="grid grid-cols-7 gap-0.5">
                {run && (
                  <span
                    aria-hidden
                    data-cal-band
                    className={cn("pointer-events-none my-px border-y border-(--band-edge) bg-(--band)", run.opens && "rounded-l-[10px] border-l", run.closes && "rounded-r-[10px] border-r")}
                    style={{ gridColumn: `${run.start + 1} / ${run.end + 2}`, gridRow: 1 }}
                  />
                )}
                {week.map((iso, c) => (
                  <div key={iso ?? `blank-${c}`} role="gridcell" className="relative" style={{ gridColumn: c + 1, gridRow: 1 }}>
                    {iso && dayButton(iso)}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
        {usual.length > 0 && (
          <ul aria-label={`Usually in ${MONTHS[m - 1]}, no date for ${year} yet`} className="flex flex-wrap gap-1">
            {usual.map((t) => (
              <li key={t.name} className="rounded-full border border-dashed border-ink-muted/70 px-1.5 py-px text-[11px] text-ink-secondary">
                {t.name}
                <span className="text-ink-muted">, usually {monthSpan(t.months)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    );
  };

  return (
    <div ref={rootRef} className={cn("space-y-7", BAND)}>
      <section aria-labelledby={`${uid}-title`} className="space-y-3">
        <SectionTitle id={`${uid}-title`} meta={countLine(data.entries)}>
          {data.region.name} in {year}
        </SectionTitle>
        {data.gaps.length > 0 && (
          <ul className="space-y-1 text-[13.5px] text-ink-body">
            {data.gaps.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        )}
        <ul aria-label="Key" className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[12.5px] text-ink-secondary">
          {KINDS.map((k) => (
            <li key={k} className="inline-flex items-center gap-1.5">
              <KindMark kind={k} />
              {KIND_LABEL[k]}
            </li>
          ))}
          {w && (
            <li className="inline-flex items-center gap-1.5">
              <span aria-hidden className="h-3 w-6 shrink-0 rounded-full border border-(--band-edge) bg-(--band)" />
              {windowName}, {dayLabel(w.date_from)} to {dayLabel(w.date_to)}
              {windowInYear ? `: ${moments(windowEntries.length)} inside` : `, outside ${year}`}
            </li>
          )}
          {today.startsWith(`${year}-`) && (
            <li className="inline-flex items-center gap-1.5">
              <span aria-hidden className="size-3.5 shrink-0 rounded-[4px] ring-[1.5px] ring-ink ring-inset" />
              Today
            </li>
          )}
          {undated.length > 0 && (
            <li className="inline-flex items-center gap-1.5">
              <span aria-hidden className="h-3 w-5 shrink-0 rounded-full border border-dashed border-ink-muted" />
              Usually in that month, no date yet
            </li>
          )}
        </ul>

        <MonthStepper big month={month} year={year} count={monthEntries.length} onMonth={goMonth} className="sm:hidden" />

        <div ref={wrapRef} className="relative @container">
          <div
            ref={gridRef}
            onFocus={() => setInside(true)}
            onBlur={(e) => {
              if (!(e.relatedTarget instanceof Node && e.currentTarget.contains(e.relatedTarget))) setInside(false);
            }}
            className="grid gap-3 sm:grid-cols-2 sm:@min-[50rem]:grid-cols-3 sm:@min-[70rem]:grid-cols-4"
          >
            {MONTH_NUMBERS.map(monthTile)}
          </div>

          {shown && shownList ? (
            <div
              ref={cardRef}
              id={cardId}
              role="dialog"
              aria-labelledby={`${cardId}-title`}
              tabIndex={-1}
              onKeyDown={onCardKey}
              onBlur={onCardBlur}
              onPointerEnter={() => window.clearTimeout(closeTimer.current)}
              onPointerLeave={(e) => e.pointerType !== "touch" && hoverOff()}
              className="static z-30 mt-3 rounded-card border border-border bg-surface-raised p-4 shadow-float sm:absolute sm:mt-0 sm:max-h-[min(32rem,80vh)] sm:w-[20rem] sm:overflow-y-auto"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="type-meta">{weekdayName(shown)}</p>
                  <h3 id={`${cardId}-title`} className="type-title text-[19px] text-ink">
                    {dayLabel(shown)}
                  </h3>
                </div>
                {pin === shown && (
                  <Button type="button" variant="ghost" size="icon" className="-mt-1 -mr-1 max-sm:size-11" aria-label="Close" onClick={closeAndReturn}>
                    <X aria-hidden />
                  </Button>
                )}
              </div>
              {inWindow(shown, w) && (
                <p className="mt-1.5 inline-flex items-center gap-1 rounded-full border border-(--band-edge) bg-(--band) px-2 py-0.5 text-[11.5px] font-medium text-ink">
                  <CalendarCheck aria-hidden className="size-3" />
                  Inside the {insideName}
                </p>
              )}
              <ul className="mt-3 divide-y divide-border">
                {shownList.map((e) => (
                  <li key={e.key} className="py-3 first:pt-0 last:pb-0">
                    <MomentBody entry={e} level={4} />
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="mt-3 rounded-card border border-dashed border-border-strong/50 bg-surface-muted/50 px-4 py-3 text-[13px] text-ink-secondary sm:hidden">
              Tap a marked day to see what it is, why it matters and where its date comes from.
            </p>
          )}
        </div>
      </section>

      <section aria-labelledby={`${uid}-agenda`} className="space-y-3">
        <SectionTitle id={`${uid}-agenda`} meta={scope === "window" && w ? `${dayLabel(w.date_from)} to ${dayLabel(w.date_to)}` : `${MONTHS[month - 1]} ${year}`}>
          Agenda
        </SectionTitle>
        <div className="flex flex-wrap items-center justify-between gap-3">
          {w && (
            <div role="group" aria-label="Show the agenda for" className="inline-flex gap-1 rounded-card bg-surface-muted/80 p-1 shadow-well">
              {(["month", "window"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  aria-pressed={scope === s}
                  onClick={() => setScope(s)}
                  className={cn(
                    "inline-flex h-11 items-center gap-1.5 rounded-full px-3 text-[13px] font-medium whitespace-nowrap transition-colors duration-150 motion-reduce:transition-none sm:h-8",
                    scope === s ? "clay text-ink" : "text-ink-secondary hover:text-ink",
                  )}
                >
                  {s === "month" ? MONTHS[month - 1] : windowName}
                  <span className={cn("tabular-nums", scope === s ? "text-pop" : "text-ink-muted")}>{s === "month" ? monthEntries.length : windowEntries.length}</span>
                </button>
              ))}
            </div>
          )}
          {(scope === "month" || !w) && <MonthStepper month={month} year={year} count={monthEntries.length} onMonth={goMonth} className="hidden sm:flex" />}
        </div>
        {agenda.length === 0 ? (
          <p className="rounded-card border border-dashed border-border-strong/50 bg-surface-muted/50 px-4 py-3 text-[13.5px] text-ink-secondary">
            {scope === "window" && w ? `No dated moment falls inside the ${insideName}.` : `No dated moment in ${MONTHS[month - 1]} ${year}.`}
          </p>
        ) : (
          <ol className="ledger-rules rounded-card border border-border bg-surface">
            {agenda.map((e) => (
              <li
                key={e.key}
                style={{ "--k": KIND_COLOR[e.kind] } as CSSProperties}
                className="grid gap-x-5 gap-y-2 px-4 py-3.5 shadow-[inset_3px_0_0_var(--k)] sm:grid-cols-[4.5rem_minmax(0,1fr)]"
              >
                <p className="flex items-baseline gap-2 sm:flex-col sm:gap-1">
                  <span className="sr-only">{longDate(e.date)}</span>
                  <span aria-hidden className="type-title text-[26px] leading-none text-ink">
                    {dayOf(e.date)}
                  </span>
                  <span aria-hidden className="type-meta">
                    {weekdayName(e.date).slice(0, 3)}, {MONTHS[monthOf(e.date) - 1].slice(0, 3)}
                  </span>
                </p>
                <MomentBody entry={e} level={3} />
              </li>
            ))}
          </ol>
        )}
      </section>

      {undated.length > 0 && (
        <section aria-labelledby={`${uid}-usual`} className="space-y-3">
          <SectionTitle id={`${uid}-usual`} meta={moments(undated.length)}>
            Usually in these months
          </SectionTitle>
          <p className="max-w-[68ch] text-[13px] text-ink-secondary">No exact date for {year} is on the calendar for these. They usually fall in the months shown.</p>
          <ul className="ledger-rules rounded-card border border-border bg-surface">
            {undated.map((t) => (
              <li key={t.name} className="grid gap-x-6 gap-y-1 px-4 py-3 sm:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
                <div className="min-w-0">
                  <p className="text-[14px] font-medium text-ink">{t.name}</p>
                  <p className="type-meta">
                    Usually {monthSpan(t.months)} · {t.calendar} calendar
                  </p>
                </div>
                <p className="text-[13px] text-ink-secondary">{t.note}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
