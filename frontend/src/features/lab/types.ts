import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type RunKind = "quick_read" | "audience_study" | "risk_check";
export type PanelKind = Exclude<RunKind, "risk_check">;

export type QuickReadResult = S["QuickReadResult"];
export type AudienceStudyResult = S["AudienceStudyResult"];
export type RiskCheckResult = S["RiskCheckResult"];
export type RiskCheckFinding = S["RiskCheckFinding"];
export type RunSummary = S["AudienceRunSummary"];
export type RunError = NonNullable<QuickReadResult["error"]>;
export type RunProgress = NonNullable<QuickReadResult["progress"]>;
export type RunStatus = RunSummary["status"];
export type DataMode = RunSummary["mode"];

export type AskBody = S["AskPanelCreate"];
export type ThemeCount = S["ThemeCount"];
export type PanelQuestion = S["PanelQuestion"];
export type PanelAnswer = S["PanelAnswer"];
export type PanelParticipant = S["PanelParticipant"];
export type SamplingOptions = S["SamplingOptions"];
export type AdCodeIndex = S["AdCodeIndex"];
export type AdCodeEntry = S["AdCodeEntry"];

export type GroundingSummary = S["GroundingSummary"];
export type GroundingClaim = S["GroundingClaim"];
export type PointCount = S["PointCount"];
export type GroundedPoint = S["GroundedPoint"];
export type QuickReadParticipant = S["QuickReadParticipant"];
export type StudyParticipant = S["StudyParticipant"];
export type ReactionDistribution = S["ReactionDistribution"];
export type ReactionCategory = keyof ReactionDistribution["counts"];
export type RunMetadata = S["AudienceRunMetadata"];
export type DimensionResult = NonNullable<NonNullable<QuickReadResult["summary"]>["dimension_results"]["clarity"]>;
export type CreativeElement = S["CreativeElementIn-Output"];
export type CreativeElementInput = S["CreativeElementIn-Input"];
export type CreativeSceneInput = S["CreativeSceneIn-Input"];

export type QuickReadCreate = S["QuickReadCreate"];
export type AudienceStudyCreate = S["AudienceStudyCreate"];
export type RiskCheckCreate = S["RiskCheckCreate"];
export type SamplingPlan = S["SamplingPlan"];
export type SubgroupFilter = S["SubgroupFilter"];

export type FindingStatus = RiskCheckFinding["status"];
export type Severity = RiskCheckFinding["severity"];
export type RiskCategory = RiskCheckFinding["category"];

export type AnyResult = QuickReadResult | AudienceStudyResult | RiskCheckResult;

export const ACTIVE_STATUSES: readonly RunStatus[] = ["queued", "running"];
export const USABLE_STATUSES: readonly RunStatus[] = ["completed", "partial"];
export const isActive = (s: RunStatus) => ACTIVE_STATUSES.includes(s);
export const isUsable = (s: RunStatus) => USABLE_STATUSES.includes(s);
