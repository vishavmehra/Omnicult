/**
 * Live Pulse Tier 3 display logic: pure functions with no React and no network (logic.test.mjs, run with `node --test`).
 * Every score, rank, status and threshold arrives from the API, computed in code; nothing here invents one. This file words
 * them, validates the alert rule form against the API's bounds and shapes the fatigue charts. Imports are type-only so it
 * also loads under Node's TypeScript stripping.
 */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];
export type PvaResult = S["PvaResult"];
export type PvaPair = S["PvaPair"];
export type PvaSummary = S["PvaSummary"];
export type PvaCheck = S["PvaCheck"];
export type PvaMetric = S["PvaResult"]["metric"];
export type AlertRuleType = S["AlertRuleCreate"]["alert_type"];
export type AlertRuleParams = S["AlertRuleParams-Input"];
export type AlertRuleView = S["AlertRuleView"];
export type AlertRecord = S["AlertRecord"];
export type AlertRecordEvent = S["AlertRecordEvent"];
export type FatigueRow = S["FatigueRow"];
export type FatigueSignal = S["FatigueSignal"];
export type FatiguePoint = S["FatiguePoint"];

export const SOURCE_LINE = "Source: sample dataset.";
export const CALIBRATION_LINE = "This shows the method working on the sample dataset; it does not show that the panel is calibrated.";

// ---------------------------------------------------------------- Predicted vs Actual

export const PVA_METRICS: { value: PvaMetric; label: string }[] = [
  { value: "ctr", label: "CTR" },
  { value: "view_rate", label: "View rate" },
  { value: "completion_100", label: "100% completion" },
  { value: "roas", label: "ROAS" },
];

export const VERDICT_LABEL = { go: "Go", fix: "Fix", rethink: "Rethink" } as const;

export const AGREEMENT_LABEL = { agree: "Agrees", near: "Near", differ: "Differs" } as const;
export const AGREEMENT_HELP = {
  agree: "The prediction and the result gave this pair the same rank.",
  near: "The prediction and the result ranked this pair one place apart.",
  differ: "The prediction and the result ranked this pair two or more places apart.",
} as const;

/** "1", "2.5": a tied rank is the mean of the places it spans. */
export const formatRank = (rank: number) => (Number.isInteger(rank) ? String(rank) : rank.toFixed(1));

export function formatTau(tau: number | null): string {
  if (tau === null) return "n/a";
  return `${tau > 0 ? "+" : tau < 0 ? "-" : ""}${Math.abs(tau).toFixed(2)}`;
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** What the ranking says about a predictor, in words. Only counts the API computed. */
export function summaryHeadline(s: PvaSummary): string {
  if (s.pairs === 0) return "No pairs yet";
  if (s.reading === "too_few_pairs") return `${plural(s.pairs, "pair")}: too few to read an order`;
  const all = s.concordant + s.discordant + s.tied;
  const reading = { mostly_agrees: "mostly the same order", mixed: "a mixed order", mostly_disagrees: "mostly the opposite order" }[s.reading];
  return `${reading}: ${s.concordant} of ${plural(all, "comparison")} between two pairs agree`;
}

export function summaryDetail(s: PvaSummary): string {
  if (s.pairs === 0) return "A pair needs a linked Studio version with a stored prediction and settled Pulse results.";
  const counts = `${s.agree} agree, ${s.near} near, ${s.differ} differ across ${plural(s.pairs, "pair")}.`;
  if (s.reading === "too_few_pairs") return `${counts} A rank correlation needs at least 3 pairs.`;
  return `${counts} ${s.discordant} ordered the opposite way, ${s.tied} tied. Kendall's tau-b ${formatTau(s.kendall_tau_b)}.`;
}

export function snapshotNote(matches: boolean): string {
  return matches ? "Reproduces: recomputing now gives the same fingerprint." : "The stored verdicts, links or results have changed since, so today's comparison differs.";
}

// ---------------------------------------------------------------- Alerts

export const ALERT_TYPE_ORDER: AlertRuleType[] = ["ctr_drop", "frequency_fatigue", "cost_spike", "prediction_miss"];

export type FieldKey = "ctr_drop_pct" | "frequency_threshold" | "frequency_min_ctr_decline_pct" | "cost_spike_pct" | "min_conversions" | "min_rank_gap";
export type FieldSpec = {
  key: FieldKey;
  label: string;
  suffix: string;
  step: string;
  /** The API takes a ratio; the form shows a percentage. */
  percent?: boolean;
  integer?: boolean;
  min: number;
  max: number;
  /** The bound is exclusive (the API's `gt`). */
  exclusiveMin?: boolean;
  initial: string;
  error: string;
};

/** Thresholds with the bounds of the alert preview and of the API (`gt`/`le` on the same fields). */
export const FIELDS: Record<FieldKey, FieldSpec> = {
  ctr_drop_pct: { key: "ctr_drop_pct", label: "CTR is at least", suffix: "% below the first week", step: "1", percent: true, min: 0, max: 100, exclusiveMin: true, initial: "20", error: "Enter a percentage above 0 and up to 100." },
  frequency_threshold: { key: "frequency_threshold", label: "Frequency is at or above", suffix: "×", step: "0.1", min: 1, max: 20, exclusiveMin: true, initial: "2.5", error: "Enter a frequency above 1 and up to 20." },
  frequency_min_ctr_decline_pct: { key: "frequency_min_ctr_decline_pct", label: "and CTR is at least", suffix: "% below the first week", step: "1", percent: true, min: 0, max: 100, exclusiveMin: true, initial: "10", error: "Enter a percentage above 0 and up to 100." },
  cost_spike_pct: { key: "cost_spike_pct", label: "Cost is at least", suffix: "% above the region average", step: "5", percent: true, min: 0, max: 500, exclusiveMin: true, initial: "30", error: "Enter a percentage above 0 and up to 500." },
  min_conversions: { key: "min_conversions", label: "CPA needs at least", suffix: "conversions in the week", step: "1", integer: true, min: 1, max: 10_000, initial: "30", error: "Enter a whole number from 1 to 10,000." },
  min_rank_gap: { key: "min_rank_gap", label: "Flag when prediction and result are", suffix: "or more ranks apart", step: "1", integer: true, min: 1, max: 20, initial: "2", error: "Enter a whole number from 1 to 20." },
};

export const ALERT_TYPES: Record<AlertRuleType, { label: string; rule: string; fields: FieldKey[]; action: string }> = {
  ctr_drop: {
    label: "CTR drop",
    rule: "CTR of the last 7 settled days against the version's own first week.",
    fields: ["ctr_drop_pct"],
    action: "Refresh the creative or rotate another version in.",
  },
  frequency_fatigue: {
    label: "Frequency fatigue",
    rule: "Frequency at or above the threshold while CTR is already falling against the first week.",
    fields: ["frequency_threshold", "frequency_min_ctr_decline_pct"],
    action: "Cap frequency or rotate a fresh version in.",
  },
  cost_spike: {
    label: "Cost spike",
    rule: "CPM or CPA of the last 7 settled days against the region's average over every version.",
    fields: ["cost_spike_pct", "min_conversions"],
    action: "Review bids, targeting and the landing flow.",
  },
  prediction_miss: {
    label: "Prediction miss",
    rule: "A version's rank by Launch Room score differs from its rank by CTR by at least the gap. Needs three compared pairs.",
    fields: ["min_rank_gap"],
    action: "Validate the creative with real people.",
  },
};

export type CostMetric = "both" | "cpm" | "cpa";
export type RuleForm = { name: string; region: string; version: string; enabled: boolean; values: Partial<Record<FieldKey, string>>; costMetric: CostMetric };

export function emptyForm(type: AlertRuleType): RuleForm {
  return {
    name: ALERT_TYPES[type].label,
    region: "",
    version: "",
    enabled: true,
    values: Object.fromEntries(ALERT_TYPES[type].fields.map((k) => [k, FIELDS[k].initial])),
    costMetric: "both",
  };
}

const show = (spec: FieldSpec, value: number) => String(spec.percent ? Number((value * 100).toPrecision(6)) : value);

export function formFromRule(rule: AlertRuleView): RuleForm {
  const values: RuleForm["values"] = {};
  for (const key of ALERT_TYPES[rule.alert_type].fields) {
    const v = rule.params[key];
    values[key] = v === null || v === undefined ? FIELDS[key].initial : show(FIELDS[key], v);
  }
  return { name: rule.name, region: rule.region_code ?? "", version: rule.version_label ?? "", enabled: rule.enabled, values, costMetric: rule.params.cost_metric ?? "both" };
}

export type FormResult =
  | { ok: true; params: AlertRuleParams }
  | { ok: false; errors: Partial<Record<FieldKey | "name", string>> };

/** Parses the form into the API's units, or says what is wrong field by field (the API would refuse the same values with a 422). */
export function parseRuleForm(type: AlertRuleType, form: RuleForm): FormResult {
  const errors: Partial<Record<FieldKey | "name", string>> = {};
  const params: Record<string, number | string> = {};
  if (form.name.trim() === "" || form.name.trim().length > 60) errors.name = "Name the rule, in up to 60 characters.";
  for (const key of ALERT_TYPES[type].fields) {
    const spec = FIELDS[key];
    const text = (form.values[key] ?? "").trim();
    const n = text === "" ? NaN : Number(text);
    const inRange = spec.exclusiveMin ? n > spec.min : n >= spec.min;
    if (!(inRange && n <= spec.max) || (spec.integer && !Number.isInteger(n))) errors[key] = spec.error;
    else params[key] = spec.percent ? Number((n / 100).toPrecision(12)) : n;
  }
  if (type === "cost_spike") params.cost_metric = form.costMetric;
  return Object.keys(errors).length ? { ok: false, errors } : { ok: true, params: params as AlertRuleParams };
}

/** One line for a saved rule: what it watches and at what threshold. */
export function describeRule(rule: AlertRuleView): string {
  const p = rule.params;
  const pct = (v: number | null | undefined) => `${Number(((v ?? 0) * 100).toPrecision(4))}%`;
  switch (rule.alert_type) {
    case "ctr_drop":
      return `CTR ${pct(p.ctr_drop_pct)} or more below the version's first week`;
    case "frequency_fatigue":
      return `Frequency at ${p.frequency_threshold}× or more with CTR ${pct(p.frequency_min_ctr_decline_pct)} or more below the first week`;
    case "cost_spike": {
      const which = p.cost_metric === "cpm" ? "CPM" : p.cost_metric === "cpa" ? "CPA" : "CPM or CPA";
      return `${which} ${pct(p.cost_spike_pct)} or more above the region average${p.cost_metric === "cpm" ? "" : `, CPA from ${p.min_conversions} conversions`}`;
    }
    case "prediction_miss":
      return `Launch Room rank and CTR rank ${p.min_rank_gap} or more places apart`;
  }
}

export function scopeText(rule: { region_code: string | null; version_label: string | null }, regionName: (code: string) => string): string {
  const region = rule.region_code ? regionName(rule.region_code) : "Every region";
  return `${region}, ${rule.version_label ? rule.version_label : "every version"}`;
}

/** An alert's threshold and observed value in the units its rule reads (ratios as percentages), so the raw 0.3 is never shown. */
export function alertFigures(a: Pick<AlertRecord, "alert_type" | "threshold" | "observed_value">): string {
  const pct = (v: number) => `${Number((Math.abs(v) * 100).toPrecision(3))}%`;
  switch (a.alert_type) {
    case "ctr_drop":
      return `Threshold ${pct(a.threshold)} below the first week, observed ${pct(a.observed_value)}`;
    case "frequency_fatigue":
      return `Threshold ${a.threshold}×, observed ${a.observed_value.toFixed(2)}×`;
    case "cost_spike":
      return `Threshold ${pct(a.threshold)} above the region average, observed ${pct(a.observed_value)}`;
    case "prediction_miss":
      return `Threshold ${a.threshold} ${a.threshold === 1 ? "rank" : "ranks"} apart, observed ${a.observed_value}`;
  }
}

export const STATUS_LABEL = { open: "Open", acknowledged: "Acknowledged", resolved: "Resolved" } as const;
export const RESOLUTION_LABEL: Record<string, string> = {
  manual: "Resolved by a person",
  cleared: "Cleared: the condition no longer holds",
  rule_removed: "The rule was deleted",
  rule_disabled: "The rule was switched off",
};
export const EVENT_LABEL = { opened: "Opened", acknowledged: "Acknowledged", resolved: "Resolved", reopened: "Reopened" } as const;
export const TRIGGER_LABEL = { refresh: "sample refresh", manual: "on demand", scheduler: "scheduled run", user: "a person" } as const;

export function eventActor(e: AlertRecordEvent): string {
  if (e.trigger === "user") return "a person";
  return e.actor_user_id ? `a person, ${TRIGGER_LABEL[e.trigger]}` : TRIGGER_LABEL[e.trigger];
}

export function evaluationLine(e: { trigger: keyof typeof TRIGGER_LABEL; rules_evaluated: number; alerts_found: number; opened: number; reopened: number; resolved: number; not_evaluated: number }): string {
  const parts = [`${plural(e.rules_evaluated, "rule")} read`, `${plural(e.alerts_found, "alert")} firing`];
  if (e.opened + e.reopened) parts.push(`${e.opened + e.reopened} opened or reopened`);
  if (e.resolved) parts.push(`${e.resolved} cleared`);
  if (e.not_evaluated) parts.push(`${e.not_evaluated} not readable`);
  return parts.join(", ");
}

// ---------------------------------------------------------------- Fatigue Watch

export const FATIGUE_STATUS = {
  fatigued: { label: "Fatigued", rank: 0 },
  watch: { label: "Watch", rank: 1 },
  healthy: { label: "Healthy", rank: 2 },
  not_enough_data: { label: "Not enough data", rank: 3 },
} as const;

export const PATTERN_LABEL = {
  wearing_out: "Wearing out: CTR falls through the period",
  static_low: "Static: low from the first week, not decaying",
  steady: "Steady",
  unknown: "Not assessed",
} as const;

/** Threshold fields for the fatigue controls (the API bounds: gt 0 le 100 percent; frequency gt 1 le 20). */
export type FatigueForm = { ctr: string; viewRate: string; frequency: string };
export const FATIGUE_DEFAULTS: FatigueForm = { ctr: "10", viewRate: "10", frequency: "2.5" };
export type FatigueQuery = { ctr_decline_pct: number; view_rate_decline_pct: number; frequency_threshold: number };

export function parseFatigueForm(f: FatigueForm): { ok: true; query: FatigueQuery } | { ok: false; errors: Partial<Record<keyof FatigueForm, string>> } {
  const errors: Partial<Record<keyof FatigueForm, string>> = {};
  const num = (t: string) => (t.trim() === "" ? NaN : Number(t));
  const ctr = num(f.ctr);
  const view = num(f.viewRate);
  const freq = num(f.frequency);
  if (!(ctr > 0 && ctr <= 100)) errors.ctr = "Enter a percentage above 0 and up to 100.";
  if (!(view > 0 && view <= 100)) errors.viewRate = "Enter a percentage above 0 and up to 100.";
  if (!(freq > 1 && freq <= 20)) errors.frequency = "Enter a frequency above 1 and up to 20.";
  if (Object.keys(errors).length) return { ok: false, errors };
  return { ok: true, query: { ctr_decline_pct: Number((ctr / 100).toPrecision(12)), view_rate_decline_pct: Number((view / 100).toPrecision(12)), frequency_threshold: freq } };
}

export type Plotted = { x: number; y: number; value: number; provisional: boolean };

/** Days the fatigue signals compare at each end of the series: the first week and the last settled week. */
export const WINDOW_DAYS = 7;

/**
 * Plot positions for a daily series on a W x H canvas: days across, zero at the bottom (a ratio axis starts at zero). Null days are
 * left out, never drawn as 0. `minMax` keeps a reference line (a threshold) inside the axis. Returns the points, the top of the axis
 * and the y position of any value, so a reference line shares the series' scale.
 */
export function plot(
  points: readonly FatiguePoint[], width: number, height: number, pad: { l: number; r: number; t: number; b: number }, minMax = 0,
): { points: Plotted[]; max: number; x: (i: number) => number; y: (v: number) => number } {
  const known = points.filter((p) => p.value !== null);
  const max = Math.max(minMax, ...known.map((p) => p.value as number)) * 1.1 || 1;
  const n = points.length;
  const x = (i: number) => pad.l + (n > 1 ? (i * (width - pad.l - pad.r)) / (n - 1) : 0);
  const y = (v: number) => pad.t + (height - pad.t - pad.b) * (1 - v / max);
  return { points: points.flatMap((p, i) => (p.value === null ? [] : [{ x: x(i), y: y(p.value), value: p.value, provisional: p.provisional }])), max, x, y };
}

/** An SVG path through the points. Provisional points are split into their own dashed path, joined to the last settled point. */
export function linePaths(points: readonly Plotted[]): { settled: string; provisional: string } {
  const at = (p: Plotted) => `${p.x.toFixed(1)} ${p.y.toFixed(1)}`;
  const settled = points.filter((p) => !p.provisional);
  const tail = points.filter((p) => p.provisional);
  const bridge = settled.length && tail.length ? [settled[settled.length - 1], ...tail] : [];
  return {
    settled: settled.map((p, i) => `${i ? "L" : "M"}${at(p)}`).join(" "),
    provisional: bridge.map((p, i) => `${i ? "L" : "M"}${at(p)}`).join(" "),
  };
}
