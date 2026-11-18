/** Readable aliases over the generated contract types. Regenerate schema.d.ts with `npm run gen:api`. */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Market = Schemas["Market"];
export type DataMode = Schemas["Project"]["mode"];
export type ErrorResponse = Schemas["ErrorResponse"];
export type Readiness = Schemas["Readiness"];

export type Project = Schemas["Project"];
export type ProjectSummary = Schemas["ProjectSummary"];
export type ProjectCreate = Schemas["ProjectCreate"];
export type ProjectUpdate = Schemas["ProjectUpdate"];
export type Brand = Schemas["Brand"];

export type Campaign = Schemas["Campaign"];
export type CampaignCreate = Schemas["CampaignCreate"];
export type CampaignUpdate = Schemas["CampaignUpdate"];
export type CampaignContent = Schemas["CampaignContent-Output"];
export type CampaignContentInput = Schemas["CampaignContent-Input"];
export type ContentVersion = Schemas["ContentVersion"];
export type EvaluationCriteria = Schemas["EvaluationCriteria"];

export type Run = Schemas["Run"];
export type RunStatus = Schemas["Run"]["status"];
export type RunType = Schemas["Run"]["run_type"];
export type RunAccepted = Schemas["RunAccepted"];
export type RunMetadata = Schemas["RunMetadata"];
export type StepTrace = Schemas["StepTrace"];

export type EvidenceRecord = Schemas["EvidenceRecord"];
export type ConfidenceLabel = "insufficient" | "limited" | "moderate";
export type EvidenceType = Schemas["EvidenceRecord"]["evidence_type"];
export type ClaimType = Schemas["EvidenceRecord"]["claim_type"];
export type RetrievalMode = Schemas["EvidenceRecord"]["retrieval_mode"];


export type DimensionResult = Schemas["DimensionResult"];




// v2 (contracts/README §13)
export type ReadinessCapabilities = Schemas["ReadinessCapabilities"];
export type BrandUpdate = Schemas["BrandUpdate"];
export type BrandExample = Schemas["BrandExample-Output"];
export type BrandExampleInput = Schemas["BrandExample-Input"];






export type Asset = Schemas["Asset"];
export type VisionStatus = Schemas["VisionStatus"];
export type VisualObservation = Schemas["VisualObservation"];

export type EvidenceGraph = Schemas["EvidenceGraph"];
export type GraphNode = Schemas["GraphNode"];
export type GraphEdge = Schemas["GraphEdge"];
export type GraphRef = Schemas["GraphRef"];

export type SearchResults = Schemas["SearchResults"];
export type SearchHit = Schemas["SearchHit"];

// v3 (contracts/README §14): population studies, social simulation, graph views
export type InterviewAnswer = Schemas["InterviewAnswer"];
export type ReactionDistribution = Schemas["ReactionDistribution"];
export type ThemeCount = Schemas["ThemeCount"];
