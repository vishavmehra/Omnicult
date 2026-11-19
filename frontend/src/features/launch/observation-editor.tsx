"use client";

import { Database, LoaderCircle, Plus, Trash2 } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { useCampaign } from "@/features/workspaces/campaign-context";
import { cn } from "@/lib/utils";

import { InputStatusChip, InputSummary, NativeSelect, NumField } from "./bits";
import { describeGroups, gatherInputs, type GatherResult } from "./gather";
import { useInputs } from "./inputs-store";
import {
  blank,
  groupState,
  GROUP_LABEL,
  MISSING_EFFECT,
  toObservations,
  withGroup,
  type Draft,
  type GroupKey,
} from "./observations";

function Group({
  group,
  draft,
  onAdd,
  onRemove,
  error,
  note,
  children,
}: {
  group: GroupKey;
  draft: Draft;
  onAdd(): void;
  onRemove(): void;
  error?: string;
  note?: ReactNode;
  children: ReactNode;
}) {
  const state = groupState(draft, group);
  const present = state.state !== "missing";
  const id = useId();
  return (
    <section aria-labelledby={id} className={cn("rounded-card border bg-surface", present ? "border-border" : "border-dashed border-border-strong/50 bg-surface-muted/50")}>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-3">
        <h3 id={id} className="text-[14px] font-semibold text-ink">
          {GROUP_LABEL[group]}
        </h3>
        <InputStatusChip state={state} />
        {state.state === "gathered" && <span className="type-meta">{state.source}</span>}
        <Button size="sm" variant={present ? "ghost" : "outline"} className="ml-auto" onClick={present ? onRemove : onAdd}>
          {present ? <Trash2 aria-hidden /> : <Plus aria-hidden />}
          {present ? "Remove" : "Add"}
          <span className="sr-only"> {GROUP_LABEL[group]}</span>
        </Button>
      </header>
      {present ? (
        <div className="space-y-3 border-t border-border px-4 py-3">
          {note}
          {children}
          {error && (
            <p role="alert" className="text-[12.5px] font-medium text-danger">
              {error}
            </p>
          )}
        </div>
      ) : (
        <p className="px-4 pb-3 text-[12.5px] text-ink-secondary">
          <span className="font-medium text-ink-body">If left out: </span>
          {MISSING_EFFECT[group]}
        </p>
      )}
    </section>
  );
}

const SEVERITIES = ["high", "medium", "low"] as const;
const FINDING_STATUS = ["open", "resolved", "dismissed"] as const;
const OBJECTIVE_STATUS: [string, string][] = [["met", "Met"], ["partly_met", "Partly met"], ["not_met", "Not met"]];

/**
 * The observation inputs for one version in one region: what the scoring and readiness rules read. Each group is present
 * or missing; a missing group is reported by the rules and never assumed. "Gather" fills what Omnicult can already read.
 */
export function ObservationEditor({ versionId, regionCode }: { versionId: string; regionCode: string }) {
  const { project } = useCampaign();
  const store = useInputs();
  const draft = store.get(versionId, regionCode);
  const set = (change: (d: Draft) => Draft) => store.update(versionId, regionCode, change);
  const { problems } = toObservations(draft);
  const uid = useId();
  const [gathering, setGathering] = useState(false);
  const [gather, setGather] = useState<GatherResult | null>(null);

  async function runGather() {
    setGathering(true);
    try {
      const result = await gatherInputs({ workspaceId: project.workspace_id, regionCode });
      const at = new Date().toISOString();
      set((d) => result.gathered.reduce((acc, g) => withGroup(acc, g.group, g.value, { kind: "gathered", source: g.source, at }), d));
      setGather(result);
    } finally {
      setGathering(false);
    }
  }

  const q = draft.quick_read;
  const m = draft.evidence_meter;
  const tr = draft.transcreation;
  const refs = draft.references;

  return (
    <div className="space-y-4">
      <div className="space-y-2 rounded-card border border-border bg-surface px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[13.5px] font-semibold text-ink">Inputs at a glance</p>
          <Button size="sm" variant="outline" onClick={() => void runGather()} disabled={gathering || !project.workspace_id}>
            {gathering ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <Database aria-hidden />}
            {gathering ? "Gathering…" : "Gather what Omnicult has"}
          </Button>
        </div>
        <InputSummary draft={draft} />
        <div aria-live="polite" className="space-y-1 text-[12.5px] text-ink-secondary">
          {gather && gather.gathered.length > 0 && (
            <p>
              <span className="font-medium text-ink">Gathered: </span>
              {gather.gathered.map((g) => g.source).join("; ")}.
            </p>
          )}
          {gather && gather.failed.map((f) => (
            <p key={f.group} className="text-danger">
              Could not read {GROUP_LABEL[f.group]}: {f.message}
            </p>
          ))}
          {gather ? (
            <p>
              Not gathered automatically yet: {describeGroups(gather.notGathered)}. Enter these here, or run them in Audience Lab and Creative Studio first.
            </p>
          ) : (
            <p>Today Omnicult can read the Evidence Meter for you; the other groups are entered by hand until automatic gathering is connected.</p>
          )}
        </div>
      </div>

      <Group
        group="quick_read"
        draft={draft}
        onAdd={() => set((d) => withGroup(d, "quick_read", blank.quick_read()))}
        onRemove={() => set((d) => withGroup(d, "quick_read", null))}
        error={problems.quick_read}
      >
        {q && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {(
              [
                ["respondents", "Respondents"],
                ["understood", "Understood the message"],
                ["confused", "Confused"],
                ["positive", "Positive"],
                ["negative", "Negative"],
                ["relevant", "Found it relevant"],
                ["concerned", "Raised a regional concern"],
              ] as const
            ).map(([key, label]) => (
              <NumField key={key} id={`${uid}-qr-${key}`} label={label} value={q[key]} onChange={(v) => set((d) => withGroup(d, "quick_read", { ...d.quick_read!, [key]: v }))} />
            ))}
          </div>
        )}
      </Group>

      <Group
        group="risk_check"
        draft={draft}
        onAdd={() => set((d) => withGroup(d, "risk_check", []))}
        onRemove={() => set((d) => withGroup(d, "risk_check", null))}
        error={problems.risk_check}
      >
        {draft.risk_check && (
          <div className="space-y-3">
            {draft.risk_check.length === 0 && (
              <p className="text-[12.5px] text-ink-secondary">
                A Risk Check that ran and found nothing. That is recorded as “ran, no findings”, which is not proof that no risk exists and is not legal review.
              </p>
            )}
            {draft.risk_check.map((f, i) => {
              const change = (patch: Partial<typeof f>) =>
                set((d) => withGroup(d, "risk_check", d.risk_check!.map((x) => (x.key === f.key ? { ...x, ...patch } : x))));
              return (
                <fieldset key={f.key} className="space-y-2 rounded-lg border border-border px-3 py-2.5">
                  <legend className="px-1 text-[12.5px] font-medium text-ink-secondary">Finding {i + 1}</legend>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-[6rem_8rem_8rem_auto]">
                    <div className="space-y-1">
                      <label htmlFor={`${uid}-f-${f.key}-id`} className="block text-[12.5px] text-ink-secondary">Id</label>
                      <Input id={`${uid}-f-${f.key}-id`} value={f.id} onChange={(e) => change({ id: e.target.value })} className="font-mono" />
                    </div>
                    <div className="space-y-1">
                      <label htmlFor={`${uid}-f-${f.key}-sev`} className="block text-[12.5px] text-ink-secondary">Severity</label>
                      <NativeSelect id={`${uid}-f-${f.key}-sev`} value={f.severity} onChange={(e) => change({ severity: e.target.value as typeof f.severity })}>
                        {SEVERITIES.map((s) => (
                          <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>
                        ))}
                      </NativeSelect>
                    </div>
                    <div className="space-y-1">
                      <label htmlFor={`${uid}-f-${f.key}-st`} className="block text-[12.5px] text-ink-secondary">Status</label>
                      <NativeSelect id={`${uid}-f-${f.key}-st`} value={f.status} onChange={(e) => change({ status: e.target.value as typeof f.status })}>
                        {FINDING_STATUS.map((s) => (
                          <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>
                        ))}
                      </NativeSelect>
                    </div>
                    <label className="flex items-center gap-2 self-end pb-1.5 text-[13px] text-ink-body">
                      <Checkbox checked={f.blocks_go} onCheckedChange={(v) => change({ blocks_go: v === true })} />
                      Blocks Go while open
                    </label>
                  </div>
                  <div className="flex items-end gap-2">
                    <div className="min-w-0 flex-1 space-y-1">
                      <label htmlFor={`${uid}-f-${f.key}-sum`} className="block text-[12.5px] text-ink-secondary">Summary</label>
                      <Input id={`${uid}-f-${f.key}-sum`} value={f.summary} maxLength={300} onChange={(e) => change({ summary: e.target.value })} />
                    </div>
                    <Button size="icon" variant="ghost" aria-label={`Remove finding ${i + 1}`} onClick={() => set((d) => withGroup(d, "risk_check", d.risk_check!.filter((x) => x.key !== f.key)))}>
                      <Trash2 aria-hidden />
                    </Button>
                  </div>
                </fieldset>
              );
            })}
            <Button size="sm" variant="outline" onClick={() => set((d) => withGroup(d, "risk_check", [...d.risk_check!, blank.finding(d.risk_check!.length + 1)]))}>
              <Plus aria-hidden />
              Add finding
            </Button>
          </div>
        )}
      </Group>

      <Group
        group="transcreation"
        draft={draft}
        onAdd={() => set((d) => withGroup(d, "transcreation", blank.transcreation()))}
        onRemove={() => set((d) => withGroup(d, "transcreation", null))}
        error={problems.transcreation}
        note={<p className="text-[12.5px] text-ink-secondary">Code-checked results for the regional copy: Brand Glossary compliance, back-translation and script.</p>}
      >
        {tr && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {(
              [
                ["lines_checked", "Lines checked"],
                ["glossary_violation_lines", "Lines breaking the glossary"],
                ["prohibited_term_lines", "Of those, with a prohibited term"],
                ["meaning_preserved_lines", "Lines whose back-translation kept the meaning"],
                ["script_error_lines", "Lines with a script error"],
              ] as const
            ).map(([key, label]) => (
              <NumField key={key} id={`${uid}-tc-${key}`} label={label} value={tr[key]} onChange={(v) => set((d) => withGroup(d, "transcreation", { ...d.transcreation!, [key]: v }))} />
            ))}
            <p className="col-span-2 self-end pb-1 text-[12px] text-ink-muted sm:col-span-1">Leave the back-translation count blank if it was not checked.</p>
          </div>
        )}
      </Group>

      <Group
        group="references"
        draft={draft}
        onAdd={() => set((d) => withGroup(d, "references", blank.references()))}
        onRemove={() => set((d) => withGroup(d, "references", null))}
        error={problems.references}
      >
        {refs && (
          <div className="grid grid-cols-2 gap-3">
            <NumField id={`${uid}-rf-checked`} label="Cultural references found in the creative" value={refs.references_checked} onChange={(v) => set((d) => withGroup(d, "references", { ...d.references!, references_checked: v }))} />
            <NumField id={`${uid}-rf-supported`} label="Of those, backed by an evidence claim" value={refs.references_supported} onChange={(v) => set((d) => withGroup(d, "references", { ...d.references!, references_supported: v }))} />
          </div>
        )}
      </Group>

      <Group
        group="objectives"
        draft={draft}
        onAdd={() => set((d) => withGroup(d, "objectives", [blank.objective()]))}
        onRemove={() => set((d) => withGroup(d, "objectives", null))}
        error={problems.objectives}
      >
        {draft.objectives && (
          <div className="space-y-3">
            {draft.objectives.map((o, i) => {
              const change = (patch: Partial<typeof o>) => set((d) => withGroup(d, "objectives", d.objectives!.map((x) => (x.key === o.key ? { ...x, ...patch } : x))));
              return (
                <fieldset key={o.key} className="space-y-2 rounded-lg border border-border px-3 py-2.5">
                  <legend className="px-1 text-[12.5px] font-medium text-ink-secondary">Objective {i + 1}</legend>
                  <div className="space-y-1">
                    <label htmlFor={`${uid}-o-${o.key}-s`} className="block text-[12.5px] text-ink-secondary">What the creative should achieve</label>
                    <Input id={`${uid}-o-${o.key}-s`} value={o.statement} maxLength={300} onChange={(e) => change({ statement: e.target.value })} />
                  </div>
                  <div className="flex flex-wrap items-end gap-3">
                    <div className="w-40 space-y-1">
                      <label htmlFor={`${uid}-o-${o.key}-st`} className="block text-[12.5px] text-ink-secondary">Does it serve it?</label>
                      <NativeSelect id={`${uid}-o-${o.key}-st`} value={o.status} onChange={(e) => change({ status: e.target.value as typeof o.status })}>
                        {OBJECTIVE_STATUS.map(([v, l]) => (
                          <option key={v} value={v}>{l}</option>
                        ))}
                      </NativeSelect>
                    </div>
                    <label className="flex items-center gap-2 pb-1.5 text-[13px] text-ink-body">
                      <Checkbox checked={o.primary} onCheckedChange={(v) => change({ primary: v === true })} />
                      Primary objective
                    </label>
                    <Button className="ml-auto" size="icon" variant="ghost" aria-label={`Remove objective ${i + 1}`} onClick={() => set((d) => withGroup(d, "objectives", d.objectives!.filter((x) => x.key !== o.key)))}>
                      <Trash2 aria-hidden />
                    </Button>
                  </div>
                </fieldset>
              );
            })}
            <Button size="sm" variant="outline" onClick={() => set((d) => withGroup(d, "objectives", [...d.objectives!, blank.objective()]))}>
              <Plus aria-hidden />
              Add objective
            </Button>
          </div>
        )}
      </Group>

      <Group
        group="evidence_meter"
        draft={draft}
        onAdd={() => set((d) => withGroup(d, "evidence_meter", blank.meter()))}
        onRemove={() => set((d) => withGroup(d, "evidence_meter", null))}
        error={problems.evidence_meter}
        note={<p className="text-[12.5px] text-ink-secondary">The region&rsquo;s Evidence Meter reading from Market Lens. Use “Gather what Omnicult has” above to read it instead of typing.</p>}
      >
        {m && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <div className="space-y-1">
              <label htmlFor={`${uid}-em-strength`} className="block text-[12.5px] text-ink-secondary">Strength</label>
              <NativeSelect id={`${uid}-em-strength`} value={m.strength} onChange={(e) => set((d) => withGroup(d, "evidence_meter", { ...d.evidence_meter!, strength: e.target.value as typeof m.strength }))}>
                <option value="weak">Weak</option>
                <option value="partial">Partial</option>
                <option value="solid">Solid</option>
              </NativeSelect>
            </div>
            {(
              [
                ["claims", "Claims"],
                ["supported_claims", "Supported claims"],
                ["open_conflicts", "Open conflicts"],
                ["stale_claims", "Stale claims"],
              ] as const
            ).map(([key, label]) => (
              <NumField key={key} id={`${uid}-em-${key}`} label={label} value={m[key]} onChange={(v) => set((d) => withGroup(d, "evidence_meter", { ...d.evidence_meter!, [key]: v }))} />
            ))}
          </div>
        )}
      </Group>

      <section aria-labelledby={`${uid}-conf`} className="rounded-card border border-border bg-surface">
        <header className="flex flex-wrap items-center gap-x-3 px-4 py-3">
          <h3 id={`${uid}-conf`} className="text-[14px] font-semibold text-ink">Open evidence conflicts</h3>
          <span className="type-meta">{draft.open_conflicts.length === 0 ? "None listed" : `${draft.open_conflicts.length} listed`}</span>
          <Button size="sm" variant="outline" className="ml-auto" onClick={() => set((d) => ({ ...d, open_conflicts: [...d.open_conflicts, blank.conflict()] }))}>
            <Plus aria-hidden />
            Add conflict
          </Button>
        </header>
        <div className="space-y-3 border-t border-border px-4 py-3">
          <p className="text-[12.5px] text-ink-secondary">Only conflicts listed here are counted. A conflict on a claim the creative relies on holds the verdict at Fix (rule FX3); an empty list means none were supplied, not that none exist.</p>
          {draft.open_conflicts.map((c, i) => {
            const change = (patch: Partial<typeof c>) => set((d) => ({ ...d, open_conflicts: d.open_conflicts.map((x) => (x.key === c.key ? { ...x, ...patch } : x)) }));
            return (
              <fieldset key={c.key} className="space-y-2 rounded-lg border border-border px-3 py-2.5">
                <legend className="px-1 text-[12.5px] font-medium text-ink-secondary">Conflict {i + 1}</legend>
                <div className="space-y-1">
                  <label htmlFor={`${uid}-c-${c.key}-s`} className="block text-[12.5px] text-ink-secondary">Summary</label>
                  <Input id={`${uid}-c-${c.key}-s`} value={c.summary} maxLength={300} onChange={(e) => change({ summary: e.target.value })} />
                </div>
                <div className="flex flex-wrap items-end gap-3">
                  <div className="w-44 space-y-1">
                    <label htmlFor={`${uid}-c-${c.key}-st`} className="block text-[12.5px] text-ink-secondary">State</label>
                    <NativeSelect id={`${uid}-c-${c.key}-st`} value={c.status} onChange={(e) => change({ status: e.target.value as typeof c.status })}>
                      <option value="open">Open</option>
                      <option value="review_requested">Review requested</option>
                      <option value="resolved">Resolved</option>
                    </NativeSelect>
                  </div>
                  <label className="flex items-center gap-2 pb-1.5 text-[13px] text-ink-body">
                    <Checkbox checked={c.relied_on} onCheckedChange={(v) => change({ relied_on: v === true })} />
                    The creative relies on one of these claims
                  </label>
                  <Button className="ml-auto" size="icon" variant="ghost" aria-label={`Remove conflict ${i + 1}`} onClick={() => set((d) => ({ ...d, open_conflicts: d.open_conflicts.filter((x) => x.key !== c.key) }))}>
                    <Trash2 aria-hidden />
                  </Button>
                </div>
              </fieldset>
            );
          })}
          {problems.open_conflicts && (
            <p role="alert" className="text-[12.5px] font-medium text-danger">{problems.open_conflicts}</p>
          )}
        </div>
      </section>

      <details className="rounded-card border border-border bg-surface px-4 py-3">
        <summary className="cursor-pointer text-[14px] font-semibold text-ink">Where these observations came from (optional)</summary>
        <div className="mt-3 space-y-3">
          <p className="text-[12.5px] text-ink-secondary">When compared versions differ in model, prompt version, criteria or evidence, the comparison says so and does not call the ranking like-for-like.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            {(
              [
                ["model_id", "Model"],
                ["prompt_version", "Prompt version"],
                ["criteria_version", "Evaluation criteria"],
                ["evidence_snapshot", "Evidence snapshot"],
              ] as const
            ).map(([key, label]) => (
              <div key={key} className="space-y-1">
                <label htmlFor={`${uid}-pv-${key}`} className="block text-[12.5px] text-ink-secondary">{label}</label>
                <Input id={`${uid}-pv-${key}`} maxLength={64} value={draft.provenance[key]} onChange={(e) => set((d) => ({ ...d, provenance: { ...d.provenance, [key]: e.target.value } }))} />
              </div>
            ))}
          </div>
        </div>
      </details>
    </div>
  );
}
