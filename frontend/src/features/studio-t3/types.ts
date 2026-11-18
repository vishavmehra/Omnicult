/** Readable aliases over the generated contract types for Creative Studio Tier 3 (Format Fit, Claim Guard, Script Check). */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type FormatFitCatalogue = S["FormatFitCatalogue"];
export type FormatFitFormat = S["FormatFitFormat"];
export type FormatFitPlans = S["FormatFitPlans"];
export type FormatFitPlan = S["FormatFitPlan"];
export type FormatFitStrategyPlan = S["FormatFitStrategyPlan"];
export type FormatFitElement = S["FormatFitElement"];
export type FormatFitIssue = S["FormatFitIssue"];
export type FormatFitCutdown = S["FormatFitCutdown"];
export type FormatFitOutput = S["FormatFitOutput"];
export type FitStrategy = FormatFitStrategyPlan["strategy"];

export type ScriptReport = S["ScriptReport"];
export type ScriptReportElement = S["ScriptReportElement"];
export type ScriptReportIssue = S["ScriptReportIssue"];

export type ClaimGuardCheck = S["ClaimGuardCheck"];
export type ClaimGuardCheckSummary = S["ClaimGuardCheckSummary"];
export type ClaimGuardFinding = S["ClaimGuardFinding"];
export type ClaimKind = ClaimGuardFinding["kind"];
export type ReviewDecision = S["ClaimGuardReviewRequest"]["decision"];
