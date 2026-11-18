import type { GroundingClaim, PointCount, QuickReadParticipant, ReactionCategory, ReactionDistribution, RiskCheckFinding, Severity } from "./types";

/** Pure helpers: no React, no icons, no browser APIs, so they can be checked with plain node (see logic.check.ts). */

export function formatMs(ms: number) {
  return `${(ms / 1000).toFixed(1)} s`;
}

/** [x, y, w, h] normalised to the frame, read as percentages of the frame (not a statistic). */
export function formatBox(box: number[]) {
  const [x, y, w, h] = box.map((n) => Math.round(n * 100));
  return `${w}% wide, ${h}% high, ${x}% from the left and ${y}% from the top`;
}

export function pluralise(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

/** Reaction tallies by one participant dimension, counted in the browser from the stored responses (no model, no estimate). */
export function tallyBy(
  participants: QuickReadParticipant[],
  pick: (p: QuickReadParticipant) => { value: string; label: string },
): { value: string; label: string; counts: Record<ReactionCategory, number>; total: number }[] {
  const out = new Map<string, { value: string; label: string; counts: Record<ReactionCategory, number>; total: number }>();
  for (const p of participants) {
    if (!p.response) continue;
    const { value, label } = pick(p);
    const row = out.get(value) ?? { value, label, counts: { positive: 0, mixed: 0, neutral: 0, negative: 0, confused: 0 }, total: 0 };
    row.counts[p.response.sentiment] += 1;
    row.total += 1;
    out.set(value, row);
  }
  return [...out.values()].sort((a, b) => b.total - a.total || a.label.localeCompare(b.label));
}

export type Counts = ReactionDistribution["counts"];

/** True when the reactions are split: at least two categories hold a participant, and the leading one is under 70% of the denominator. */
export function isSplit(d: ReactionDistribution) {
  const filled = Object.values(d.counts).filter((n) => n > 0).length;
  const top = Math.max(...Object.values(d.counts));
  return d.denominator > 0 && filled >= 2 && top / d.denominator < 0.7;
}

/**
 * A statement is claim-supported only when it cites at least one OBSERVED or CALCULATED claim that exists in the claims the
 * run was given. The API labels this already; the screen checks again so a mislabelled point can never read as grounded.
 */
export function citedClaims(point: Pick<PointCount, "claim_ids">, claims: GroundingClaim[]) {
  const byId = new Map(claims.map((c) => [c.id, c]));
  return point.claim_ids.map((id) => byId.get(id)).filter((c): c is GroundingClaim => Boolean(c));
}
export function isGrounded(point: Pick<PointCount, "basis" | "claim_ids">, claims: GroundingClaim[]) {
  return point.basis === "claim_supported" && citedClaims(point, claims).some((c) => c.kind === "observed" || c.kind === "calculated");
}


/** `lang` for a piece of text: the participant's language only when the text is actually in an Indic script, so English stays English. */
export function langFor(text: string | null | undefined, code: string): string | undefined {
  return text && /[\u0900-\u0DFF]/.test(text) ? code : undefined;
}

/** "Scene mh-s5, 19.9 s to 29.4 s" or "Not tied to a scene": where in the creative a finding points. */
export function describeAnchor(a: { scene_id?: string | null; start_ms?: number | null; end_ms?: number | null; bbox?: number[] | null }) {
  const time =
    a.start_ms != null && a.end_ms != null ? `${formatMs(a.start_ms)} to ${formatMs(a.end_ms)}` : a.start_ms != null ? `from ${formatMs(a.start_ms)}` : null;
  return { scene: a.scene_id ?? null, time, box: a.bbox ? formatBox(a.bbox) : null };
}

export const SEVERITY_RANK: Record<Severity, number> = { high: 3, medium: 2, low: 1 };

/** Findings by computed severity, high first; within a level, the ones that block Go first, then the order the check produced them. */
export function sortFindings(findings: RiskCheckFinding[]): RiskCheckFinding[] {
  return [...findings].sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || Number(b.blocks_go) - Number(a.blocks_go) || a.ordinal - b.ordinal);
}
