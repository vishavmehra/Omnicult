"use client";

import { GitCompareArrows, Gauge, Gavel, History } from "lucide-react";
import { useState } from "react";

import { Reveal, VerdictStamp } from "@/components/creative";
import { Tag } from "@/components/evidence/badges";
import { LimitationList } from "@/components/evidence/limitation-list";
import { Button } from "@/components/ui/button";
import { Verdict } from "@/components/workflow/verdict";
import { LedgerList } from "@/features/workspaces/parts";
import { formatDateTime, formatRelative, shortId, shownModel } from "@/lib/format";
import { cn } from "@/lib/utils";

import { ApprovalDialog, ApprovalLine } from "./approvals";
import { Disclosure } from "./bits";
import type { ComputePreset } from "./compute-sheet";
import { FiredRule } from "./rules";
import { ScoreCardList } from "./score-parts";
import type { Capabilities, ReadinessRules, RegionReadiness } from "./types";

const STRENGTH = { weak: "Weak", partial: "Partial", solid: "Solid" } as const;
const CONFLICT_STATE = { open: "Open", review_requested: "Review requested", resolved: "Resolved" } as const;

/**
 * One region on the Readiness Board: the verdict stamp, why, the highest-priority issue and the next action, then the rules that
 * fired with their thresholds, open conflicts, confidence limitations, the score at that verdict and the human decision.
 */
export function RegionPanel({
  index = 0,
  campaignId,
  region,
  rules,
  caps,
  onRecompute,
  onHistory,
}: {
  /** Position on the board: staggers the card's entrance and its stamp into one landing sequence. */
  index?: number;
  campaignId: string;
  region: RegionReadiness;
  rules: ReadinessRules | undefined;
  caps: Capabilities & { loading: boolean };
  onRecompute(preset: ComputePreset): void;
  onHistory(filter: { region: string; version: string }): void;
}) {
  const [versionId, setVersionId] = useState(region.versions[0].verdict.version_id);
  const [deciding, setDeciding] = useState(false);
  const entry = region.versions.find((v) => v.verdict.version_id === versionId) ?? region.versions[0];
  const v = entry.verdict;
  const top = v.highest_priority_issue;
  const meaning = rules?.verdict_meanings[v.verdict] ?? "A recommendation computed by rules. Not an approval.";
  const titleId = `region-${region.region_code}`;

  return (
    <Reveal as="article" index={index} aria-labelledby={titleId} className="clay overflow-hidden rounded-card border border-border">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border px-5 py-3.5">
        <h3 id={titleId} className="type-title text-[22px] text-ink">
          {region.region_name}
        </h3>
        <span className="font-mono text-[12px] text-ink-muted">{region.region_code}</span>
        {region.versions.length > 1 && (
          <div role="group" aria-label={`Versions in ${region.region_name}`} className="ml-auto flex flex-wrap gap-1.5">
            {region.versions.map((x) => {
              const on = x.verdict.version_id === v.version_id;
              return (
                <button
                  key={x.verdict.version_id}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setVersionId(x.verdict.version_id)}
                  className={cn(
                    "inline-flex min-h-8 items-center gap-2 rounded-lg border px-2.5 text-[13px] transition-colors",
                    on ? "border-border-strong bg-surface-raised font-medium text-ink shadow-clay" : "border-border text-ink-secondary hover:bg-surface-muted",
                  )}
                >
                  <span className="max-w-[14ch] truncate">{x.verdict.score.label}</span>
                  <Verdict value={x.verdict.verdict} />
                </button>
              );
            })}
          </div>
        )}
      </header>

      <div className="grid gap-x-8 gap-y-4 px-5 py-5 lg:grid-cols-[13rem_minmax(0,1fr)]">
        <div className="space-y-2.5">
          <VerdictStamp key={v.version_id} value={v.verdict} size="lg" delay={280 + index * 220} />
          <p className="max-w-[26ch] text-[12.5px] text-ink-secondary">{meaning}</p>
          <p className="type-meta" title={formatDateTime(v.computed_at)}>
            {v.score.label} · computed {formatRelative(v.computed_at)} · rules {v.rule_version}
          </p>
        </div>
        <LedgerList
          className="bg-transparent"
          rows={[
            { label: "Main reason", value: v.main_reason },
            {
              label: "Highest-priority issue",
              muted: !top,
              value: top ? (
                <>
                  <span className="font-mono text-[12.5px] text-ink">{top.rule_id}</span> {top.summary}
                </>
              ) : (
                "No rule fired, so there is no open issue."
              ),
            },
            { label: "Next action", value: <span className="text-ink">{v.next_action}</span> },
            {
              label: "Open conflicts",
              muted: v.open_conflicts.length === 0,
              value: v.open_conflicts.length === 0 ? "None supplied" : `${v.open_conflicts.length} listed, ${v.open_conflicts.filter((c) => c.relied_on).length} on claims this creative relies on`,
            },
            {
              label: "Evidence and risk",
              value: (
                <>
                  Evidence for the region: {v.evidence_strength ? STRENGTH[v.evidence_strength] : "unknown (no reading supplied)"}. Open findings: {v.risk.open_high} high,{" "}
                  {v.risk.open_medium} medium, {v.risk.open_low} low{v.risk.blocking ? `, ${v.risk.blocking} blocking Go` : ""}.
                </>
              ),
            },
          ]}
        />
      </div>

      <div className="border-t border-border bg-surface-muted/40 px-5 py-4">
        <ApprovalLine approval={entry.latest_approval} verdict={v} />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" disabled={!caps.canDecide} onClick={() => setDeciding(true)}>
            <Gavel aria-hidden />
            Record a decision
          </Button>
          <Button size="sm" variant="ghost" disabled={!caps.canCompute} onClick={() => onRecompute({ regionCode: region.region_code, versionId: v.version_id })}>
            <Gauge aria-hidden />
            Recompute with new inputs
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onHistory({ region: region.region_code, version: v.version_id })}>
            <History aria-hidden />
            History ({entry.history_count})
          </Button>
        </div>
        {!caps.loading && caps.reason && (!caps.canDecide || !caps.canCompute) && <p className="mt-2 max-w-[68ch] text-[12.5px] text-ink-secondary">{caps.reason}</p>}
      </div>

      <Disclosure title="Rules that fired" count={v.issues.length === 0 ? "none" : v.issues.length} defaultOpen>
        {v.issues.length === 0 ? (
          <p className="max-w-[68ch] text-[13.5px] text-ink-body">
            No blocking rule fired, so the verdict is Go (<span className="font-mono text-[12.5px]">{v.rules_applied[0]}</span>).
          </p>
        ) : (
          <ul className="ledger-rules rounded-card border border-border">
            {v.issues.map((issue, i) => (
              <FiredRule key={issue.rule_id} issue={issue} first={i === 0} rules={rules} />
            ))}
          </ul>
        )}
      </Disclosure>

      {v.open_conflicts.length > 0 && (
        <Disclosure title="Open evidence conflicts" count={v.open_conflicts.length}>
          <ul className="ledger-rules rounded-card border border-border">
            {v.open_conflicts.map((c) => (
              <li key={c.conflict_id} className="flex items-start gap-2.5 px-4 py-2.5 text-[13.5px]">
                <GitCompareArrows aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" />
                <span className="min-w-0 flex-1 text-ink-body">
                  {c.summary}
                  {c.claim_ids.length > 0 && <span className="type-meta block">Claims {c.claim_ids.map(shortId).join(", ")}</span>}
                </span>
                <span className="flex shrink-0 flex-wrap justify-end gap-1.5">
                  <Tag className="border-warning/35 bg-warning-soft text-warning">{CONFLICT_STATE[c.status ?? "open"]}</Tag>
                  {c.relied_on && <Tag className="border-border-strong/60 bg-surface-raised text-ink">The creative relies on it</Tag>}
                </span>
              </li>
            ))}
          </ul>
        </Disclosure>
      )}

      <Disclosure title="Confidence limitations" count={v.confidence_limitations.length}>
        <LimitationList items={v.confidence_limitations} title="What limits trust in this verdict" />
      </Disclosure>

      <Disclosure title="Score and record" count={`${v.scoring_version}, overall ${v.score.overall === null ? "not computed" : v.score.overall.toFixed(1)}`}>
        <div className="space-y-4">
          <ScoreCardList card={v.score} />
          <dl className="type-ledger grid gap-x-4 gap-y-1 text-[12.5px] sm:grid-cols-[9rem_minmax(0,1fr)]">
            <dt className="text-ink-muted">Rule version</dt>
            <dd className="font-mono text-ink-body">{v.rule_version}</dd>
            <dt className="text-ink-muted">Scoring version</dt>
            <dd className="font-mono text-ink-body">{v.scoring_version}</dd>
            <dt className="text-ink-muted">Input fingerprint</dt>
            <dd className="font-mono text-ink-body" title={v.input_fingerprint}>{v.input_fingerprint.slice(0, 16)}</dd>
            <dt className="text-ink-muted">Computed by</dt>
            <dd className="text-ink-body">
              <span className="font-mono">{shortId(v.computed_by)}</span> · {formatDateTime(v.computed_at)}
            </dd>
            <dt className="text-ink-muted">Observations from</dt>
            <dd className="text-ink-body">
              {[shownModel(v.provenance.model_id), v.provenance.prompt_version, v.provenance.criteria_version, shownModel(v.provenance.evidence_snapshot)].filter(Boolean).join(" · ") || "Not recorded"}
            </dd>
          </dl>
        </div>
      </Disclosure>

      <ApprovalDialog campaignId={campaignId} verdict={v} open={deciding} onOpenChange={setDeciding} />
    </Reveal>
  );
}
