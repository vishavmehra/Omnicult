import { CircleCheck, CircleDot, CircleHelp, CircleSlash, Frown, Info, Meh, OctagonAlert, Scale, Smile, TriangleAlert, type LucideIcon } from "lucide-react";

import type { FindingStatus, ReactionCategory, RiskCategory, Severity } from "./types";

import { SEVERITY_RANK } from "./logic";

export * from "./logic";

export const REACTIONS: { key: ReactionCategory; label: string; Icon: LucideIcon }[] = [
  { key: "positive", label: "Positive", Icon: Smile },
  { key: "mixed", label: "Mixed", Icon: Scale },
  { key: "neutral", label: "Neutral", Icon: Meh },
  { key: "negative", label: "Negative", Icon: Frown },
  { key: "confused", label: "Confused", Icon: CircleHelp },
];
export const REACTION_LABEL = Object.fromEntries(REACTIONS.map((r) => [r.key, r.label])) as Record<ReactionCategory, string>;

export const CITY_TIER_LABEL: Record<string, string> = { tier1: "Tier 1 city", tier2: "Tier 2 city", tier3: "Tier 3 town", rural: "Rural" };
export const DIMENSION_LABEL: Record<string, string> = { states: "State", languages: "Language", city_tiers: "City tier", age_bands: "Age band" };

export const RATING_LABEL: Record<string, string> = { clarity: "Clarity", cultural_relevance: "Cultural relevance", cultural_risk: "Cultural risk", brand_fidelity: "Brand fidelity" };

export const SURVIVAL_LABEL = { understood: "Understood", partial: "Partly understood", misunderstood: "Misunderstood" } as const;

export const CATEGORY_LABEL: Record<RiskCategory, string> = {
  brand_rule: "Brand rule",
  unsubstantiated_claim: "Unsubstantiated claim",
  health_nutrition_claim: "Health or nutrition claim",
  comparative_claim: "Comparative claim",
  children_safety: "Children and safety",
  unsafe_depiction: "Unsafe depiction",
  offensive_content: "Offensive content",
  stereotype_or_derision: "Stereotype or derision",
  disclaimer_issue: "Disclaimer issue",
  synthetic_media_disclosure: "Synthetic media disclosure",
  regional_sensitivity: "Regional sensitivity",
  language_ambiguity: "Language ambiguity",
  other: "Other",
};

export const SEVERITY: Record<Severity, { label: string; rank: number; Icon: LucideIcon; className: string }> = {
  high: { label: "High", rank: SEVERITY_RANK.high, Icon: OctagonAlert, className: "border-danger/45 bg-danger-soft text-danger" },
  medium: { label: "Medium", rank: SEVERITY_RANK.medium, Icon: TriangleAlert, className: "border-warning/45 bg-warning-soft text-warning" },
  low: { label: "Low", rank: SEVERITY_RANK.low, Icon: Info, className: "border-border-strong/50 bg-surface-muted text-ink-secondary" },
};

/** The API calls a resolved finding `fixed`; the product says resolved. */
export const FINDING_STATUS: Record<FindingStatus, { label: string; Icon: LucideIcon; className: string; meaning: string }> = {
  open: { label: "Open", Icon: CircleDot, className: "text-ink", meaning: "Not yet reviewed. It counts toward Go while open." },
  accepted: { label: "Accepted", Icon: CircleCheck, className: "text-info", meaning: "A person agrees it is a real problem. It still counts toward Go until it is resolved." },
  dismissed: { label: "Dismissed", Icon: CircleSlash, className: "text-ink-muted", meaning: "A person decided it is not a problem and recorded why. It no longer counts toward Go." },
  fixed: { label: "Resolved", Icon: CircleCheck, className: "text-success", meaning: "The creative was changed to address it. It no longer counts toward Go." },
};

export const newKey = () => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `lab-${Date.now()}-${Math.random().toString(36).slice(2)}`);
