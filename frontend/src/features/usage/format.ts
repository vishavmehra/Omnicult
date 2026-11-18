import { humanize } from "@/lib/format";

import type { UsageRow } from "./api";

export const NOT_RECORDED = "Not recorded";

const CAPABILITY: Record<string, string> = {
  chat: "Text",
  text: "Text",
  embeddings: "Embeddings",
  vision: "Vision",
  transcribe: "Transcription",
  image_generation: "Image generation",
  tts: "Text to speech",
  grounded_research: "Grounded research",
  live: "Live audio",
  music: "Music",
};
export const capabilityLabel = (key: string) => CAPABILITY[key] ?? humanize(key);

/** `google / gemini-3.8-flash` stays as the gateway names it; only the separator is read aloud-friendly. */
export const modelLabel = (key: string) => key.replace(" / ", ", ");

/** Small amounts keep four decimals so a $0.0021 call does not read as $0.00. A missing cost is never printed as 0. */
export function usd(n: number | null | undefined) {
  if (n === null || n === undefined) return NOT_RECORDED;
  return `$${n === 0 ? "0.00" : n < 1 ? n.toFixed(4) : n.toFixed(2)}`;
}

/** A short money label for a chart axis: $0.5, $0.02, $5. */
export const axisUsd = (n: number) => `$${n >= 1 ? n : +n.toPrecision(2)}`;

export const num = new Intl.NumberFormat("en");

const day = new Intl.DateTimeFormat("en", { day: "numeric", month: "short", timeZone: "UTC" });
const dayLong = new Intl.DateTimeFormat("en", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
const clock = new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" });
const utcDay = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00Z`);
export const formatDay = (iso: string) => day.format(utcDay(iso));
export const formatDayLong = (iso: string) => dayLong.format(utcDay(iso));
export const formatUtcTime = (iso: string) => `${dayLong.format(new Date(iso))}, ${clock.format(new Date(iso))} UTC`;

/** Time until the daily ceiling resets (UTC midnight), as "5h 12m". */
export function untilReset(resetsAt: string, now = Date.now()) {
  const minutes = Math.max(0, Math.round((Date.parse(resetsAt) - now) / 60_000));
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m` : `${minutes}m`;
}

/** What the cost cell says for a row: the recorded sum, or that none was recorded, plus what the sum leaves out. */
export function costParts(row: Pick<UsageRow, "estimated_cost_usd" | "calls" | "calls_without_cost" | "fixture_calls" | "price_known">) {
  const allFixture = row.fixture_calls > 0 && row.fixture_calls === row.calls;
  return {
    value: usd(row.estimated_cost_usd),
    recorded: row.estimated_cost_usd !== null,
    note: allFixture
      ? "fixture, no model ran"
      : [
          row.calls_without_cost > 0 ? `${num.format(row.calls_without_cost)} without a recorded cost` : null,
          row.price_known === false ? "stand-in price" : null,
        ]
          .filter(Boolean)
          .join(", "),
  };
}
