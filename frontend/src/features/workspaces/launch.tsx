"use client";

import { useQuery } from "@tanstack/react-query";
import { Scale } from "lucide-react";

import { ContextPanel } from "@/components/shell/workspace-shell";
import { ErrorState, LoadingState } from "@/components/states";
import { Verdict, type VerdictValue } from "@/components/workflow/verdict";
import { WEIGHT_FIELDS } from "@/features/project/campaign-form";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { CampaignContent, Recommendation } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useCampaign } from "./campaign-context";
import { CampaignFacts, EarlierTools, FeatureScope, LedgerList, SectionTitle, useCampaignRuns, versionsOldestFirst, WorkspaceHeader } from "./parts";

/**
 * Mapping from the evaluation's deterministic decision to the readiness verdict (audit 7.2, proposed): accept is Go; a
 * risk rule (R1) or no improvement (R2) is Rethink; revise, validate and inconclusive are Fix with a named next step.
 */
export function verdictFor(rec: Recommendation): { verdict: VerdictValue; next: string } {
  if (/^R[12](_|$)/.test(rec.rule_id)) return { verdict: "rethink", next: "Revisit the adaptation approach before spending; do not launch this version." };
  if (rec.decision === "accept") return { verdict: "go", next: "Prepare the region plan and asset pack." };
  if (rec.decision === "validate") return { verdict: "fix", next: "Validate the open question with real people before launch." };
  if (rec.decision === "inconclusive") return { verdict: "fix", next: "Gather more evidence, then re-run Compare and Score." };
  return { verdict: "fix", next: "Apply the named revisions and re-run Compare and Score." };
}

const FIELDS: { key: "headline" | "body" | "call_to_action"; label: string }[] = [
  { key: "headline", label: "Headline" },
  { key: "body", label: "Body" },
  { key: "call_to_action", label: "Call to action" },
];

function VersionColumn({ title, content, other }: { title: string; content: CampaignContent; other?: CampaignContent }) {
  return (
    <section aria-label={title} className="min-w-0 rounded-card border border-border bg-surface">
      <p className="border-b border-border px-4 py-2.5 text-[13px] font-semibold text-ink">{title}</p>
      <dl className="ledger-rules">
        {FIELDS.map((f) => {
          const value = content[f.key];
          const changed = other ? (other[f.key] ?? "") !== (value ?? "") : false;
          return (
            <div key={f.key} className="space-y-1 px-4 py-3">
              <dt className="flex items-center justify-between gap-2">
                <span className="type-meta">{f.label}</span>
                {other && (
                  <span className={cn("text-[11.5px] font-medium", changed ? "text-warning" : "text-ink-muted")}>{changed ? "Changed" : "Preserved"}</span>
                )}
              </dt>
              <dd className={cn("text-[14px] leading-relaxed whitespace-pre-line", value ? "text-ink" : "text-ink-muted")}>{value ?? "Empty"}</dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}

function ReadinessBoard() {
  const { campaign } = useCampaign();
  const runs = useCampaignRuns(["campaign_evaluation"], 10);
  const latest = runs.data?.find((r) => r.status === "completed" || r.status === "partial") ?? null;
  const evaluationId = latest?.result?.ids[0] ?? null;
  const evaluation = useQuery({
    queryKey: ["evaluation", campaign.id, evaluationId],
    enabled: Boolean(evaluationId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/campaigns/{campaign_id}/evaluations/{evaluation_id}", {
          params: { path: { campaign_id: campaign.id, evaluation_id: evaluationId! } },
        }),
      ),
  });

  if (runs.error) return <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />;
  if (runs.isPending || (evaluationId && evaluation.isPending)) return <LoadingState label="Reading the latest evaluation…" />;
  if (evaluation.error) return <ErrorState error={evaluation.error} onRetry={() => void evaluation.refetch()} />;

  const rec = evaluation.data?.recommendation ?? null;
  const mapped = rec ? verdictFor(rec) : null;
  return (
    <section aria-labelledby="readiness" className="clay rounded-card border border-border px-5 py-4">
      <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
        <div className="space-y-1">
          <h2 id="readiness" className="text-[15px] font-semibold text-ink">
            Readiness
          </h2>
          {mapped ? <Verdict value={mapped.verdict} size="lg" /> : <p className="text-[14px] font-medium text-ink-secondary">No verdict yet</p>}
        </div>
        <div className="min-w-0 flex-1 space-y-1.5 text-[13.5px]">
          {rec && mapped && evaluation.data ? (
            <>
              <p className="text-ink">
                <span className="font-medium">Main reason: </span>
                {rec.rationale}
              </p>
              <p className="text-ink-body">
                <span className="font-medium text-ink">Next action: </span>
                {mapped.next}
              </p>
              <p className="type-meta">
                Rule {rec.rule_id} · scoring {evaluation.data.scoring_version} · evaluated {formatDateTime(evaluation.data.created_at)} for{" "}
                {evaluation.data.market.display_name}
              </p>
            </>
          ) : (
            <p className="text-ink-secondary">
              A verdict needs a completed Compare and Score run on this campaign. It comes from fixed rules over the scores, never from a free-form model
              opinion, and always carries its main reason and next action.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

/** Launch Room: the readiness verdict on top, then the original and current versions side by side with what changed. */
export function LaunchWorkspace() {
  const { campaign } = useCampaign();
  const versions = versionsOldestFirst(campaign);
  const original = versions[0];
  const current = campaign.current_version;
  const same = original?.id === current.id;

  return (
    <>
      <WorkspaceHeader workspace="launch">
        <CampaignFacts />
      </WorkspaceHeader>
      <div className="space-y-6">
        <ReadinessBoard />
        <section aria-labelledby="compare" className="space-y-2.5">
          <SectionTitle id="compare" meta={same ? "Only one version exists" : `v${original.version_number} against v${current.version_number}`}>
            Compare versions
          </SectionTitle>
          <div className={cn("grid gap-4", !same && "md:grid-cols-2")}>
            {original && <VersionColumn title={`Original · v${original.version_number}`} content={original.content} />}
            {!same && <VersionColumn title={`Current · v${current.version_number}`} content={current.content} other={original.content} />}
          </div>
        </section>
      </div>
      <ContextPanel title="Scoring rules">
        <div className="space-y-2">
          <p className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-ink">
            <Scale aria-hidden className="size-4" />
            Fixed weights for this campaign
          </p>
          <LedgerList rows={WEIGHT_FIELDS.map((f) => ({ label: f.label, value: <span className="tabular-nums">{campaign.evaluation_criteria[f.key].toFixed(2)}</span> }))} />
          <p className="text-[12.5px] text-ink-muted">Scores are calculated by documented code from these weights. The model may add observations; it never sets the score.</p>
        </div>
        <EarlierTools
          tools={[
            { segment: "loop", label: "Loop", note: "Evaluate original against candidates with a recommendation" },
            { segment: "voice", label: "Voice", note: "Adaptations with change lists and revisions" },
          ]}
        />
        <FeatureScope workspace="launch" />
      </ContextPanel>
    </>
  );
}
