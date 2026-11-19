/**
 * Moment calendar logic: dates as ISO strings (`2027-04-14`, a calendar day with no time zone), month grids, keyboard moves
 * and the words a screen reader hears. Pure, with no React and no runtime import, so it runs under `node --test` as it is.
 * Nothing here invents a number: every count is taken from the entries the API returned.
 */
import type { LensCalendarEntry, LensCalendar } from "./api";

export type Kind = LensCalendarEntry["kind"];
export type Window = NonNullable<LensCalendar["window"]>;

/** Strongest first: a day holding several kinds is drawn as the first of these it holds. */
export const KINDS: readonly Kind[] = ["public_holiday", "festival", "observance"];

const WORDS: Record<Kind, readonly [string, string]> = {
  public_holiday: ["public holiday", "public holidays"],
  festival: ["festival", "festivals"],
  observance: ["observance", "observances"],
};
export const kindWord = (kind: Kind, n = 1) => WORDS[kind][n === 1 ? 0 : 1];

const pad = (n: number) => String(n).padStart(2, "0");
export const isoDate = (y: number, m: number, d: number) => `${y}-${pad(m)}-${pad(d)}`;
const split = (iso: string) => iso.split("-").map(Number) as [number, number, number];
const utc = (iso: string) => {
  const [y, m, d] = split(iso);
  return new Date(Date.UTC(y, m - 1, d));
};

export const monthOf = (iso: string) => split(iso)[1];
export const dayOf = (iso: string) => split(iso)[2];
export const daysIn = (y: number, m: number) => new Date(Date.UTC(y, m, 0)).getUTCDate();
/** 0 is Monday, 6 is Sunday. */
export const weekday = (iso: string) => (utc(iso).getUTCDay() + 6) % 7;

export function addDays(iso: string, n: number) {
  const t = utc(iso);
  t.setUTCDate(t.getUTCDate() + n);
  return t.toISOString().slice(0, 10);
}

/** The local calendar day of `now` (today, when called with the current time). */
export const isoOf = (now: Date) => isoDate(now.getFullYear(), now.getMonth() + 1, now.getDate());

/** A month as weeks of seven days, Monday first; null stands for a day of the month before or after. */
export function monthWeeks(year: number, month: number): (string | null)[][] {
  const cells: (string | null)[] = Array.from({ length: weekday(isoDate(year, month, 1)) }, () => null);
  for (let d = 1; d <= daysIn(year, month); d++) cells.push(isoDate(year, month, d));
  while (cells.length % 7) cells.push(null);
  return Array.from({ length: cells.length / 7 }, (_, w) => cells.slice(w * 7, w * 7 + 7));
}

/**
 * Where a key moves the calendar focus from `iso`: arrows by a day or a week, Home and End to the start and end of the
 * week (kept inside the month, as the row is drawn), PageUp and PageDown to the same day of the month before or after.
 * Never leaves `year` (the move stops at its edge). Null for a key that is not a move.
 */
export function moveDate(key: string, iso: string, year: number): string | null {
  const [y, m, d] = split(iso);
  let next: string;
  switch (key) {
    case "ArrowLeft":
      next = addDays(iso, -1);
      break;
    case "ArrowRight":
      next = addDays(iso, 1);
      break;
    case "ArrowUp":
      next = addDays(iso, -7);
      break;
    case "ArrowDown":
      next = addDays(iso, 7);
      break;
    case "Home": {
      const start = addDays(iso, -weekday(iso));
      next = monthOf(start) === m && start.startsWith(`${y}-`) ? start : isoDate(y, m, 1);
      break;
    }
    case "End": {
      const end = addDays(iso, 6 - weekday(iso));
      next = monthOf(end) === m && end.startsWith(`${y}-`) ? end : isoDate(y, m, daysIn(y, m));
      break;
    }
    case "PageUp":
    case "PageDown": {
      const to = m + (key === "PageUp" ? -1 : 1);
      next = to < 1 || to > 12 ? iso : isoDate(y, to, Math.min(d, daysIn(y, to)));
      break;
    }
    default:
      return null;
  }
  return next.startsWith(`${year}-`) ? next : iso;
}

/** The entries of each day, in the API's order (date, then kind, then name). */
export function byDate(entries: LensCalendarEntry[]) {
  const days = new Map<string, LensCalendarEntry[]>();
  for (const e of entries) {
    const list = days.get(e.date);
    if (list) list.push(e);
    else days.set(e.date, [e]);
  }
  return days;
}

export const strongestKind = (list: LensCalendarEntry[]): Kind => KINDS.find((k) => list.some((e) => e.kind === k)) ?? "observance";

/** "38 dated moments: 17 public holidays, 6 festivals, 15 observances" (a kind with none is left out). */
export function countLine(entries: LensCalendarEntry[]) {
  if (entries.length === 0) return "No dated moments";
  const kinds = KINDS.map((k) => [k, entries.filter((e) => e.kind === k).length] as const)
    .filter(([, n]) => n > 0)
    .map(([k, n]) => `${n} ${kindWord(k, n)}`);
  return `${entries.length} dated ${entries.length === 1 ? "moment" : "moments"}: ${kinds.join(", ")}`;
}

export const moments = (n: number) => `${n} ${n === 1 ? "moment" : "moments"}`;

export const inWindow = (iso: string, w: Window | null | undefined) => Boolean(w) && iso >= w!.date_from && iso <= w!.date_to;

const LONG = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric" });
const WEEKDAY = new Intl.DateTimeFormat("en-GB", { weekday: "long" });
const local = (iso: string) => {
  const [y, m, d] = split(iso);
  return new Date(y, m - 1, d);
};
/** `14 April 2027` */
export const longDate = (iso: string) => LONG.format(local(iso));
/** `Wednesday` */
export const weekdayName = (iso: string) => WEEKDAY.format(local(iso));

/**
 * What a day button says: "14 April 2027: Vishu, festival; Ambedkar Jayanti, observance. Inside the campaign dates."
 * `inside` names the window the day falls in (null when it is outside or there is none).
 */
export function dayAriaLabel(iso: string, list: LensCalendarEntry[] | undefined, inside: string | null, today: boolean) {
  const what = list?.length
    ? list.map((e) => `${e.name}, ${kindWord(e.kind)}${e.tentative ? ", tentative date" : ""}`).join("; ")
    : "no dated moment";
  return [`${longDate(iso)}: ${what}.`, inside ? `Inside the ${inside}.` : "", today ? "Today." : ""].filter(Boolean).join(" ");
}

/** The run of window days in one week row, as column indexes, and whether it holds the window's first or last day. */
export function bandRun(week: (string | null)[], w: Window) {
  let start = -1;
  let end = -1;
  week.forEach((d, i) => {
    if (d && inWindow(d, w)) {
      if (start < 0) start = i;
      end = i;
    }
  });
  return start < 0 ? null : { start, end, opens: week[start] === w.date_from, closes: week[end] === w.date_to };
}

/** The marked day closest to `iso` (the earlier one on a tie); null when there is none. */
export function nearest(iso: string, sorted: string[]) {
  const t = utc(iso).getTime();
  let best: string | null = null;
  let gap = Infinity;
  for (const d of sorted) {
    const g = Math.abs(utc(d).getTime() - t);
    if (g < gap) {
      gap = g;
      best = d;
    }
  }
  return best;
}

/** Where the calendar opens: the first moment in the window, else the next one from today, else the year's first. */
export function startDay(marked: string[], year: number, w: Window | null, today: string) {
  const first = marked.find((d) => inWindow(d, w));
  if (first) return first;
  if (today.startsWith(`${year}-`)) return marked.find((d) => d >= today) ?? marked.at(-1) ?? today;
  return marked[0] ?? isoDate(year, 1, 1);
}

const SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** Typical months as people say them: `Oct–Nov` for a run, `Jan, Apr` otherwise. */
export function monthSpan(months: number[]) {
  const ms = [...new Set(months)].filter((m) => m >= 1 && m <= 12).sort((a, b) => a - b);
  const run = ms.length > 1 && ms.every((m, i) => i === 0 || m === ms[i - 1] + 1);
  return run ? `${SHORT[ms[0] - 1]}–${SHORT[ms[ms.length - 1] - 1]}` : ms.map((m) => SHORT[m - 1]).join(", ");
}
