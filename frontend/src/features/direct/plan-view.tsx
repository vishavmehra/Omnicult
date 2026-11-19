"use client";

import { ArrowRight, ArrowUpRight, Bot, Check, CircleSlash, Lock, LockOpen, MessageSquareText, TriangleAlert, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Tag } from "@/components/evidence/badges";
import { WORKSPACES, workspaceHref } from "@/components/shell/workspaces";
import { Button, buttonVariants } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { formatCost } from "@/features/studio/model";
import { MutationError, Status, useStudio } from "@/features/studio/parts";
import type { CreativeElement } from "@/features/studio/types";
import { cn } from "@/lib/utils";

import type { DirectPlan, DirectStep } from "./types";

const DEMO_NOTE = "Demo fixture output, not a live model response.";
/** Steps a person can (re)confirm: refused and failed ones changed nothing, so they may be tried again. */
const CONFIRMABLE = new Set<DirectStep["status"]>(["proposed", "refused", "failed"]);

const STATUS_WORD: Record<DirectPlan["status"], string> = {
  proposed: "Not applied yet",
  partial: "Partly applied",
  applied: "Applied",
  refused: "Nothing applied",
  unsupported: "Cannot be planned",
};

function StepStatus({ step }: { step: DirectStep }) {
  switch (step.status) {
    case "applied":
      return <Status tone="success" Icon={Check}>Applied</Status>;
    case "blocked":
      return <Status tone="warning" Icon={step.blocked?.code === "LOCKED" ? Lock : CircleSlash}>Blocked by code</Status>;
    case "refused":
      return <Status tone="warning" Icon={Lock}>Refused, nothing changed</Status>;
    case "failed":
      return <Status tone="danger" Icon={TriangleAlert}>Failed, nothing changed</Status>;
    case "applying":
      return <Status tone="neutral" Icon={ArrowRight}>Applying…</Status>;
    default:
      return step.needs_confirmation ? <Status tone="neutral" Icon={ArrowRight}>Waiting for you</Status> : null;
  }
}

/** What confirming the step does, in words: the person decides knowing it. */
function effectOf(step: DirectStep): string | null {
  switch (step.kind) {
    case "edit_element":
    case "apply_chip":
    case "restore_version":
      return "Makes a new version; the current one stays as it is.";
    case "transcreate":
      return "Starts a transcreation run (a model call); its version appears when the run finishes.";
    case "propose_chips":
      return "Calls the model for suggestions; nothing changes until you apply a chip.";
    case "lock_element":
    case "unlock_element":
      return "Locks hold in every version, so no version is made.";
    default:
      return null;
  }
}

function Change({ step, lang }: { step: DirectStep; lang?: string }) {
  if (!step.after) return null;
  return (
    <div className="grid gap-1.5 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:items-start sm:gap-3">
      <p lang={lang} className="rounded-md bg-surface-muted/70 px-2.5 py-1.5 text-[13.5px] leading-snug text-ink-secondary">
        <span className="type-meta block">Now</span>
        {step.before}
      </p>
      <ArrowRight aria-hidden className="mt-4 hidden size-4 text-ink-muted sm:block" />
      <p lang={lang} className="rounded-md bg-surface-muted/70 px-2.5 py-1.5 text-[13.5px] leading-snug text-ink">
        <span className="type-meta flex items-center gap-1.5">
          Proposed
          <Tag className="border-dashed border-ink-secondary/50 bg-surface text-ink-secondary" title="Written by a model. Not an observed fact.">
            <Bot aria-hidden />
            AI proposal
          </Tag>
        </span>
        {step.after}
      </p>
    </div>
  );
}

function Outcome({ step, numbers, onOpenVersion, onShowRun }: { step: DirectStep; numbers: Map<string, number>; onOpenVersion(id: string): void; onShowRun(runId: string): void }) {
  const result = step.result;
  if (!result) return null;
  const made = result.version_id ? numbers.get(result.version_id) : undefined;
  return (
    <div className="space-y-2">
      <p className="text-[13px] text-ink-body">{result.message}</p>
      <div className="flex flex-wrap gap-2">
        {result.version_id && (
          <Button size="sm" variant="outline" onClick={() => onOpenVersion(result.version_id!)}>
            Open {made ? `v${made}` : "the new version"}
          </Button>
        )}
        {result.chip_version_id && result.chip_ids.length > 0 && (
          <Button size="sm" variant="outline" onClick={() => onOpenVersion(result.chip_version_id!)}>
            Review the chips
          </Button>
        )}
        {result.run_id && (
          <Button size="sm" variant="outline" onClick={() => onShowRun(result.run_id!)}>
            Follow the transcreation
          </Button>
        )}
      </div>
    </div>
  );
}

function StepRow({
  step,
  checked,
  onToggle,
  elements,
  numbers,
  onOpenVersion,
  onShowRun,
}: {
  step: DirectStep;
  checked: boolean;
  onToggle(on: boolean): void;
  elements: CreativeElement[];
  numbers: Map<string, number>;
  onOpenVersion(id: string): void;
  onShowRun(runId: string): void;
}) {
  const { campaignId } = useStudio();
  const selectable = step.needs_confirmation && CONFIRMABLE.has(step.status);
  const effect = effectOf(step);
  const lang = elements.find((e) => e.id === step.element_id)?.language ?? undefined;
  const LockIcon: LucideIcon | null = step.kind === "lock_element" ? Lock : step.kind === "unlock_element" ? LockOpen : null;
  const id = `direct-step-${step.id}`;
  return (
    <li className="flex gap-3 px-4 py-3">
      <div className="flex w-5 shrink-0 justify-center pt-0.5">
        {selectable ? (
          <Checkbox id={id} checked={checked} onCheckedChange={(on) => onToggle(on === true)} aria-labelledby={`${id}-title`} />
        ) : step.status === "applied" ? (
          <Check aria-hidden className="mt-0.5 size-4 text-success" />
        ) : step.status === "blocked" ? (
          <CircleSlash aria-hidden className="mt-0.5 size-4 text-warning" />
        ) : (
          <ArrowUpRight aria-hidden className="mt-0.5 size-4 text-ink-muted" />
        )}
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
          <label htmlFor={selectable ? id : undefined} id={`${id}-title`} className="flex min-w-0 items-center gap-1.5 text-[14px] font-semibold text-ink">
            {LockIcon && <LockIcon aria-hidden className="size-3.5 shrink-0 text-ink-secondary" />}
            {step.title}
          </label>
          <StepStatus step={step} />
        </div>
        {step.status === "blocked" && step.blocked && <p className="text-[13px] text-ink-body">{step.blocked.message}</p>}
        <Change step={step} lang={lang} />
        {step.status !== "blocked" && step.status !== "applied" && effect && step.needs_confirmation && <p className="type-meta">{effect}</p>}
        {step.rationale && step.status !== "applied" && <p className="max-w-[68ch] text-[13px] text-ink-secondary">{step.rationale}</p>}
        {step.kind === "navigate" && step.workspace && (
          <Link href={workspaceHref(campaignId, step.workspace)} className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
            <ArrowUpRight aria-hidden />
            Open {WORKSPACES[step.workspace].label}
          </Link>
        )}
        <Outcome step={step} numbers={numbers} onOpenVersion={onOpenVersion} onShowRun={onShowRun} />
      </div>
    </li>
  );
}

/**
 * One plan: what was understood, each step with its code checks, and the confirmation. Nothing runs until the person
 * presses the one button; each step they leave unticked stays as it was. The summary and the reasons are the model's
 * interpretation; the proposed text is an AI proposal; whether a step is allowed is decided by code.
 */
export function PlanView({
  plan,
  elements,
  numbers,
  applying,
  applyError,
  onApply,
  onOpenVersion,
  onShowRun,
}: {
  plan: DirectPlan;
  elements: CreativeElement[];
  numbers: Map<string, number>;
  applying: boolean;
  applyError: unknown;
  onApply(stepIds: string[]): void;
  onOpenVersion(id: string): void;
  onShowRun(runId: string): void;
}) {
  const [choice, setChoice] = useState<Record<string, boolean>>({});
  const confirmable = plan.steps.filter((s) => s.needs_confirmation && CONFIRMABLE.has(s.status));
  const picked = confirmable.filter((s) => choice[s.id] ?? s.status === "proposed");
  const usesModel = picked.filter((s) => s.uses_model).length;
  const cost = formatCost(plan.estimated_cost_usd);
  const notes = plan.notes.filter((n) => n !== DEMO_NOTE);
  const source = plan.provider === "fixture" ? "" : [plan.model_id ?? plan.provider, plan.prompt_version && `prompt ${plan.prompt_version}`, cost && `${cost} (estimate)`].filter(Boolean).join(" · ");
  const from = numbers.get(plan.version_id);

  return (
    <section aria-labelledby="direct-plan-title" className="space-y-3 rounded-card border border-border bg-surface px-4 py-3.5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
        <div className="min-w-0 space-y-1">
          <h3 id="direct-plan-title" className="text-[15px] font-semibold text-ink">
            {plan.supported ? "Plan" : "Not something a plan can do"}
            {from && <span className="ml-2 font-mono text-[12px] font-normal text-ink-muted">from v{from}</span>}
          </h3>
          <p className="max-w-[68ch] text-[13.5px] text-ink-body">&ldquo;{plan.instruction}&rdquo;</p>
        </div>
        <Status tone={plan.status === "applied" ? "success" : plan.status === "proposed" || plan.status === "partial" ? "neutral" : "warning"} Icon={plan.status === "applied" ? Check : plan.status === "unsupported" ? CircleSlash : ArrowRight}>
          {STATUS_WORD[plan.status]}
        </Status>
      </div>

      {plan.summary && (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13.5px] text-ink-body">
          <Tag className="border-dashed border-ink-secondary/50 bg-surface text-ink-secondary" title="Written by a model. Not an observed fact.">
            <MessageSquareText aria-hidden />
            Model interpretation
          </Tag>
          {plan.summary}
        </p>
      )}

      {!plan.supported ? (
        <div className="space-y-2.5 rounded-lg border border-warning/40 bg-warning-soft/60 px-3.5 py-3">
          <p role="status" className="text-[13.5px] text-ink">{plan.refusal}</p>
          <div>
            <p className="text-[12.5px] font-medium text-ink">What a plan can do</p>
            <ul className="mt-1 list-disc pl-5 text-[13px] text-ink-body">
              {plan.supported_actions.map((action) => (
                <li key={action}>{action}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : (
        <>
          <ol className="ledger-rules overflow-hidden rounded-lg border border-border">
            {plan.steps.map((step) => (
              <StepRow
                key={step.id}
                step={step}
                checked={choice[step.id] ?? step.status === "proposed"}
                onToggle={(on) => setChoice((c) => ({ ...c, [step.id]: on }))}
                elements={elements}
                numbers={numbers}
                onOpenVersion={onOpenVersion}
                onShowRun={onShowRun}
              />
            ))}
          </ol>
          {notes.map((n) => (
            <p key={n} className="type-meta">{n}</p>
          ))}
          {confirmable.length > 0 && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <Button disabled={picked.length === 0 || applying} onClick={() => onApply(picked.map((s) => s.id))}>
                <Check aria-hidden />
                {applying ? "Applying…" : picked.length === 0 ? "Nothing selected" : `Apply ${picked.length} ${picked.length === 1 ? "step" : "steps"}`}
              </Button>
              <p className="type-meta">
                Nothing runs until you press this. Locks are checked again as each step runs.
                {usesModel > 0 && ` ${usesModel} of these call${usesModel === 1 ? "s" : ""} the model again.`}
              </p>
            </div>
          )}
        </>
      )}
      {applyError != null && <MutationError error={applyError} />}
      {source && <p className="type-meta">{source}</p>}
    </section>
  );
}
