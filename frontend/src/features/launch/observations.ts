/**
 * Observation inputs for the Launch Room. Scores and verdicts are computed from typed observations (Quick Read counts,
 * Risk Check findings, transcreation checks, reference grounding, objective checks, the Evidence Meter reading). Today the
 * client supplies them; `gather.ts` fills what Omnicult can already read. A group that is absent stays absent: the rules
 * report it as missing and never default it to zero.
 *
 * The draft keeps numbers as strings so a half-typed field is not rewritten; `toObservations` converts and validates.
 */
import type { VersionObservations } from "./types";

export const GROUPS = ["quick_read", "risk_check", "transcreation", "references", "objectives", "evidence_meter"] as const;
export type GroupKey = (typeof GROUPS)[number];

export const GROUP_LABEL: Record<GroupKey, string> = {
  quick_read: "Quick Read",
  risk_check: "Risk Check",
  transcreation: "Transcreation checks",
  references: "Reference grounding",
  objectives: "Objective checks",
  evidence_meter: "Evidence Meter",
};

/** What a missing group costs, taken from the rules in backend/app/analytics (scoring_v2 A1, readiness FX12 to FX14). */
export const MISSING_EFFECT: Record<GroupKey, string> = {
  quick_read: "Message clarity and Cultural relevance are not assessed, and rule FX13 holds the verdict at Fix.",
  risk_check: "Sensitivity risk is not assessed (an unrun Risk Check is not “no risk”), and rule FX14 holds the verdict at Fix.",
  transcreation: "Brand fidelity is not assessed, and the back-translation check on Message clarity is skipped.",
  references: "Cultural relevance rests on the synthetic panel alone; reference grounding is skipped.",
  objectives: "Objective consistency is not assessed.",
  evidence_meter: "Evidence strength for the region is unknown, and rule FX12 holds the verdict at Fix.",
};

export type Origin = { kind: "entered" | "gathered"; source: string | null; at: string };
export type GroupState = { state: "missing" } | { state: "entered"; at: string } | { state: "gathered"; source: string; at: string };

export type QuickDraft = { respondents: string; understood: string; confused: string; positive: string; negative: string; relevant: string; concerned: string };
export type FindingDraft = { key: string; id: string; severity: "high" | "medium" | "low"; status: "open" | "resolved" | "dismissed"; blocks_go: boolean; summary: string };
export type TranscreationDraft = { lines_checked: string; glossary_violation_lines: string; prohibited_term_lines: string; meaning_preserved_lines: string; script_error_lines: string };
export type ReferencesDraft = { references_checked: string; references_supported: string };
export type ObjectiveDraft = { key: string; statement: string; status: "met" | "partly_met" | "not_met"; primary: boolean };
export type MeterDraft = { strength: "weak" | "partial" | "solid"; claims: string; supported_claims: string; open_conflicts: string; stale_claims: string };
export type ConflictDraft = { key: string; conflict_id: string; summary: string; relied_on: boolean; status: "open" | "review_requested" | "resolved" };

export type Draft = {
  quick_read: QuickDraft | null;
  risk_check: FindingDraft[] | null; // null: not run. [] : ran and found nothing.
  transcreation: TranscreationDraft | null;
  references: ReferencesDraft | null;
  objectives: ObjectiveDraft[] | null;
  evidence_meter: MeterDraft | null;
  open_conflicts: ConflictDraft[];
  provenance: { model_id: string; prompt_version: string; criteria_version: string; evidence_snapshot: string };
  origins: Partial<Record<GroupKey, Origin>>;
};

export const emptyDraft = (): Draft => ({
  quick_read: null,
  risk_check: null,
  transcreation: null,
  references: null,
  objectives: null,
  evidence_meter: null,
  open_conflicts: [],
  provenance: { model_id: "", prompt_version: "", criteria_version: "", evidence_snapshot: "" },
  origins: {},
});

export const newKey = () => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Math.random()).slice(2));

export const blank = {
  quick_read: (): QuickDraft => ({ respondents: "", understood: "", confused: "", positive: "", negative: "", relevant: "", concerned: "" }),
  transcreation: (): TranscreationDraft => ({ lines_checked: "", glossary_violation_lines: "0", prohibited_term_lines: "0", meaning_preserved_lines: "", script_error_lines: "0" }),
  references: (): ReferencesDraft => ({ references_checked: "", references_supported: "" }),
  meter: (): MeterDraft => ({ strength: "partial", claims: "0", supported_claims: "0", open_conflicts: "0", stale_claims: "0" }),
  finding: (n: number): FindingDraft => ({ key: newKey(), id: `F${n}`, severity: "medium", status: "open", blocks_go: false, summary: "" }),
  objective: (): ObjectiveDraft => ({ key: newKey(), statement: "", status: "met", primary: false }),
  conflict: (): ConflictDraft => ({ key: newKey(), conflict_id: newKey(), summary: "", relied_on: false, status: "open" }),
};

export function groupState(d: Draft, key: GroupKey): GroupState {
  if (d[key] === null) return { state: "missing" };
  const origin = d.origins[key];
  if (origin?.kind === "gathered") return { state: "gathered", source: origin.source ?? "Omnicult", at: origin.at };
  return { state: "entered", at: origin?.at ?? "" };
}

export const missingGroups = (d: Draft): GroupKey[] => GROUPS.filter((g) => d[g] === null);

/** Rewrites one group and records that a person entered or edited it (an edit to gathered values ends the "gathered" claim). */
export function withGroup<K extends GroupKey>(d: Draft, key: K, value: Draft[K], origin?: Origin): Draft {
  const origins = { ...d.origins };
  if (value === null) delete origins[key];
  else origins[key] = origin ?? { kind: "entered", source: null, at: new Date().toISOString() };
  return { ...d, [key]: value, origins };
}

// --- conversion and validation ---------------------------------------------------------------------

type Problems = Partial<Record<GroupKey | "open_conflicts", string>>;

function count(text: string, min = 0): number | null {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return null;
  const n = Number(t);
  return n >= min ? n : null;
}

/** The request body observations and a plain-language problem per group that cannot be sent as typed. */
export function toObservations(d: Draft): { value: VersionObservations; problems: Problems } {
  const problems: Problems = {};
  const value: VersionObservations = { provenance: { run_ids: [] }, objective_checks: [], open_conflicts: [] };

  const p = d.provenance;
  for (const k of ["model_id", "prompt_version", "criteria_version", "evidence_snapshot"] as const) {
    if (p[k].trim()) value.provenance[k] = p[k].trim().slice(0, 64);
  }

  if (d.quick_read) {
    const q = d.quick_read;
    const n = count(q.respondents, 1);
    const c = { u: count(q.understood), f: count(q.confused), p: count(q.positive), g: count(q.negative), r: count(q.relevant), k: count(q.concerned) };
    if (n === null || n > 2000) problems.quick_read = "Respondents must be a whole number from 1 to 2000.";
    else if (Object.values(c).some((x) => x === null)) problems.quick_read = "Every count must be a whole number, 0 or more.";
    else if (Object.values(c).some((x) => x! > n)) problems.quick_read = "A count cannot exceed the number of respondents.";
    else if (c.u! + c.f! > n) problems.quick_read = "Understood plus confused cannot exceed the number of respondents.";
    else if (c.p! + c.g! > n) problems.quick_read = "Positive plus negative cannot exceed the number of respondents.";
    else value.quick_read = { respondents: n, understood: c.u!, confused: c.f!, positive: c.p!, negative: c.g!, relevant: c.r!, concerned: c.k!, synthetic: true, evidence_ids: [] };
  }

  if (d.risk_check) {
    const ids = d.risk_check.map((f) => f.id.trim());
    if (d.risk_check.some((f) => !f.id.trim() || !f.summary.trim())) problems.risk_check = "Every finding needs an id and a summary.";
    else if (new Set(ids).size !== ids.length) problems.risk_check = "Finding ids must be unique.";
    else {
      value.risk_check = {
        findings: d.risk_check.map((f) => ({
          id: f.id.trim(), severity: f.severity, category: "other", status: f.status, blocks_go: f.blocks_go, source: "model_assessment", summary: f.summary.trim(), claim_ids: [],
        })),
      };
    }
  }

  if (d.transcreation) {
    const t = d.transcreation;
    const lines = count(t.lines_checked, 1);
    const viol = count(t.glossary_violation_lines);
    const proh = count(t.prohibited_term_lines);
    const script = count(t.script_error_lines);
    const kept = t.meaning_preserved_lines.trim() === "" ? undefined : count(t.meaning_preserved_lines);
    if (lines === null || lines > 500) problems.transcreation = "Lines checked must be a whole number from 1 to 500.";
    else if (viol === null || proh === null || script === null || kept === null) problems.transcreation = "Every count must be a whole number, 0 or more.";
    else if (viol > lines || script > lines || (kept ?? 0) > lines) problems.transcreation = "A count cannot exceed the lines checked.";
    else if (proh > viol) problems.transcreation = "Prohibited-term lines are part of the violation lines, so they cannot exceed them.";
    else value.transcreation = { lines_checked: lines, glossary_violation_lines: viol, prohibited_term_lines: proh, meaning_preserved_lines: kept ?? null, script_error_lines: script };
  }

  if (d.references) {
    const checked = count(d.references.references_checked, 1);
    const supported = count(d.references.references_supported);
    if (checked === null || checked > 200) problems.references = "References checked must be a whole number from 1 to 200.";
    else if (supported === null) problems.references = "Supported references must be a whole number, 0 or more.";
    else if (supported > checked) problems.references = "Supported references cannot exceed references checked.";
    else value.references = { references_checked: checked, references_supported: supported };
  }

  if (d.objectives) {
    if (d.objectives.length === 0) problems.objectives = "Add at least one objective, or remove this group.";
    else if (d.objectives.some((o) => !o.statement.trim())) problems.objectives = "Every objective needs a statement.";
    else value.objective_checks = d.objectives.map((o) => ({ id: o.key.slice(0, 12), statement: o.statement.trim(), status: o.status, primary: o.primary }));
  }

  if (d.evidence_meter) {
    const m = d.evidence_meter;
    const nums = [count(m.claims), count(m.supported_claims), count(m.open_conflicts), count(m.stale_claims)];
    if (nums.some((x) => x === null)) problems.evidence_meter = "Every count must be a whole number, 0 or more.";
    else value.evidence_meter = { strength: m.strength, claims: nums[0]!, supported_claims: nums[1]!, open_conflicts: nums[2]!, stale_claims: nums[3]! };
  }

  if (d.open_conflicts.some((c) => !c.summary.trim())) problems.open_conflicts = "Every conflict needs a one-line summary.";
  else value.open_conflicts = d.open_conflicts.map((c) => ({ conflict_id: c.conflict_id, claim_ids: [], relied_on: c.relied_on, status: c.status, summary: c.summary.trim() }));

  return { value, problems };
}

// --- persistence (a convenience only: the server stores verdicts, not drafts) ---------------------------

const storageKey = (campaignId: string) => `omnicult.launch.inputs.v1.${campaignId}`;
export const draftKey = (versionId: string, regionCode: string) => `${versionId}|${regionCode}`;

export function loadDrafts(campaignId: string): Record<string, Draft> {
  try {
    const raw = typeof window === "undefined" ? null : window.localStorage.getItem(storageKey(campaignId));
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? (parsed as Record<string, Draft>) : {};
  } catch {
    return {};
  }
}

export function saveDrafts(campaignId: string, drafts: Record<string, Draft>) {
  try {
    window.localStorage.setItem(storageKey(campaignId), JSON.stringify(drafts));
  } catch {
    // Private windows and blocked storage: inputs simply are not remembered between visits.
  }
}
