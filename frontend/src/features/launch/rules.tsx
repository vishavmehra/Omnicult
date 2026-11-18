"use client";

import { OctagonAlert, Wrench } from "lucide-react";

import { Tag } from "@/components/evidence/badges";
import { ErrorState, LoadingState } from "@/components/states";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Verdict } from "@/components/workflow/verdict";
import { cn } from "@/lib/utils";

import { useReadinessRules } from "./api";
import { WIDE_SHEET } from "./bits";
import type { ReadinessIssue, ReadinessRules } from "./types";

/**
 * The named thresholds each rule reads (backend/app/analytics/readiness.py). The rule's own description, served by the API,
 * states the numbers in words; these names let a reader find the same value in the thresholds table. A rule absent here
 * (a newer rule version) simply shows its description.
 */
const THRESHOLDS: Record<string, string[]> = {
  RT1: ["min_panel", "message_fail_share"],
  RT3: ["severe_risk_points"],
  RT4: ["min_panel", "relevance_fail_share"],
  FX6: ["min_panel", "message_fail_share", "message_go_share"],
  FX7: ["back_translation_go_share"],
  FX8: ["min_panel", "relevance_fail_share", "relevance_go_share"],
  FX9: ["objective_go_value"],
  FX10: ["medium_findings_fix"],
  FX15: ["min_panel"],
  FX16: ["go_min_overall"],
};

const code = (ruleId: string) => ruleId.split("_")[0];

export function thresholdsFor(ruleId: string, rules: ReadinessRules | undefined) {
  return (THRESHOLDS[code(ruleId)] ?? []).filter((n) => rules && n in rules.thresholds).map((name) => ({ name, value: rules!.thresholds[name] }));
}

export function EffectTag({ effect }: { effect: "fix" | "rethink" }) {
  return effect === "rethink" ? (
    <Tag className="border-danger/35 bg-danger-soft text-danger" title="While this rule fires, the verdict cannot be better than Rethink.">
      <OctagonAlert aria-hidden />
      Forces Rethink
    </Tag>
  ) : (
    <Tag className="border-warning/35 bg-warning-soft text-warning" title="While this rule fires, the verdict cannot be better than Fix.">
      <Wrench aria-hidden />
      Holds at Fix
    </Tag>
  );
}

function Thresholds({ ruleId, rules }: { ruleId: string; rules: ReadinessRules | undefined }) {
  const named = thresholdsFor(ruleId, rules);
  if (named.length === 0) return null;
  return (
    <span className="font-mono text-[12px] text-ink-body">
      {named.map((t) => `${t.name} = ${t.value}`).join(" · ")}
    </span>
  );
}

/** One rule that fired for a verdict: what it saw, what to do, what it read, and the threshold it applied. */
export function FiredRule({ issue, first, rules }: { issue: ReadinessIssue; first: boolean; rules: ReadinessRules | undefined }) {
  const doc = rules?.rules.find((r) => r.rule_id === issue.rule_id);
  const claims = issue.evidence_ids.length;
  return (
    <li className="space-y-1.5 px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-mono text-[12.5px] font-medium text-ink">{issue.rule_id}</span>
        <EffectTag effect={issue.effect} />
        {first && <Tag className="border-border-strong/60 bg-surface-raised text-ink">Highest priority</Tag>}
        <span className="type-meta">
          priority {issue.priority} · reads {issue.source.replace(/_/g, " ")}
          {claims ? ` · ${claims} evidence ${claims === 1 ? "claim" : "claims"}` : ""}
        </span>
      </div>
      <p className="max-w-[72ch] text-[13.5px] text-ink">{issue.summary}</p>
      <p className="max-w-[72ch] text-[13px] text-ink-body">
        <span className="font-medium text-ink">Next step: </span>
        {issue.action}
      </p>
      <p className="type-ledger max-w-[72ch] text-[12.5px] text-ink-muted">
        <span className="font-medium text-ink-secondary">Threshold: </span>
        {doc?.description ?? "The rule text could not be loaded."} <Thresholds ruleId={issue.rule_id} rules={rules} />
      </p>
    </li>
  );
}

/** Every readiness rule with its effect, priority and named thresholds, plus what each verdict means. */
export function RulesSheet({ campaignId, open, onOpenChange }: { campaignId: string; open: boolean; onOpenChange(open: boolean): void }) {
  const rules = useReadinessRules(campaignId);
  const data = rules.data;
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className={cn("overflow-y-auto", WIDE_SHEET)}>
        <SheetHeader>
          <SheetTitle>Readiness rules {data?.rule_version ?? ""}</SheetTitle>
          <SheetDescription>
            A verdict is the worst effect among the rules that fire; with none firing it is Go. No model chooses a verdict.
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-6 px-4 pb-6">
          {rules.error ? (
            <ErrorState error={rules.error} onRetry={() => void rules.refetch()} />
          ) : !data ? (
            <LoadingState label="Reading the rules…" />
          ) : (
            <>
              <ul className="space-y-2">
                {(["go", "fix", "rethink"] as const).map((v) => (
                  <li key={v} className="flex flex-wrap items-start gap-x-3 gap-y-1">
                    <Verdict value={v} />
                    <span className="min-w-0 flex-1 text-[13px] text-ink-body">{data.verdict_meanings[v]}</span>
                  </li>
                ))}
              </ul>
              <ul className="ledger-rules rounded-card border border-border bg-surface">
                {[...data.rules].sort((a, b) => a.priority - b.priority).map((r) => (
                  <li key={r.rule_id} className="space-y-1.5 px-4 py-3">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <span className="font-mono text-[12.5px] font-medium text-ink">{r.rule_id}</span>
                      <EffectTag effect={r.effect} />
                      <span className="type-meta">priority {r.priority}</span>
                    </div>
                    <p className="max-w-[62ch] text-[13px] text-ink-body">{r.description}</p>
                    <Thresholds ruleId={r.rule_id} rules={data} />
                  </li>
                ))}
              </ul>
              <section className="space-y-2">
                <h3 className="text-[13px] font-semibold text-ink">Named thresholds in force</h3>
                <dl className={cn("ledger-rules rounded-card border border-border bg-surface")}>
                  {Object.entries(data.thresholds).map(([name, value]) => (
                    <div key={name} className="flex justify-between gap-4 px-4 py-2 text-[13px]">
                      <dt className="font-mono text-[12.5px] text-ink-body">{name}</dt>
                      <dd className="tabular-nums text-ink">{value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
              <ul className="list-disc space-y-1 pl-5 text-[13px] text-ink-body">
                {data.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
                <li>Scoring version {data.scoring_version} supplies the overall score that rule FX16 reads.</li>
              </ul>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
