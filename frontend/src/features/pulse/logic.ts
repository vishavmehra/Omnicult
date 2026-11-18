/**
 * Live Pulse display logic: pure functions with no React and no network, so each rule can be tested on its own
 * (logic.test.mjs, run with `node --test`). Nothing here invents a metric: it formats, orders and classifies what the
 * API returned. Imports are type-only so the file also loads under Node's TypeScript stripping.
 */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];
export type Unit = S["MetricValue"]["unit"];
export type Platform = NonNullable<S["RegionSummary"]["platform"]>;
export type GroupBy = S["TimeSeries"]["group_by"];
export type SeriesPoint = S["SeriesPoint"];
export type PulseAlert = S["PulseAlert"];
export type AlertThresholds = S["AlertThresholds"];
export type RegionComparison = S["RegionComparison"];
export type ComparedMetric = S["ComparedMetric"];

export const SAMPLE_LABEL = "Sample data, not from a connected account";

/** Shown wherever reach (or frequency, which is derived from it) appears. The API sends the same statement; this is the floor. */
export const REACH_CAVEAT =
  "Reach is cumulative from the first day of data and is not deduplicated across platforms or versions: a person reached through two of them is counted twice.";

export const NOT_AVAILABLE = "n/a";
export const NOT_AVAILABLE_WHY = "Not available: the ratio has no denominator in this slice (for example CTR with no impressions). It is not zero.";

export const PLATFORM_LABEL: Record<string, string> = { google_ads: "Google Ads", youtube: "YouTube", meta: "Meta Ads", ga4: "GA4" };
export const REGION_FALLBACK: Record<string, string> = { "IN-MH": "Maharashtra", "IN-TN": "Tamil Nadu", "IN-KL": "Kerala", "IN-WB": "West Bengal" };

/** Regions in the order the campaign tells its story: the original's home first, then where it was adapted. Others follow by code. */
const REGION_ORDER = ["IN-MH", "IN-TN", "IN-KL", "IN-WB"];
export function sortRegions<T>(items: readonly T[], code: (item: T) => string): T[] {
  const rank = (c: string) => (REGION_ORDER.includes(c) ? REGION_ORDER.indexOf(c) : REGION_ORDER.length);
  return [...items].sort((a, b) => rank(code(a)) - rank(code(b)) || code(a).localeCompare(code(b)));
}

export const platformLabel = (p: string) => PLATFORM_LABEL[p] ?? p;
export const platformList = (ps: readonly string[]) => (ps.length ? ps.map(platformLabel).join(", ") : "No platform");
export const regionLabel = (code: string, names?: Record<string, string>) => names?.[code] ?? REGION_FALLBACK[code] ?? code;

// ---------------------------------------------------------------- dates

const DAY = 86_400_000;
const parseDay = (iso: string) => Date.parse(`${iso}T00:00:00Z`);
const dayFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const dayLongFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const weekdayFmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: "UTC" });

export const addDays = (iso: string, n: number) => new Date(parseDay(iso) + n * DAY).toISOString().slice(0, 10);
export const formatDay = (iso: string) => dayFmt.format(parseDay(iso));
export const formatDayLong = (iso: string) => dayLongFmt.format(parseDay(iso));
export const formatWeekday = (iso: string) => weekdayFmt.format(parseDay(iso));
/** "27 Oct to 16 Nov 2026". */
export const formatSpan = (from: string, to: string) => `${formatDay(from)} to ${formatDayLong(to)}`;

export type Range = { from: string | null; to: string | null };
type Span = { date_from: string | null; date_to: string | null; provisional_from: string | null };

/** Range presets for the filter row. "Settled days" ends the day before the provisional window begins. */
export function rangePresets(span: Span): { key: string; label: string; range: Range }[] {
  const presets = [{ key: "all", label: "Whole period", range: { from: null, to: null } as Range }];
  if (span.provisional_from && span.date_from && span.provisional_from > span.date_from) {
    presets.push({ key: "settled", label: "Settled days only", range: { from: null, to: addDays(span.provisional_from, -1) } });
  }
  if (span.date_to && span.date_from && addDays(span.date_to, -6) > span.date_from) {
    presets.push({ key: "last7", label: "Last 7 days", range: { from: addDays(span.date_to, -6), to: null } });
  }
  return presets;
}

export const sameRange = (a: Range, b: Range) => a.from === b.from && a.to === b.to;

// ---------------------------------------------------------------- number formatting

const grouped = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const compactFmt = new Intl.NumberFormat("en", { notation: "compact", maximumSignificantDigits: 3 });

function percent(ratio: number, signed = false) {
  const pct = ratio * 100;
  const text = Math.abs(pct) >= 10 ? pct.toFixed(1) : pct.toFixed(2);
  return `${signed && pct > 0 ? "+" : ""}${text}%`;
}

/**
 * One metric value in its unit. `null` is "not available", never 0. `compact` is for dense ledgers (5.06M, ₹377K);
 * the full form keeps Indian digit grouping.
 */
export function formatValue(value: number | null | undefined, unit: Unit, opts: { compact?: boolean; signed?: boolean } = {}): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NOT_AVAILABLE;
  switch (unit) {
    case "count":
      return opts.compact && Math.abs(value) >= 10_000 ? compactFmt.format(value) : grouped.format(value);
    case "inr": {
      const body =
        Math.abs(value) >= 1000
          ? opts.compact && Math.abs(value) >= 10_000
            ? compactFmt.format(value)
            : grouped.format(value)
          : value.toFixed(2);
      return `₹${body}`;
    }
    case "ratio":
      return percent(value, opts.signed);
    case "multiple":
      return `${value.toFixed(2)}×`;
  }
}

/** Change against the baseline as a percentage of the baseline, e.g. "+101%". */
export function formatPctChange(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) return NOT_AVAILABLE;
  const abs = Math.abs(pct * 100);
  const text = abs >= 10 ? abs.toFixed(0) : abs.toFixed(1);
  return `${pct > 0 ? "+" : pct < 0 ? "-" : ""}${text}%`;
}

/** Percentage-point change for ratio metrics, e.g. "+0.50 pts". */
export function formatPoints(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return NOT_AVAILABLE;
  const pts = delta * 100;
  return `${pts > 0 ? "+" : ""}${pts.toFixed(Math.abs(pts) >= 10 ? 1 : 2)} pts`;
}

// ---------------------------------------------------------------- metric direction

/** Whether a higher value is better for the campaign. null: neutral (volume, not quality), so no better/worse is stated. */
const HIGHER_IS_BETTER: Record<string, boolean | null> = {
  ctr: true,
  view_rate: true,
  completion_25: true,
  completion_50: true,
  completion_75: true,
  completion_100: true,
  roas: true,
  conversions: true,
  conversion_value: true,
  clicks: true,
  video_views: true,
  ctr_change_vs_first_week: true,
  view_rate_change_vs_first_week: true,
  cpm: false,
  cpc: false,
  cpa: false,
};
export const higherIsBetter = (metric: string): boolean | null => HIGHER_IS_BETTER[metric] ?? null;

/** Metrics that compare two weeks of one version: their change against another version is a gap in points, not a percentage. */
export const isWindowChange = (metric: string) => metric.endsWith("_change_vs_first_week");

export type Judgement = "better" | "worse" | "same" | "neutral";

/** "About the same" below a 1% relative difference. */
export function judge(metric: string, deltaPct: number | null | undefined, delta: number | null | undefined): Judgement {
  const dir = higherIsBetter(metric);
  const d = isWindowChange(metric) ? delta : deltaPct;
  if (d === null || d === undefined) return "neutral";
  if (Math.abs(d) < (isWindowChange(metric) ? 0.0025 : 0.01)) return "same";
  if (dir === null) return "neutral";
  return (d > 0) === dir ? "better" : "worse";
}

// ---------------------------------------------------------------- series entities

/** Short version name: "v2 Adapted A (regional language)" reads "Adapted A"; "v1 Original (Marathi)" reads "Original". */
export function shortVersion(label: string): string {
  const m = /^v\d+\s+(.*?)(?:\s*\(.*\))?$/.exec(label.trim());
  return m?.[1] || label;
}

/** The brief's colour rule: colour follows the entity, so a filter that removes a series never repaints the others. */
const REGION_SLOT: Record<string, number> = { "IN-MH": 1, "IN-TN": 2, "IN-KL": 3, "IN-WB": 4 };
const PLATFORM_SLOT: Record<string, number> = { google_ads: 1, youtube: 2, meta: 3, ga4: 4 };

export function slotFor(group: "region" | "version" | "platform", key: string, known: readonly string[] = []): number {
  if (group === "region") return REGION_SLOT[key] ?? Math.min(4, known.indexOf(key) + 1 || 4);
  if (group === "platform") return PLATFORM_SLOT[key] ?? Math.min(4, known.indexOf(key) + 1 || 4);
  const n = /^v(\d+)\b/.exec(key);
  return Math.min(4, n ? Number(n[1]) : known.indexOf(key) + 1 || 4);
}

// ---------------------------------------------------------------- chart scale

/** Zero-based "nice" ticks up to at least `max` (at most `count` steps). */
export function niceTicks(max: number, count = 5): number[] {
  if (!Number.isFinite(max) || max <= 0) return [0, 1];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const top = Math.ceil(max / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let v = 0; v <= top + step / 1e6; v += step) ticks.push(Number(v.toPrecision(12)));
  return ticks;
}

/** Axis tick text: whole numbers and compact large values, percentages without trailing zeros. */
export function formatTick(value: number, unit: Unit): string {
  if (unit === "ratio") {
    const pct = value * 100;
    return `${Number(pct.toFixed(pct >= 10 ? 0 : 2))}%`;
  }
  if (unit === "multiple") return `${Number(value.toFixed(2))}×`;
  const body = Math.abs(value) >= 10_000 ? compactFmt.format(value) : value >= 100 || Number.isInteger(value) ? grouped.format(value) : value.toFixed(2);
  return unit === "inr" ? `₹${body}` : body;
}

// ---------------------------------------------------------------- compare

const median = (xs: number[]) => {
  const s = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
};

export type Standout = { versionLabel: string; value: number; baselineValue: number; deltaPct: number | null; delta: number; baselineLeads: boolean };

/**
 * Which version leads in a region on one metric, and by how much against the baseline. Neutral metrics (impressions, reach,
 * spend) have no "better", so nothing stands out. Ties and missing values are skipped, never treated as 0.
 */
export function standout(region: RegionComparison, metric: string): Standout | null {
  const dir = higherIsBetter(metric);
  if (dir === null) return null;
  const cols = region.versions.flatMap((v) => {
    const m = v.metrics.find((x) => x.metric === metric);
    return m && m.value !== null ? [{ v, m }] : [];
  });
  const base = cols.find((c) => c.v.is_baseline);
  if (!base || cols.length < 2) return null;
  const best = cols.reduce((a, b) => ((b.m.value as number) > (a.m.value as number) === dir ? b : a));
  const value = best.m.value as number;
  const baselineValue = base.m.value as number;
  return {
    versionLabel: best.v.version_label,
    value,
    baselineValue,
    deltaPct: best.m.delta_pct_vs_baseline,
    delta: value - baselineValue,
    baselineLeads: best.v.is_baseline,
  };
}

// ---------------------------------------------------------------- alerts

export type CostPattern = {
  kind: "persistent" | "rising" | "unknown";
  /** Median daily value of the first 7 settled days, and of the last 7 settled days. */
  firstWeek: number | null;
  lastWeek: number | null;
  /** Each against the region average the alert rule used (comparison_value). */
  firstVsAverage: number | null;
  lastVsAverage: number | null;
};

/**
 * Tells a sudden rise from a standing gap for a cost-spike alert. The rule behind the alert compares the last 7 settled days
 * with the region's average over every version, so a version that was simply costlier from day one trips it too. Here the same
 * series is read in two windows: if the first 7 settled days already sat at least `thresholdPct` above that average, the
 * version is underperforming from launch (persistent); if not, the cost rose during the period (rising). Medians of the
 * daily values keep one odd day from deciding it. Needs 14 settled days, otherwise "unknown".
 */
export function classifyCostPattern(points: readonly SeriesPoint[], comparisonValue: number, thresholdPct: number): CostPattern {
  const settled = points.filter((p) => !p.provisional && p.value !== null).map((p) => p.value as number);
  const none: CostPattern = { kind: "unknown", firstWeek: null, lastWeek: null, firstVsAverage: null, lastVsAverage: null };
  if (settled.length < 14 || !comparisonValue) return none;
  const firstWeek = median(settled.slice(0, 7));
  const lastWeek = median(settled.slice(-7));
  const firstVsAverage = firstWeek / comparisonValue - 1;
  return {
    kind: firstVsAverage >= thresholdPct ? "persistent" : "rising",
    firstWeek,
    lastWeek,
    firstVsAverage,
    lastVsAverage: lastWeek / comparisonValue - 1,
  };
}

export const ALERT_META = {
  ctr_drop: { label: "CTR drop", rule: "CTR of the last 7 settled days against the version's own first week." },
  frequency_fatigue: { label: "Frequency fatigue", rule: "Frequency at or above the threshold while CTR is already falling against the first week." },
  cost_spike: { label: "Cost spike", rule: "CPM or CPA of the last 7 settled days against the region's average over every version." },
} as const;

/** The sentence an alert row leads with, from the API's observed and comparison values. */
export function alertHeadline(a: PulseAlert, regionName: string): string {
  switch (a.alert_type) {
    case "ctr_drop":
      return `CTR is ${percent(Math.abs(a.observed_value))} below this version's first week`;
    case "frequency_fatigue":
      return `Frequency has reached ${a.observed_value.toFixed(2)}× while CTR is ${percent(Math.abs(a.comparison_value))} below its first week`;
    case "cost_spike":
      return `${a.metric.toUpperCase()} is ${percent(a.observed_value)} above the ${regionName} average`;
  }
}

/** The figures behind the headline, so the reader can check the arithmetic. */
export function alertEvidence(a: PulseAlert): string {
  switch (a.alert_type) {
    case "ctr_drop":
      return `First week ${percent(a.comparison_value)} CTR, last settled week ${percent(a.comparison_value * (1 + a.observed_value))}.`;
    case "frequency_fatigue":
      return `Frequency through the last settled day, against a threshold of ${a.threshold.toFixed(2)}×.`;
    case "cost_spike": {
      const observed = a.comparison_value * (1 + a.observed_value);
      return `Last settled week about ${formatValue(observed, "inr")}, against a region average of ${formatValue(a.comparison_value, "inr")} over all versions.`;
    }
  }
}

/** Threshold fields the alert form edits, with the API's bounds (exclusive minimums use a step above the bound). */
export type ThresholdForm = { ctrDropPct: string; frequency: string; frequencyCtrPct: string; costSpikePct: string; minConversions: string };
export const DEFAULT_THRESHOLDS: ThresholdForm = { ctrDropPct: "20", frequency: "2.5", frequencyCtrPct: "10", costSpikePct: "30", minConversions: "30" };

export type ThresholdQuery = { ctr_drop_pct: number; frequency_threshold: number; frequency_min_ctr_decline_pct: number; cost_spike_pct: number; min_conversions: number };

/** Parses the form into the API's units (percent to ratio) or returns what is wrong, field by field. */
export function parseThresholds(f: ThresholdForm): { ok: true; query: ThresholdQuery } | { ok: false; errors: Partial<Record<keyof ThresholdForm, string>> } {
  const errors: Partial<Record<keyof ThresholdForm, string>> = {};
  const num = (text: string) => (text.trim() === "" ? NaN : Number(text));
  const ctr = num(f.ctrDropPct);
  const freq = num(f.frequency);
  const freqCtr = num(f.frequencyCtrPct);
  const cost = num(f.costSpikePct);
  const conv = num(f.minConversions);
  if (!(ctr > 0 && ctr <= 100)) errors.ctrDropPct = "Enter a percentage above 0 and up to 100.";
  if (!(freq > 1 && freq <= 20)) errors.frequency = "Enter a frequency above 1 and up to 20.";
  if (!(freqCtr > 0 && freqCtr <= 100)) errors.frequencyCtrPct = "Enter a percentage above 0 and up to 100.";
  if (!(cost > 0 && cost <= 500)) errors.costSpikePct = "Enter a percentage above 0 and up to 500.";
  if (!(Number.isInteger(conv) && conv >= 1 && conv <= 10_000)) errors.minConversions = "Enter a whole number from 1 to 10,000.";
  if (Object.keys(errors).length) return { ok: false, errors };
  return {
    ok: true,
    query: {
      ctr_drop_pct: ctr / 100,
      frequency_threshold: freq,
      frequency_min_ctr_decline_pct: freqCtr / 100,
      cost_spike_pct: cost / 100,
      min_conversions: conv,
    },
  };
}
