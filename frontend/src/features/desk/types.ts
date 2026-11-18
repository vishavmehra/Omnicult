import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type Brief = S["CampaignBrief"];
export type BriefContent = S["BriefContent-Output"];
export type BriefVersionSummary = S["BriefVersionSummary"];
export type BriefVersion = S["BriefVersion"];
export type BriefField = S["BriefCompleteness"]["missing"][number];
export type BrandKit = S["BrandKit"];
export type KitDesign = S["KitDesign-Output"];
export type KitContrast = S["KitContrastResult"];
export type Today = S["TodayView"];
export type TodayCampaign = S["TodayCampaign"];
export type TodayEvent = S["TodayEvent"];
export type TodayConflict = S["TodayConflict"];
export type TodayNextAction = S["TodayNextAction"];
export type Region = S["Region"];

export const REQUIRED_LABEL: Record<BriefField, string> = {
  objective: "Objective",
  origin_region: "Origin region",
  target_regions: "Target regions",
  languages: "Languages for every target",
  channels: "Channels",
  budget: "Budget",
  dates: "Campaign dates",
  success_metric: "Primary success metric",
};

const languageNames = new Intl.DisplayNames(["en"], { type: "language" });
const scriptNames = new Intl.DisplayNames(["en"], { type: "script" });

function safe(names: Intl.DisplayNames, code: string) {
  try {
    return names.of(code) ?? code;
  } catch {
    return code;
  }
}

export const languageName = (code: string) => safe(languageNames, code);
export const scriptName = (code: string) => safe(scriptNames, code);

/** "₹24,00,000" for INR (Indian digit grouping); other currencies use their own symbol. Falls back to the code on a bad currency. */
export function formatMoney(currency: string, amount: number) {
  try {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: amount % 1 ? 2 : 0 }).format(amount);
  } catch {
    return `${currency} ${amount.toLocaleString("en-IN")}`;
  }
}

/** A stable id from a name: "Instagram Reels" becomes "instagram-reels". */
export function slugify(text: string, fallback = "item") {
  const slug = text
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  return slug || fallback;
}

/** A slug that does not collide with the ones already taken. */
export function uniqueSlug(text: string, taken: string[], fallback?: string) {
  const base = slugify(text, fallback);
  if (!taken.includes(base)) return base;
  let n = 2;
  while (taken.includes(`${base}-${n}`)) n += 1;
  return `${base}-${n}`;
}

export const dayLabel = (iso: string) =>
  new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(`${iso}T00:00:00Z`));

export function daysBetween(start: string, end: string) {
  return Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000) + 1;
}

export const AGE_BANDS = ["18-24", "25-34", "35-44", "45-54", "55+"] as const;
export const CITY_TIERS = [
  { value: "tier1", label: "Tier 1 cities" },
  { value: "tier2", label: "Tier 2 cities" },
  { value: "tier3", label: "Tier 3 cities" },
  { value: "rural", label: "Rural" },
] as const;
export const SCRIPTS = ["Latn", "Deva", "Taml", "Mlym", "Beng", "Telu", "Knda", "Gujr", "Guru", "Orya"] as const;
export const STATUS_LABEL = { planning: "Planning", live: "In market", closed: "Closed" } as const;

/** A brief with every optional part empty, so the editor can read it without null checks. */
export const emptyBrief = (): BriefContent => ({
  status: "planning",
  objective: null,
  product: null,
  target_audience: null,
  regions: { origin: null, targets: [] },
  languages: {},
  scripts: {},
  channels: [],
  budget: null,
  dates: null,
  success_metric: null,
  primary_message: null,
  cta: null,
  original_creative_refs: [],
  constraints: [],
});
