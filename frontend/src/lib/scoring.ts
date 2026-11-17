import type { EvaluationCriteria } from "@/lib/api/types";

/** Default campaign scoring weights (contract default). They must total 1.000 and are never rescaled. */
export const DEFAULT_WEIGHTS: EvaluationCriteria = { clarity: 0.3, brand_fidelity: 0.25, cultural_relevance: 0.3, cultural_risk: 0.15 };

/** The four scored criteria, in display order. Plain data, safe to import from server components. */
export const WEIGHT_FIELDS: { key: keyof EvaluationCriteria; label: string; help: string }[] = [
  { key: "clarity", label: "Clarity", help: "How clearly the message reads." },
  { key: "brand_fidelity", label: "Brand fidelity", help: "Consistency with the brand voice and terms." },
  { key: "cultural_relevance", label: "Cultural relevance", help: "Fit with the target market's context." },
  { key: "cultural_risk", label: "Cultural risk", help: "Inverted into utility: 100 − risk score." },
];
