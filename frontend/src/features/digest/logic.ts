/**
 * Comment Pulse and Weekly Digest display logic: pure functions with no React and no network, so each rule can be tested on its
 * own (logic.test.mjs, run with `node --test`). Nothing here invents a number: it parses, orders, formats and labels what the
 * API returned. Imports are type-only so the file also loads under Node's TypeScript stripping.
 */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];
export type CommentSummary = S["CommentSummary"];
export type CommentSlice = S["CommentSlice"];
export type SentimentCounts = S["SentimentCounts"];
export type CommentItem = S["CommentItem"];
export type SentimentLabel = NonNullable<CommentItem["interpretation"]>["sentiment"];
export type CommentTheme = S["CommentTheme"];
export type Digest = S["Digest"];
export type DigestContent = S["DigestContent"];
export type DigestAction = S["DigestAction"];
export type DigestSource = S["DigestSource"];
export type DigestWeek = S["DigestWeek"];

// ---------------------------------------------------------------- the Pulse views

export type PulseView = "overview" | "predicted" | "alerts" | "fatigue" | "comments" | "digest";
export const PULSE_VIEWS: { key: PulseView; label: string }[] = [
  { key: "overview", label: "Dashboard" },
  { key: "predicted", label: "Predicted vs Actual" },
  { key: "alerts", label: "Alerts" },
  { key: "fatigue", label: "Fatigue Watch" },
  { key: "comments", label: "Comment Pulse" },
  { key: "digest", label: "Weekly Digest" },
];
export const asPulseView = (value: string | null | undefined): PulseView => (PULSE_VIEWS.some((v) => v.key === value) ? (value as PulseView) : "overview");

// ---------------------------------------------------------------- one quiet source line per view

export const COMMENT_SOURCE = "Source: sample comments, written for the demo, not from a connected channel";
export const DIGEST_SOURCE = "Source: stored campaign records and the Live Pulse sample dataset";
export const MODEL_INTERPRETATION = "Model interpretation";

// ---------------------------------------------------------------- sentiment

export const SENTIMENTS = ["positive", "neutral", "negative", "mixed"] as const;
export const SENTIMENT_LABEL: Record<(typeof SENTIMENTS)[number], string> = { positive: "Positive", neutral: "Neutral", negative: "Negative", mixed: "Mixed" };

export type SentimentRead = { read: number; shares: Record<(typeof SENTIMENTS)[number], number> };

/** Counts and shares of the comments that carry a model label. Unread comments are left out of the shares, never counted as neutral. */
export function sentimentRead(counts: SentimentCounts | null | undefined): SentimentRead | null {
  if (!counts) return null;
  const read = counts.positive + counts.neutral + counts.negative + counts.mixed;
  if (!read) return null;
  return {
    read,
    shares: { positive: counts.positive / read, neutral: counts.neutral / read, negative: counts.negative / read, mixed: counts.mixed / read },
  };
}

export const shareText = (share: number | null | undefined) => (share === null || share === undefined ? "n/a" : `${Math.round(share * 100)}%`);

export const LANGUAGE_NAME: Record<string, string> = { mr: "Marathi", ta: "Tamil", ml: "Malayalam", bn: "Bengali", en: "English" };

export const CONFIDENCE_LEVEL = { low: "low", moderate: "moderate" } as const;

// ---------------------------------------------------------------- matched terms

export type Segment = { text: string; match: boolean };

/** Splits a comment around the first occurrence of the watch term code matched in it, so the match can be marked in the text. */
export function highlight(text: string, term: string | null | undefined): Segment[] {
  if (!term) return [{ text, match: false }];
  const at = text.toLowerCase().indexOf(term.toLowerCase());
  if (at < 0) return [{ text, match: false }];
  return [
    ...(at > 0 ? [{ text: text.slice(0, at), match: false }] : []),
    { text: text.slice(at, at + term.length), match: true },
    ...(at + term.length < text.length ? [{ text: text.slice(at + term.length), match: false }] : []),
  ];
}

/** BCP 47 tag for a comment, so its script gets the right face: a regional language written in Latin letters is not tagged with the regional script. */
export const langTag = (language: string, script: string) => (script === "Latn" && language !== "en" ? `${language}-Latn` : language);

// ---------------------------------------------------------------- weeks

const DAY = 86_400_000;
const parse = (iso: string) => Date.parse(`${iso}T00:00:00Z`);
export const addDays = (iso: string, n: number) => new Date(parse(iso) + n * DAY).toISOString().slice(0, 10);

/** ISO 8601 week label of a date, for example "2026-W46". */
export function isoWeekLabel(iso: string): string {
  const d = new Date(parse(iso));
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7) + 3); // the Thursday of this week decides the ISO year
  const year = d.getUTCFullYear();
  const jan4 = new Date(Date.UTC(year, 0, 4)); // 4 January is always in week 1
  const thursdayOfWeekOne = Date.UTC(year, 0, 4 - ((jan4.getUTCDay() + 6) % 7) + 3);
  const week = 1 + Math.round((d.getTime() - thursdayOfWeekOne) / (7 * DAY));
  return `${year}-W${String(week).padStart(2, "0")}`;
}

const monthDay = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
export const weekSpan = (start: string, end: string) => `${monthDay.format(parse(start))} to ${monthDay.format(parse(end))}`;

/** The week in progress and the five before it, newest first: the weeks a person can ask a digest for. */
export function weekChoices(current: { start: string; end: string }, count = 6): { value: string; label: string }[] {
  return Array.from({ length: count }, (_, i) => {
    const start = addDays(current.start, -7 * i);
    const end = addDays(start, 6);
    return { value: start, label: `${isoWeekLabel(start)}, ${weekSpan(start, end)}${i === 0 ? " (this week)" : ""}` };
  });
}

/** Seven-day periods of the sample run, from its first day: the "weeks" the comment trend is bucketed in. */
export function runWeeks(first: string | null, last: string | null): { key: string; label: string; from: string; to: string }[] {
  if (!first || !last) return [];
  const out = [];
  for (let from = first, i = 1; from <= last; from = addDays(from, 7), i += 1) {
    const to = addDays(from, 6);
    out.push({ key: `w${i}`, label: `Week ${i}`, from, to: to > last ? last : to });
  }
  return out;
}

// ---------------------------------------------------------------- where a digest line leads

export type Destination = { workspace: DigestSource["workspace"]; view: string | null; ref: string | null };

/** Path inside the campaign for a digest source. Pulse views are a query; Studio opens a version; the rest open their workspace. */
export function sourceHref(campaignId: string, source: Destination): string {
  const base = `/app/c/${campaignId}/${source.workspace}`;
  if (source.workspace === "pulse") return source.view && source.view !== "overview" ? `${base}?view=${source.view}` : base;
  if (source.workspace === "studio" && source.ref) return `${base}?v=${source.ref}`;
  return base;
}

export const WORKSPACE_LABEL: Record<DigestSource["workspace"], string> = {
  desk: "Campaign Desk", lens: "Market Lens", studio: "Creative Studio", lab: "Audience Lab", launch: "Launch Room", pulse: "Live Pulse", proof: "Proof Vault",
};

export const PRIORITY_LABEL: Record<DigestAction["priority"], string> = { 1: "Do first", 2: "Soon", 3: "When you can" };

/** Total of everything the week recorded, for a one-line summary of the empty case. */
export const changeTotal = (c: DigestContent) => Object.values(c.what_changed.counts).reduce((a, b) => a + b, 0);
