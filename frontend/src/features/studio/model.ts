/**
 * Pure helpers for Creative Studio: version numbering and the tree, lineage back to the original, pairing original and
 * adapted elements, and finding the back-translation that belongs to a line of copy. No React and no network here, so
 * `model.check.mjs` can exercise it with plain Node (type-only imports are erased).
 */
import type { CreativeElement, ElementKind, LineResult, Operation, OperationKind, Tone, VersionNode, VersionSummary } from "./types";

// ---------- vocabulary ----------

const TEXT_KINDS: ReadonlySet<ElementKind> = new Set(["headline", "body", "cta", "tagline", "voiceover", "caption"]);
/** The API only edits, transcreates and tweaks text elements; the other kinds can be locked and inspected. */
export const isTextKind = (kind: ElementKind) => TEXT_KINDS.has(kind);

export const KIND_LABEL: Record<ElementKind, string> = {
  headline: "Headline",
  body: "Body",
  cta: "Call to action",
  tagline: "Tagline",
  logo: "Logo",
  product: "Product",
  packshot: "Packshot",
  image_region: "Image region",
  scene: "Scene",
  voiceover: "Voice-over",
  music: "Music",
  caption: "Caption",
};

export const OPERATION_LABEL: Record<OperationKind, string> = {
  manual_edit: "Manual edit",
  replace_text: "Text replaced",
  transcreate: "Transcreate",
  apply_chip: "Tweak chip",
  swap_reference: "Reference swapped",
  change_setting: "Setting changed",
  tone_shift: "Tone shifted",
  restore: "Restore",
};

const SCRIPT_NAME: Record<string, string> = {
  Latn: "Latin",
  Deva: "Devanagari",
  Taml: "Tamil",
  Mlym: "Malayalam",
  Beng: "Bengali",
  Telu: "Telugu",
  Knda: "Kannada",
  Gujr: "Gujarati",
  Guru: "Gurmukhi",
  Orya: "Odia",
  Arab: "Arabic",
};
export const SCRIPT_CODES = Object.keys(SCRIPT_NAME);
export const scriptName = (code: string | null | undefined) => (code ? (SCRIPT_NAME[code] ?? code) : "unknown script");

export const TONE_DIALS: { key: keyof Tone; label: string; low: string; high: string }[] = [
  { key: "formality", label: "Formality", low: "Casual", high: "Formal" },
  { key: "code_mixing", label: "Code-mixing", low: "Pure language", high: "Mixed with English" },
  { key: "urban_rural", label: "Urban or rural", low: "Rural", high: "Urban" },
  { key: "playfulness", label: "Playfulness", low: "Serious", high: "Playful" },
  { key: "energy", label: "Energy", low: "Low", high: "High" },
];
export const DEFAULT_TONE: Tone = { formality: 50, code_mixing: 50, urban_rural: 50, playfulness: 50, energy: 50 };

/** The wording for a dial value, so a number never stands alone: "Formal, 80". */
export function dialWord(dial: (typeof TONE_DIALS)[number], value: number) {
  const word = value <= 30 ? dial.low : value >= 70 ? dial.high : "Balanced"; // the API's thresholds (app.studio.checks)
  return `${word}, ${value}`;
}

/** The estimate from the price table, never presented as billed spend. */
export function formatCost(usd: number | null | undefined) {
  if (usd === null || usd === undefined) return null;
  return `about $${usd < 0.01 ? usd.toFixed(4) : usd.toFixed(3)}`;
}

/** A value for display: copy as written, anything else (an asset reference, a descriptor) as compact JSON. */
export function elementText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  return JSON.stringify(value);
}

// ---------- the version tree ----------

const byTime = (a: VersionSummary, b: VersionSummary) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id);

/** Display numbers in creation order, so "v3" always means the third node saved in this campaign. */
export function numberVersions(versions: VersionSummary[]): Map<string, number> {
  return new Map([...versions].sort(byTime).map((v, i) => [v.id, i + 1]));
}

export type TreeRow = { version: VersionSummary; number: number; depth: number; branchStart: boolean };

/**
 * Depth-first rows. A node continues its parent's line unless the parent has several children: then each child opens a
 * branch one step to the right (two regions transcreated from the same original are two branches).
 */
export function buildTree(versions: VersionSummary[]): TreeRow[] {
  const numbers = numberVersions(versions);
  const ids = new Set(versions.map((v) => v.id));
  const children = new Map<string, VersionSummary[]>();
  const roots: VersionSummary[] = [];
  for (const v of [...versions].sort(byTime)) {
    if (v.parent_id && ids.has(v.parent_id)) children.set(v.parent_id, [...(children.get(v.parent_id) ?? []), v]);
    else roots.push(v);
  }
  const rows: TreeRow[] = [];
  const seen = new Set<string>();
  const walk = (v: VersionSummary, depth: number, branchStart: boolean) => {
    if (seen.has(v.id)) return;
    seen.add(v.id);
    rows.push({ version: v, number: numbers.get(v.id) ?? 0, depth, branchStart });
    const kids = children.get(v.id) ?? [];
    for (const kid of kids) walk(kid, kids.length > 1 ? depth + 1 : depth, kids.length > 1);
  };
  for (const root of roots) walk(root, 0, false);
  return rows;
}

/** The version, its parent, and so on up to the original (a node with no parent). */
export function lineage(versions: VersionSummary[], id: string): VersionSummary[] {
  const byId = new Map(versions.map((v) => [v.id, v]));
  const chain: VersionSummary[] = [];
  for (let cur = byId.get(id); cur && !chain.includes(cur); cur = cur.parent_id ? byId.get(cur.parent_id) : undefined) chain.push(cur);
  return chain;
}

/** The root of this version's line: the original the adaptation started from. */
export const originalOf = (versions: VersionSummary[], id: string) => lineage(versions, id).at(-1) ?? null;

/** Region and language of a node as one tag text: "IN-TN · ta", or null for an unlocalised original. */
export function placeTag(v: Pick<VersionSummary, "region_code" | "language">) {
  const parts = [v.region_code, v.language].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

// ---------- elements ----------

export type ElementPair = { id: string; kind: ElementKind; original: CreativeElement | null; current: CreativeElement | null };

/** Every element of the version, with the original's element of the same id. Elements only the original has come last. */
export function pairElements(original: VersionNode | null, current: VersionNode): ElementPair[] {
  const before = new Map((original?.elements ?? []).map((e) => [e.id, e]));
  const pairs: ElementPair[] = current.elements.map((e) => ({ id: e.id, kind: e.kind, original: before.get(e.id) ?? null, current: e }));
  const here = new Set(current.elements.map((e) => e.id));
  for (const e of original?.elements ?? []) if (!here.has(e.id)) pairs.push({ id: e.id, kind: e.kind, original: e, current: null });
  return pairs;
}

// ---------- transcreation lines ----------

function isLine(x: unknown): x is LineResult {
  if (typeof x !== "object" || x === null) return false;
  const l = x as Record<string, unknown>;
  return (
    typeof l.element_id === "string" &&
    typeof l.regional_copy === "string" &&
    typeof l.back_translation === "string" &&
    typeof l.script_check === "object" &&
    l.script_check !== null &&
    typeof l.term_checks === "object" &&
    l.term_checks !== null &&
    Array.isArray(l.problems)
  );
}

/** The lines a transcreate operation stored, or none when `params` has another shape. */
export function asLines(params: Operation["params"] | null | undefined): LineResult[] {
  const raw = (params as { lines?: unknown } | null | undefined)?.lines;
  return Array.isArray(raw) ? raw.filter(isLine) : [];
}

export type LineMatch = { line: LineResult; operation: Operation; state: "current" | "edited" };

/**
 * The transcreated line behind an element's current wording. Walks from the selected version back to the original:
 * "current" when the element still says exactly what the line says; "edited" when a later edit changed it, so the
 * back-translation belongs to the earlier wording; null when nothing in the line of versions was transcreated.
 */
export function lineFor(ops: Operation[], chain: VersionSummary[], elementId: string, currentValue: string): LineMatch | null {
  let earlier: LineMatch | null = null;
  for (const v of chain) {
    const op = ops.find((o) => o.kind === "transcreate" && o.status === "applied" && o.result_version_id === v.id);
    const line = asLines(op?.params).find((l) => l.element_id === elementId && l.passed);
    if (!op || !line) continue;
    if (line.regional_copy === currentValue) return { line, operation: op, state: "current" };
    earlier ??= { line, operation: op, state: "edited" };
  }
  return earlier;
}

/** How many lines of a transcreation were applied and how many were kept back for review. */
export function lineCounts(lines: LineResult[]) {
  const passed = lines.filter((l) => l.passed).length;
  return { passed, review: lines.length - passed };
}

/** Problems of a line in plain sentences (the engine's own `problems`, then anything the checks flag that it did not say). */
export function lineProblems(line: LineResult): string[] {
  return line.problems.length ? line.problems : line.passed ? [] : ["A check failed."];
}
