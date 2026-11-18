/** Readable aliases over the generated contract types for Creative Studio. Regenerate schema.d.ts with `npm run gen:api`. */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type VersionSummary = S["VersionSummary"];
export type VersionNode = S["VersionNode"];
export type CreativeElement = S["CreativeElement-Output"];
export type ElementKind = CreativeElement["kind"];
export type Operation = S["Operation"];
export type OperationKind = Operation["kind"];
export type OperationResult = S["OperationResult"];
export type Lock = S["Lock"];
export type Chip = S["Chip"];
export type ChipsGenerated = S["ChipsGenerated"];
export type VersionDiff = S["VersionDiff"];
export type Tone = S["Tone-Input"];
export type GlossaryTerm = S["GlossaryTerm"];
export type GlossaryTermCreate = S["GlossaryTermCreate"];
export type GlossaryTermUpdate = S["GlossaryTermUpdate"];
export type Region = S["Region"];
export type RegionLanguage = S["RegionLanguage"];
export type ClaimView = S["ClaimView"];

/**
 * One transcreated line as the operation stores it in `params.lines` (the engine's TranscreatedLine; the API types
 * `params` as an open object, so this shape is read defensively, see `asLines` in model.ts).
 */
export type LineResult = {
  element_id: string;
  kind: ElementKind;
  source_text: string;
  regional_copy: string;
  back_translation: string;
  explanation: string;
  claim_ids: string[];
  reasoning_type: "evidence_supported" | "model_interpretation";
  preserved_terms: string[];
  script_check: {
    expected_script: string;
    ok: boolean;
    dominant_script: string | null;
    shares: Record<string, number>;
    foreign_scripts: string[];
    min_share: number;
    message: string;
  };
  term_checks: {
    protected_preserved: boolean;
    missing_in_copy: string[];
    missing_in_back_translation: string[];
    prohibited_in_copy: string[];
    prohibited_in_back_translation: string[];
    preferred_translation_missing: string[];
    preserved_terms: string[];
  };
  passed: boolean;
  problems: string[];
};
