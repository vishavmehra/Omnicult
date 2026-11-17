/** Confidence levels and their deterministic rules. Plain data, safe to import from server components. */
export type ConfidenceLevel = "low" | "moderate" | "high" | "deterministic";

/** The deterministic rules behind each level (MASTER_PROMPT 6.2). Computed by backend code, never chosen by a model. */
export const CONFIDENCE: Record<ConfidenceLevel, { label: string; filled: number; rule: string }> = {
  low: { label: "Low", filled: 1, rule: "One source, or a model interpretation only." },
  moderate: {
    label: "Moderate",
    filled: 2,
    rule: "At least two observed sources from independent groups agree, and the newest is less than two years old.",
  },
  high: { label: "High", filled: 3, rule: "Moderate, plus reviewer confirmation or agreement with observed campaign results." },
  deterministic: { label: "Deterministic", filled: 4, rule: "Calculated by documented code from recorded inputs. Not an estimate." },
};
