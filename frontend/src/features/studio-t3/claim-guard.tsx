"use client";

import { Check, ExternalLink, MessageSquareText, ShieldCheck, Sigma } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfidenceIndicator } from "@/components/evidence/confidence";
import { Tag } from "@/components/evidence/badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { KIND_LABEL } from "@/features/studio/model";
import { MutationError } from "@/features/studio/parts";
import type { VersionNode } from "@/features/studio/types";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useClaimCheck, useClaimChecks, useReviewFinding, useRunClaimCheck } from "./api";
import { AnchorLine, MarkedText, plural, ToneTag } from "./parts";
import type { ClaimGuardFinding, ClaimKind, ReviewDecision } from "./types";

const CLAIM_LABEL: Record<ClaimKind, string> = {
  superiority: "Superiority",
  comparative: "Comparison",
  price: "Price or offer",
  health: "Health",
  guarantee: "Guarantee or promise",
  financial: "Financial",
};

const DECISIONS: { value: ReviewDecision; label: string; hint: string }[] = [
  { value: "substantiated", label: "Substantiated", hint: "Evidence for this exact wording is on file." },
  { value: "revise", label: "Will revise", hint: "The copy will change. This still holds a Go." },
  { value: "accepted", label: "Accept the risk", hint: "A person accepts it as it is." },
  { value: "not_a_claim", label: "Not a claim", hint: "The wording was matched by mistake." },
];
const DECISION_LABEL = Object.fromEntries(DECISIONS.map((d) => [d.value, d.label])) as Record<ReviewDecision, string>;

function Review({ campaignId, versionId, finding }: { campaignId: string; versionId: string; finding: ClaimGuardFinding }) {
  const review = useReviewFinding(campaignId);
  const [decision, setDecision] = useState<ReviewDecision | null>(finding.review?.decision ?? null);
  const [note, setNote] = useState(finding.review?.note ?? "");
  const changed = decision !== (finding.review?.decision ?? null) || note.trim() !== (finding.review?.note ?? "");
  return (
    <fieldset className="space-y-2 border-t border-border pt-3">
      <legend className="text-[12.5px] font-medium text-ink-secondary">
        Review by a person{finding.review ? `: ${DECISION_LABEL[finding.review.decision]}, ${formatRelative(finding.review.reviewed_at)}` : ": not yet"}
      </legend>
      <div role="radiogroup" aria-label="Decision" className="flex flex-wrap gap-1.5">
        {DECISIONS.map((d) => (
          <Button key={d.value} type="button" size="sm" variant={decision === d.value ? "default" : "outline"} role="radio" aria-checked={decision === d.value} title={d.hint} onClick={() => setDecision(d.value)}>
            {decision === d.value && <Check aria-hidden />}
            {d.label}
          </Button>
        ))}
      </div>
      <Textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} rows={2} placeholder="Note: where the evidence is, or what will change (optional)" aria-label="Review note" className="max-w-[60ch]" />
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          size="sm"
          disabled={!decision || !changed || review.isPending}
          onClick={() =>
            decision &&
            review.mutate({ versionId, key: finding.key, decision, note: note.trim() || null }, { onSuccess: () => toast.success("Decision recorded") })
          }
        >
          {review.isPending ? "Saving…" : "Record decision"}
        </Button>
        {review.isError && <MutationError error={review.error} />}
      </div>
    </fieldset>
  );
}

function Finding({ campaignId, version, finding }: { campaignId: string; version: VersionNode; finding: ClaimGuardFinding }) {
  const element = version.elements.find((e) => e.id === finding.element_id);
  const text = typeof element?.value === "string" ? element.value : finding.phrase;
  const start = typeof element?.value === "string" ? finding.start : 0;
  const end = typeof element?.value === "string" ? finding.end : finding.phrase.length;
  const model = finding.source === "model";
  return (
    <article aria-label={`${CLAIM_LABEL[finding.kind]} claim in ${finding.element_id}`} className="space-y-3 px-4 py-4">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <h4 className="text-[14px] font-semibold text-ink">{CLAIM_LABEL[finding.kind]}</h4>
        <ToneTag tone={finding.severity} label={`${finding.severity[0].toUpperCase()}${finding.severity.slice(1)} severity`} />
        {model ? (
          <Tag className="border-dashed border-ink-secondary/50 bg-surface text-ink-secondary" title="A model proposed this reading. Code verified that the quote is in the element; whether it is a claim is the model's interpretation.">
            <MessageSquareText aria-hidden />
            Model interpretation
          </Tag>
        ) : (
          <Tag className="border-border bg-surface-muted text-ink" title="A fixed wording rule matched these words in code.">
            <Sigma aria-hidden />
            Rule match
          </Tag>
        )}
        <span className="inline-flex items-center gap-1.5 text-[12.5px] text-ink-secondary" title="How sure the match is that this wording is a claim of this kind. Not a probability.">
          Match <ConfidenceIndicator level={finding.confidence} showRule={false} />
        </span>
        {finding.blocks_go && (!finding.review || finding.review.decision === "revise") && <span className="text-[12.5px] font-medium text-danger">Holds a Go until reviewed</span>}
      </header>
      <AnchorLine anchor={finding.anchor} elementId={`${finding.element_id}${element ? ` · ${KIND_LABEL[element.kind]}` : ""}`} />
      <MarkedText text={text} marks={[{ start, end, tone: "claim" }]} lang={element?.language} />
      <p className="max-w-[68ch] text-[13.5px] text-ink-body">{finding.explanation}</p>

      <dl className="ledger-rules type-ledger overflow-hidden rounded-lg border border-border text-[12.5px]">
        <div className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-x-3 px-3 py-1.5">
          <dt className="text-ink-secondary">Brand Kit policy</dt>
          <dd className="text-ink-body">
            {finding.policy.status === "forbidden" && (
              <>
                <span className="font-medium text-danger">Forbidden.</span> {finding.policy.rule}
              </>
            )}
            {finding.policy.status === "not_listed" && "The claims policy does not mention this kind of claim."}
            {finding.policy.status === "no_policy" && "This brand has no claims policy yet."}
          </dd>
        </div>
        <div className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-x-3 px-3 py-1.5">
          <dt className="text-ink-secondary">Evidence on file</dt>
          <dd className="space-y-1 text-ink-body">
            {finding.evidence.status === "none" && <span>None. Nothing the campaign holds bears on this wording.</span>}
            {finding.evidence.status === "mismatch" && <span className="font-medium text-warning">The price in the copy differs from the brief.</span>}
            {finding.evidence.items.map((item, i) => (
              <p key={i}>
                {item.statement} <span className="text-ink-muted">{item.note}</span>
              </p>
            ))}
          </dd>
        </div>
        <div className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-x-3 px-3 py-1.5">
          <dt className="text-ink-secondary">Basis shown</dt>
          <dd className="text-ink-body">
            {finding.basis.stated ? (
              <>
                Names a basis (<span lang={element?.language ?? undefined}>{finding.basis.wording}</span>){finding.basis.sourced ? " with a source or date nearby." : " but shows no source, sample or date."}
              </>
            ) : (
              "No basis is named for it."
            )}
          </dd>
        </div>
      </dl>

      {finding.ad_codes.length > 0 && (
        <details className="group text-[13px]">
          <summary className="cursor-pointer font-medium text-ink-body select-none hover:text-ink">ASCI references ({finding.ad_codes.length})</summary>
          <ul className="mt-2 space-y-2.5">
            {finding.ad_codes.map((a) => (
              <li key={a.id} className="space-y-0.5 border-l-2 border-border pl-3">
                <p className="font-medium text-ink">
                  Clause {a.clause}: {a.title}
                </p>
                <p className="max-w-[72ch] text-[12.5px] text-ink-body">{a.excerpt}</p>
                <a href={a.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[12px] text-primary underline-offset-2 hover:underline">
                  ASCI document <ExternalLink aria-hidden className="size-3" />
                </a>
              </li>
            ))}
          </ul>
        </details>
      )}
      <details className="group text-[13px]">
        <summary className="cursor-pointer font-medium text-ink-body select-none hover:text-ink">How the severity was computed</summary>
        <ol className="mt-2 list-decimal space-y-0.5 pl-5 text-[12.5px] text-ink-body">
          {finding.severity_rules.map((r) => (
            <li key={r.rule}>
              <span className="font-mono text-[11.5px] text-ink-muted">{r.rule}</span> {r.effect === "base" ? "" : `${r.effect}: `}
              {r.reason}
            </li>
          ))}
        </ol>
      </details>
      {finding.limitations.length > 0 && <p className="type-meta">{finding.limitations.join(" ")}</p>}
      <Review campaignId={campaignId} versionId={version.id} finding={finding} />
    </article>
  );
}

/**
 * Claim Guard: the claims in the selected version's copy, found by wording rules first (a model may add a labelled second
 * pass), each graded in code against the Brand Kit claims policy, the evidence on file and the ASCI index. A finding is a
 * warning for a person to review; nothing here clears a creative.
 */
export function ClaimGuardPanel({ campaignId, version, demo }: { campaignId: string; version: VersionNode; demo: boolean }) {
  const checks = useClaimChecks(campaignId, version.id);
  const latest = checks.data?.items[0] ?? null;
  const check = useClaimCheck(campaignId, latest?.id ?? null);
  const run = useRunClaimCheck(campaignId);
  const [model, setModel] = useState(false);
  const hasText = version.elements.some((e) => typeof e.value === "string" && e.value.trim());

  const controls = (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <Button type="button" disabled={run.isPending || !hasText} onClick={() => run.mutate({ versionId: version.id, model }, { onSuccess: (c) => toast.success(`${plural(c.counts.total, "finding")} in the copy`) })}>
        <ShieldCheck aria-hidden />
        {run.isPending ? "Checking…" : latest ? "Check again" : "Check the claims"}
      </Button>
      <label className="inline-flex cursor-pointer items-center gap-2 text-[13px] text-ink-body" title={demo ? undefined : "One model call. Its quotes are verified in code."}>
        <input type="checkbox" className="size-4" checked={model} onChange={(e) => setModel(e.target.checked)} />
        Add a model second pass for implied claims
      </label>
    </div>
  );

  if (checks.isPending) return <LoadingState label="Loading the claim checks…" />;
  if (checks.isError) return <ErrorState error={checks.error} onRetry={() => void checks.refetch()} />;
  if (!latest) {
    return (
      <div className="space-y-3">
        <EmptyState
          title="This version has not been checked for claims"
          description="Claim Guard finds superiority, comparison, price, health, guarantee and financial claims in the copy, checks each against the Brand Kit claims policy, the evidence on file and the ASCI ad code, and holds them for a person to review."
          needs={[{ label: "Text in the version", met: hasText }]}
          action={controls}
        />
        {run.isError && <MutationError error={run.error} />}
      </div>
    );
  }
  if (check.isPending) return <LoadingState label="Loading the check…" />;
  if (check.isError) return <ErrorState error={check.error} onRetry={() => void check.refetch()} />;
  const c = check.data;
  const counts = c.counts;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="space-y-1">
          <p className="text-[14px] text-ink">
            <span className="font-semibold">{plural(counts.total, "finding")}</span>
            {counts.total > 0 && (
              <>
                {" "}
                · {counts.high} high, {counts.medium} medium, {counts.low} low · <span className={cn(counts.review_complete ? "text-success" : "text-ink")}>{counts.reviewed} of {counts.total} reviewed</span>
              </>
            )}
          </p>
          {counts.blocks_go > 0 && <p className="text-[13px] font-medium text-danger">{plural(counts.blocks_go, "claim")} hold a Go until a person reviews {counts.blocks_go === 1 ? "it" : "them"}.</p>}
          {counts.total > 0 && counts.review_complete && <p className="text-[13px] text-success">Every finding has a decision. That records that a person looked; it is not clearance.</p>}
        </div>
        {controls}
      </div>
      {run.isError && <MutationError error={run.error} />}
      {c.model?.error && <p role="alert" className="rounded-lg border border-warning/40 bg-warning-soft/60 px-3 py-2 text-[13px] text-ink">The model pass did not run: {c.model.error}. The wording-rule findings below are complete.</p>}
      {counts.total === 0 ? (
        <p className="rounded-card border border-dashed border-border-strong/50 px-4 py-3 text-[13.5px] text-ink-secondary">
          The wording rules found no claim in {plural(c.texts_checked, "text element")}. That is not a statement that the copy is fine: the rules match words, and implied claims need a reader.
        </p>
      ) : (
        <div className="ledger-rules overflow-hidden rounded-card border border-border bg-surface">
          {c.findings.map((f) => (
            <Finding key={f.key} campaignId={campaignId} version={version} finding={f} />
          ))}
        </div>
      )}
      <p className="type-meta">
        Wording rules ({c.rules_version}) over {plural(c.texts_checked, "text element")}, the Brand Kit claims policy, the Campaign Brief, region claims and a partial ASCI index
        {c.model && !c.model.error ? `; second pass by ${c.model.model_id ?? c.model.provider ?? "a model"} (${c.model.kept} kept, ${c.model.dropped} dropped in code)` : ""}. A warning for human review, not legal clearance.
      </p>
    </div>
  );
}
