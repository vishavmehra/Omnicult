import type { CreativeElement } from "./api";
import { isVideoClip } from "./video-api";

/** Mirrors the server's rule (app/media/remake.py): these kinds are never-change zones even when nobody locked them. */
export const NEVER_CHANGE_KINDS = new Set(["logo", "packshot", "product", "tagline"]);
export const TEXT_KINDS = new Set(["headline", "body", "cta", "caption", "tagline"]);
export const VOICE_KINDS = new Set(["voiceover", "caption"]);

export type LockedPart = { element: CreativeElement; source: "lock" | "brand_kit_never_change" };

export type VisualPlan = {
  plate: CreativeElement | null;
  locked: LockedPart[];
  texts: CreativeElement[];
  blocked: string | null;
};

export const isText = (e: CreativeElement) => typeof e.value === "string" && e.value.trim().length > 0;

/** What a visual remake of `plateId` would do to this version: the scene it replaces, the regions it keeps, the text it draws. */
export function planVisual(elements: CreativeElement[], plateId: string | null, locks: Set<string>): VisualPlan {
  const scenes = elements.filter((e) => e.kind === "scene" && !isVideoClip(e));
  const plate = scenes.find((e) => e.id === plateId) ?? scenes.find((e) => !locks.has(e.id)) ?? null;
  if (!plate) return { plate: null, locked: [], texts: [], blocked: "This version has no scene element to remake." };
  const group = elements.filter((e) => e.scene_id === plate.scene_id && e.id !== plate.id && e.bbox);
  const locked: LockedPart[] = [];
  const texts: CreativeElement[] = [];
  for (const e of group) {
    const byLock = locks.has(e.id) || e.locked;
    if (byLock || NEVER_CHANGE_KINDS.has(e.kind)) locked.push({ element: e, source: byLock ? "lock" : "brand_kit_never_change" });
    else if (TEXT_KINDS.has(e.kind) && isText(e)) texts.push(e);
  }
  return { plate, locked, texts, blocked: locks.has(plate.id) ? `${plate.id} is locked. Unlock it in Creative Studio to remake it.` : null };
}

/** The lines Remake: Sound speaks by default (mirrors the server): the version's voice-over script, else its captions. Never both,
 *  because a caption usually repeats a spoken line. */
export function defaultVoiceLines(elements: CreativeElement[]): CreativeElement[] {
  const script = elements.filter((e) => e.kind === "voiceover" && isText(e));
  return script.length ? script : elements.filter((e) => e.kind === "caption" && isText(e));
}

/** Pick a likely original and clean plate by file name, so the common case needs no clicks. */
export function suggestAssets<T extends { id: string; filename: string }>(images: T[]): { original?: string; plate?: string; reference?: string } {
  const lower = (a: T) => a.filename.toLowerCase();
  const plate = images.find((a) => /plate/.test(lower(a)));
  const reference = images.find((a) => /(pack|reference|tin)/.test(lower(a)) && a !== plate);
  const original = images.find((a) => a !== plate && a !== reference && /(key|visual|creative|original)/.test(lower(a))) ?? images.find((a) => a !== plate && a !== reference);
  return { original: original?.id, plate: plate?.id, reference: reference?.id };
}
