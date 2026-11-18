/** Readable aliases over the generated contract types for the Voice Director. Regenerate schema.d.ts with `npm run gen:api`. */
import type { components } from "@/lib/api/schema";

type S = components["schemas"];

export type DirectPlan = S["DirectPlan"];
export type DirectStep = S["DirectStep"];
export type DirectStepKind = DirectStep["kind"];
export type DirectTranscript = S["DirectTranscript"];
export type DirectWorkspace = NonNullable<DirectStep["workspace"]>;
