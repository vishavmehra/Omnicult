"use client";

import { Bot, CircleCheck, CircleDashed, Database, FlaskConical, MessageSquareText, Radio, Sigma } from "lucide-react";
import type { ComponentType, ReactNode } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { ClaimType, ConfidenceLabel, DataMode, EvidenceType, RetrievalMode } from "@/lib/api/types";
import { CLAIM_LABEL, CONFIDENCE_RULE, LABEL_MEANING, evidenceLabel, type EvidenceUiLabel } from "@/lib/evidence";
import { formatDateTime, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

const TAG =
  "inline-flex h-5 shrink-0 items-center gap-1 rounded-sm border px-1.5 text-[11px] leading-none font-medium whitespace-nowrap [&>svg]:size-3 [&>svg]:shrink-0";

/** Compact label chip used by every evidence badge. Exported for consistent ad-hoc tags. */
export function Tag({ className, children, title }: { className?: string; children: ReactNode; title?: string }) {
  return (
    <span className={cn(TAG, className)} title={title}>
      {children}
    </span>
  );
}

const LABEL_STYLE: Record<EvidenceUiLabel, { className: string; Icon: ComponentType }> = {
  "Observed outcome": { className: "border-success/25 bg-success-soft text-success", Icon: CircleCheck },
  "Source data": { className: "border-info/25 bg-info-soft text-info", Icon: Database },
  Calculated: { className: "border-border bg-surface-muted text-ink", Icon: Sigma },
  "Model interpretation": { className: "border-dashed border-ink-secondary/50 bg-surface text-ink-secondary", Icon: MessageSquareText },
  Synthetic: { className: "border-dashed border-ink-secondary/50 bg-surface-muted text-ink-secondary", Icon: Bot },
  Unverified: { className: "border-warning/30 bg-warning-soft text-warning", Icon: CircleDashed },
};

function UiLabel({ label }: { label: EvidenceUiLabel }) {
  const { className, Icon } = LABEL_STYLE[label];
  return (
    <Tag className={className} title={LABEL_MEANING[label]}>
      <Icon aria-hidden />
      {label}
    </Tag>
  );
}

/** Evidence label derived from evidence_type + claim_type (contracts/README §7). */
export function EvidenceLabel({ record }: { record: { evidence_type: EvidenceType; claim_type: ClaimType } }) {
  return <UiLabel label={evidenceLabel(record)} />;
}

/** Label for a finding's claim type. */
export function ClaimBadge({ claim }: { claim: ClaimType }) {
  return <UiLabel label={CLAIM_LABEL[claim]} />;
}

/** Retrieval badge. `generated` records get no badge (contracts/README §7). */
export function RetrievalBadge({ mode, retrievedAt }: { mode: RetrievalMode; retrievedAt?: string | null }) {
  switch (mode) {
    case "live":
      return (
        <Tag className="border-success/25 bg-success-soft text-success">
          <Radio aria-hidden />
          Live
        </Tag>
      );
    case "cached":
      return (
        <Tag className="border-info/25 bg-info-soft text-info" title={retrievedAt ? `Retrieved ${formatDateTime(retrievedAt)}` : undefined}>
          Cached{retrievedAt ? ` · retrieved ${formatRelative(retrievedAt)}` : ""}
        </Tag>
      );
    case "fixture":
      return (
        <Tag className="border-warning/30 bg-warning-soft text-warning" title="Labeled fixture data, not a live provider result.">
          <FlaskConical aria-hidden />
          Fixture
        </Tag>
      );
    case "user_input":
      return <Tag className="border-border bg-surface text-ink-secondary">User input</Tag>;
    default:
      return null;
  }
}

/** Evidence-quality label with its deterministic rule. Never a probability (contracts/README §8). */
export function ConfidenceBadge({ label }: { label: ConfidenceLabel }) {
  const { label: text, rule } = CONFIDENCE_RULE[label];
  const tone =
    label === "moderate"
      ? "border-border bg-surface text-ink"
      : label === "limited"
        ? "border-border bg-surface-muted text-ink-secondary"
        : "border-dashed border-ink-secondary/50 bg-surface text-ink-secondary";
  return (
    <Tooltip>
      <TooltipTrigger
        className={cn(TAG, tone, "cursor-help outline-none")}
        aria-label={`${text}. ${rule} This is an evidence-quality label, not a probability.`}
      >
        <span aria-hidden className="flex gap-0.5">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className={cn(
                "size-1.5 rounded-full border border-current",
                i < (label === "moderate" ? 2 : label === "limited" ? 1 : 0) && "bg-current",
              )}
            />
          ))}
        </span>
        {text}
      </TooltipTrigger>
      <TooltipContent className="max-w-72 flex-col items-start gap-1 text-left">
        <span className="font-medium">{text}</span>
        <span>{rule}</span>
        <span className="opacity-80">Evidence-quality label, not a probability. There is no “high” label until observed outcomes exist.</span>
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * Quiet inline note for anything a simulation produced: participants, answers, panels, buzz. Small muted text with a robot
 * mark, no box. `compact` keeps only the word for dense rows (with a tooltip).
 */
export function SyntheticLabel({ compact, children, className }: { compact?: boolean; children?: ReactNode; className?: string }) {
  const full = children ?? "Synthetic: simulated opinion, not real research";
  return (
    <span
      title={compact ? "Synthetic: simulated by a model. Not a real participant and not real research." : undefined}
      className={cn("type-meta inline-flex max-w-full items-center gap-1 [&>svg]:size-3 [&>svg]:shrink-0", className)}
    >
      <Bot aria-hidden />
      {compact ? "Synthetic" : full}
    </span>
  );
}

/** Persistent disclosure for AI-generated reactions (legacy Omnicult pages). */
export function SyntheticBadge() {
  return <SyntheticLabel>AI-generated reaction, not a real participant</SyntheticLabel>;
}

/** Project/run mode. Demo data must never be confused with live results, so it stays as quiet muted text. */
export function ModeBadge({ mode }: { mode: DataMode }) {
  if (mode === "demo") {
    return (
      <span className="type-meta whitespace-nowrap" title="Demo project: deterministic, labeled fixtures. Not live research.">
        Demo data
      </span>
    );
  }
  return (
    <Tag className="border-success/25 bg-success-soft text-success" title="Live project: runs call the configured providers.">
      <Radio aria-hidden />
      Live
    </Tag>
  );
}
