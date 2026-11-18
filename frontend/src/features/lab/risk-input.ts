import type { components } from "@/lib/api/schema";

import type { CreativeElementInput, CreativeSceneInput } from "./types";

type StudioElement = components["schemas"]["VersionNode"]["elements"][number];
type XRayScene = components["schemas"]["Scene"];

/** Risk Check accepts 60 elements and 40 scenes; copy comes first so the lines a regulator would read are never the ones cut. */
export const MAX_ELEMENTS = 60;
export const MAX_SCENES = 40;
const COPY_FIRST = ["headline", "body", "cta", "tagline", "caption", "voiceover"];

export function buildElements(elements: StudioElement[]): { elements: CreativeElementInput[]; omitted: number } {
  const rank = (k: string) => {
    const i = COPY_FIRST.indexOf(k);
    return i === -1 ? COPY_FIRST.length : i;
  };
  const ordered = [...elements].sort((a, b) => rank(a.kind) - rank(b.kind));
  const sent = ordered.slice(0, MAX_ELEMENTS).map((e) => ({
    id: e.id,
    kind: e.kind,
    value: e.value,
    language: e.language ?? null,
    script: e.script ?? null,
    bbox: e.bbox ?? null,
    scene_id: e.scene_id ?? null,
    locked: e.locked,
  }));
  return { elements: sent, omitted: Math.max(0, elements.length - MAX_ELEMENTS) };
}

/** Scenes the elements point at. A time range is added only where an X-Ray scene carries the same id; the rest stay untimed. */
export function buildScenes(elements: CreativeElementInput[], xray: XRayScene[] | undefined): { scenes: CreativeSceneInput[]; timed: number } {
  const ids = [...new Set(elements.map((e) => e.scene_id).filter((s): s is string => Boolean(s)))].slice(0, MAX_SCENES);
  const byId = new Map((xray ?? []).map((s) => [s.anchor.scene_id ?? s.id, s]));
  let timed = 0;
  const scenes = ids.map((id) => {
    const hit = byId.get(id);
    if (hit) timed += 1;
    return { id, start_ms: hit?.start_ms ?? null, end_ms: hit?.end_ms ?? null, summary: hit?.setting?.slice(0, 300) ?? null };
  });
  return { scenes, timed };
}
