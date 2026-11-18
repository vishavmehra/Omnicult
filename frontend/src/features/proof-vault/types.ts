import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type ProofReport = S["ProofReport"];
export type ProofReportSummary = S["ProofReportSummary"];
export type ProofExport = S["ProofExport"];
export type ProofSection = ProofReport["sections"][number];
export type SectionId = ProofSection["id"];
export type SectionOf<Id extends SectionId> = Extract<ProofSection, { id: Id }>;
export type KindLabel = S["KindLabel"];
export type ReportConflict = S["ReportConflict"];
export type RunHistoryItem = S["RunHistoryItem"];
export type RunHistoryDetail = S["RunHistoryDetail"];
export type RunHistoryTotals = S["RunHistoryTotals"];
export type DataHealth = S["DataHealth"];
export type SourceHealth = S["SourceHealth"];
export type RegionCoverage = S["RegionCoverage"];
export type ClaimView = S["ClaimView"];
export type SourceView = S["SourceView"];
export type Conflict = S["Conflict"];
export type Region = S["Region"];
export type GraphNode = S["GraphNode"];
export type SearchHit = S["SearchHit"];
export type ExportFormat = ProofExport["format"];

export type ProofView = "report" | "history" | "health" | "map" | "search";
