/** Readable aliases over the generated contract types for the Launch Room (features 36 and 37). */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type ScoreComparison = S["ScoreComparison"];
export type ScoreCard = S["ScoreCard"];
export type DimensionScore = S["DimensionScore"];
export type ScoreDimension = DimensionScore["dimension"];
export type ScoreCompareRequest = S["ScoreCompareRequest"];

export type ReadinessBoard = S["ReadinessBoard"];
export type RegionReadiness = S["RegionReadiness"];
export type VersionReadiness = S["VersionReadiness"];
export type ReadinessVerdict = S["ReadinessVerdict"];
export type ReadinessIssue = S["ReadinessIssue"];
export type ReadinessRules = S["ReadinessRules"];
export type ReadinessRequest = S["ReadinessRequest"];
export type VerdictValue = ReadinessVerdict["verdict"];

export type Approval = S["Approval"];
export type ApprovalCreate = S["ApprovalCreate"];
export type ApprovalDecision = ApprovalCreate["decision"];

export type VersionObservations = S["VersionObservations"];
export type Region = S["Region"];
export type VersionSummary = S["VersionSummary"];

/** A creative version that can be scored: a Creative Studio version node, or a campaign content version as a fallback. */
export type VersionOption = {
  id: string;
  label: string;
  source: "studio" | "content";
  regionCode: string | null;
  language: string | null;
};

export type MemberRole = "owner" | "editor" | "reviewer" | "viewer";

/** What the signed-in person may do in this workspace (backend: services.identity WRITE_ROLES and REVIEW_ROLES). */
export type Capabilities = {
  role: MemberRole | null;
  signedIn: boolean;
  canCompute: boolean;
  canDecide: boolean;
  /** One plain sentence that says why an action is unavailable, or null when nothing is blocked. */
  reason: string | null;
};
