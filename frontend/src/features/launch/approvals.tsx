"use client";

import { Ban, CircleCheck, Gavel, LoaderCircle, MessageSquareWarning, TriangleAlert, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Tag } from "@/components/evidence/badges";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";
import { Verdict } from "@/components/workflow/verdict";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useRecordApproval } from "./api";
import type { Approval, ApprovalDecision, ReadinessVerdict } from "./types";

const DECISION: Record<ApprovalDecision, { label: string; past: string; Icon: LucideIcon; help: string }> = {
  approve: { label: "Approve", past: "Approved", Icon: CircleCheck, help: "This version may go ahead in this region." },
  request_changes: { label: "Request changes", past: "Changes requested", Icon: MessageSquareWarning, help: "Not yet. Say what needs to change." },
  reject: { label: "Reject", past: "Rejected", Icon: Ban, help: "This version should not run in this region." },
};

const DECISION_VERDICT = { go: "Go", fix: "Fix", rethink: "Rethink" } as const;

/** The newest human decision on a version, and whether it was made against the recommendation now in force. */
export function ApprovalLine({ approval, verdict }: { approval: Approval | null; verdict: ReadinessVerdict }) {
  if (!approval) {
    return (
      <p className="text-[13.5px] text-ink-secondary">
        <span className="font-medium text-ink-body">No human decision recorded yet.</span>
      </p>
    );
  }
  const d = DECISION[approval.decision];
  const earlier = approval.readiness_verdict_id !== verdict.id;
  return (
    <div className="space-y-1.5 text-[13.5px]">
      <p className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <span className={cn("inline-flex items-center gap-1.5 font-semibold", approval.decision === "approve" ? "text-success" : approval.decision === "reject" ? "text-danger" : "text-warning")}>
          <d.Icon aria-hidden className="size-4" />
          {d.past}
        </span>
        <span className="text-ink-body">
          by {approval.decided_by_name ?? "a team member"} · {formatDateTime(approval.decided_at)}
        </span>
        {approval.overrides_recommendation && (
          <Tag className="border-warning/40 bg-warning-soft font-semibold text-warning" title="Approved although the readiness recommendation was not Go (or none existed).">
            <TriangleAlert aria-hidden />
            Overrides recommendation{approval.verdict_at_decision ? `: it was ${DECISION_VERDICT[approval.verdict_at_decision]}` : ": there was none"}
          </Tag>
        )}
      </p>
      <blockquote className="max-w-[68ch] border-l border-border-strong/50 pl-3 text-ink-body">{approval.reason}</blockquote>
      {earlier && (
        <p className="max-w-[68ch] text-[12.5px] text-ink-muted">
          Made on an earlier verdict{approval.verdict_at_decision ? ` (${DECISION_VERDICT[approval.verdict_at_decision]})` : ""}. The recommendation in force now was computed after it.
        </p>
      )}
    </div>
  );
}

/**
 * Record a person's decision. Approving against a Fix or Rethink recommendation is allowed, so it is a deliberate step: the
 * override is explained, the open issues stay in view, a reason is required and a confirmation must be ticked.
 */
export function ApprovalDialog({
  campaignId,
  verdict,
  open,
  onOpenChange,
}: {
  campaignId: string;
  verdict: ReadinessVerdict;
  open: boolean;
  onOpenChange(open: boolean): void;
}) {
  const record = useRecordApproval(campaignId);
  const [decision, setDecision] = useState<ApprovalDecision>("approve");
  const [reason, setReason] = useState("");
  const [understood, setUnderstood] = useState(false);
  const override = decision === "approve" && verdict.verdict !== "go";
  const ready = reason.trim().length > 0 && (!override || understood);

  function close(next: boolean) {
    if (!next) {
      record.reset();
      setReason("");
      setUnderstood(false);
      setDecision("approve");
    }
    onOpenChange(next);
  }

  function submit() {
    record.mutate(
      { region_code: verdict.region_code, version_id: verdict.version_id, decision, reason: reason.trim(), readiness_verdict_id: verdict.id },
      {
        onSuccess: (a) => {
          toast.success(`${DECISION[a.decision].past} for ${verdict.region_name}${a.overrides_recommendation ? ", recorded as an override" : ""}.`);
          close(false);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Record a decision: {verdict.region_name}</DialogTitle>
          <DialogDescription>
            {verdict.score.label}. Your name, the time, your reason and the recommendation in force are stored with the decision.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5 rounded-lg border border-border bg-surface-muted/60 px-3.5 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <Verdict value={verdict.verdict} />
              <span className="type-meta">Recommendation in force, rules {verdict.rule_version}</span>
            </div>
            <p className="text-[13.5px] text-ink">{verdict.main_reason}</p>
          </div>

          <fieldset className="space-y-2">
            <legend className="text-[13px] font-medium text-ink">Your decision</legend>
            <RadioGroup value={decision} onValueChange={(v) => setDecision(v as ApprovalDecision)} aria-label="Decision">
              {(Object.keys(DECISION) as ApprovalDecision[]).map((k) => (
                <label key={k} className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-border px-3 py-2 has-[[data-checked]]:border-border-strong has-[[data-checked]]:bg-surface-raised">
                  <RadioGroupItem value={k} className="mt-0.5" />
                  <span className="min-w-0">
                    <span className="block text-[14px] font-medium text-ink">{DECISION[k].label}</span>
                    <span className="block text-[12.5px] text-ink-secondary">{DECISION[k].help}</span>
                  </span>
                </label>
              ))}
            </RadioGroup>
          </fieldset>

          {override && (
            <div role="alert" className="space-y-2.5 rounded-lg border border-warning/45 bg-warning-soft/70 px-3.5 py-3 text-[13px] text-ink">
              <p className="flex items-start gap-2 font-semibold">
                <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" />
                You are approving against a {DECISION_VERDICT[verdict.verdict]} recommendation
              </p>
              <p>
                The rules found {verdict.issues.length} {verdict.issues.length === 1 ? "issue" : "issues"}. This approval is allowed, and it is recorded as an
                override of the recommendation, with the verdict that was in force, the rule version, your name and your reason. The verdict itself does not
                change and the open issues stay on the board.
              </p>
              {verdict.highest_priority_issue && (
                <p>
                  <span className="font-medium">Highest-priority issue: </span>
                  {verdict.highest_priority_issue.summary}
                </p>
              )}
              <label className="flex cursor-pointer items-start gap-2.5">
                <Checkbox checked={understood} onCheckedChange={(v) => setUnderstood(v === true)} className="mt-0.5" />
                <span>I understand this approval will be recorded as an override of a {DECISION_VERDICT[verdict.verdict]} recommendation.</span>
              </label>
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="decision-reason" className="block text-[13px] font-medium text-ink">
              Reason <span className="text-danger">*</span>
            </label>
            <Textarea
              id="decision-reason"
              value={reason}
              maxLength={1000}
              onChange={(e) => setReason(e.target.value)}
              placeholder={override ? "Why approve although the rules recommend " + DECISION_VERDICT[verdict.verdict] + "? Someone will read this later." : "What this decision rests on."}
            />
          </div>

          {record.error && <ErrorState error={record.error} onRetry={submit} />}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)}>
            Cancel
          </Button>
          <Button disabled={!ready || record.isPending} onClick={submit}>
            {record.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <Gavel aria-hidden />}
            {record.isPending ? "Recording…" : override ? "Approve and record override" : `Record: ${DECISION[decision].label.toLowerCase()}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
