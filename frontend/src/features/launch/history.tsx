"use client";

import { ArrowRight, Gavel, TriangleAlert } from "lucide-react";
import { useMemo } from "react";

import { Tag } from "@/components/evidence/badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Verdict } from "@/components/workflow/verdict";
import { SectionTitle } from "@/features/workspaces/parts";
import { formatDateTime } from "@/lib/format";

import { useHistory } from "./api";
import { NativeSelect } from "./bits";
import type { Approval, ReadinessVerdict, VerdictValue } from "./types";

type Entry =
  | { kind: "verdict"; at: string; verdict: ReadinessVerdict; previous: VerdictValue | null }
  | { kind: "decision"; at: string; approval: Approval; versionLabel: string };

const DECISION_WORD = { approve: "Approved", request_changes: "Changes requested", reject: "Rejected" } as const;
const WORD = { go: "Go", fix: "Fix", rethink: "Rethink" } as const;

export type HistoryFilter = { region: string; version: string };

/**
 * The record of verdicts as a timeline, newest first, with the human decisions between them. Each verdict says what it replaced,
 * so a region's path (Rethink, then Fix, then Go) reads at a glance. Verdicts and decisions are append-only.
 */
export function HistoryTimeline({ campaignId, filter, onFilter }: { campaignId: string; filter: HistoryFilter; onFilter(next: HistoryFilter): void }) {
  const { verdicts, approvals } = useHistory(campaignId);

  const entries = useMemo(() => {
    const all = verdicts.data?.items ?? [];
    const labels = new Map(all.map((v) => [v.version_id, v.score.label]));
    const keep = (region: string, version: string) => (!filter.region || region === filter.region) && (!filter.version || version === filter.version);
    const rows: Entry[] = all
      .filter((v) => keep(v.region_code, v.version_id))
      .map((v) => {
        // The verdict this one replaced: the next older one for the same region and version.
        const older = all.find((o) => o.region_code === v.region_code && o.version_id === v.version_id && Date.parse(o.computed_at) < Date.parse(v.computed_at));
        return { kind: "verdict", at: v.computed_at, verdict: v, previous: older?.verdict ?? null };
      });
    for (const a of approvals.data?.items ?? []) {
      if (keep(a.region_code, a.version_id)) rows.push({ kind: "decision", at: a.decided_at, approval: a, versionLabel: labels.get(a.version_id) ?? "Version" });
    }
    return rows.sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  }, [verdicts.data, approvals.data, filter]);

  const regionOptions = useMemo(() => [...new Map((verdicts.data?.items ?? []).map((v) => [v.region_code, v.region_name])).entries()], [verdicts.data]);
  const versionOptions = useMemo(
    () => [...new Map((verdicts.data?.items ?? []).filter((v) => !filter.region || v.region_code === filter.region).map((v) => [v.version_id, v.score.label])).entries()],
    [verdicts.data, filter.region],
  );

  const error = verdicts.error ?? approvals.error;
  const total = verdicts.data?.total ?? 0;

  return (
    <section id="history" aria-labelledby="history-title" className="scroll-mt-24 space-y-3">
      <SectionTitle id="history-title" meta={verdicts.data ? `${total} ${total === 1 ? "verdict" : "verdicts"} stored` : undefined}>
        Verdict history
      </SectionTitle>

      {error ? (
        <ErrorState error={error} onRetry={() => { void verdicts.refetch(); void approvals.refetch(); }} />
      ) : verdicts.isPending || approvals.isPending ? (
        <LoadingState label="Reading the verdict history…" />
      ) : total === 0 ? (
        <EmptyState
          title="No verdicts have been stored yet"
          description="Every time a verdict is computed it is kept here with its inputs and the rules that produced it, so you can see how a region moved from Rethink to Fix to Go and what a decision was based on."
        />
      ) : (
        <>
          <div className="flex flex-wrap items-end gap-4">
            <div className="w-48 space-y-1">
              <label htmlFor="history-region" className="block text-[12.5px] text-ink-secondary">Region</label>
              <NativeSelect id="history-region" value={filter.region} onChange={(e) => onFilter({ region: e.target.value, version: "" })}>
                <option value="">All regions</option>
                {regionOptions.map(([code, name]) => (
                  <option key={code} value={code}>{name}</option>
                ))}
              </NativeSelect>
            </div>
            <div className="w-56 space-y-1">
              <label htmlFor="history-version" className="block text-[12.5px] text-ink-secondary">Version</label>
              <NativeSelect id="history-version" value={filter.version} onChange={(e) => onFilter({ ...filter, version: e.target.value })}>
                <option value="">All versions</option>
                {versionOptions.map(([id, label]) => (
                  <option key={id} value={id}>{label}</option>
                ))}
              </NativeSelect>
            </div>
          </div>
          {total > (verdicts.data?.items.length ?? 0) && (
            <p className="text-[12.5px] text-ink-secondary">Showing the newest {verdicts.data?.items.length} of {total} verdicts.</p>
          )}

          {entries.length === 0 ? (
            <p className="text-[13.5px] text-ink-secondary">Nothing matches this region and version.</p>
          ) : (
            <ol className="relative space-y-0 border-l border-border pl-0">
              {entries.map((e) => (
                <li key={e.kind === "verdict" ? e.verdict.id : e.approval.id} className="relative grid gap-x-4 gap-y-1 py-3 pl-6 sm:grid-cols-[11rem_minmax(0,1fr)]">
                  <span aria-hidden className="absolute top-[1.1rem] -left-[4.5px] size-2 rounded-full bg-border-strong ring-4 ring-canvas" />
                  <p className="type-ledger text-[12.5px] text-ink-muted" title={e.at}>{formatDateTime(e.at)}</p>
                  {e.kind === "verdict" ? (
                    <div className="min-w-0 space-y-1.5">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                        <Verdict value={e.verdict.verdict} />
                        <span className="text-[14px] font-medium text-ink">{e.verdict.region_name}</span>
                        <span className="text-[13px] text-ink-body">{e.verdict.score.label}</span>
                        {e.verdict.is_latest && <Tag className="border-border-strong/60 bg-surface-raised text-ink">Latest</Tag>}
                      </div>
                      <p className="flex flex-wrap items-center gap-1.5 text-[12.5px] text-ink-secondary">
                        {e.previous ? (
                          <>
                            {WORD[e.previous]}
                            <ArrowRight aria-hidden className="size-3.5" />
                            <span className="font-medium text-ink-body">{WORD[e.verdict.verdict]}</span>
                            {e.previous === e.verdict.verdict && <span>(inputs changed, verdict did not)</span>}
                          </>
                        ) : (
                          "First verdict for this version in this region"
                        )}
                        <span className="text-ink-muted">· rules {e.verdict.rule_version}</span>
                      </p>
                      <p className="max-w-[72ch] text-[13.5px] text-ink-body">{e.verdict.main_reason}</p>
                    </div>
                  ) : (
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                        <span className="inline-flex items-center gap-1.5 text-[13.5px] font-semibold text-ink">
                          <Gavel aria-hidden className="size-4" />
                          {DECISION_WORD[e.approval.decision]}
                        </span>
                        <span className="text-[13px] text-ink-body">
                          {e.approval.region_code} · {e.versionLabel} · by {e.approval.decided_by_name ?? "a team member"}
                        </span>
                        {e.approval.overrides_recommendation && (
                          <Tag className="border-warning/40 bg-warning-soft font-semibold text-warning">
                            <TriangleAlert aria-hidden />
                            Overrides recommendation{e.approval.verdict_at_decision ? `: it was ${WORD[e.approval.verdict_at_decision]}` : ""}
                          </Tag>
                        )}
                      </div>
                      <p className="max-w-[72ch] text-[13.5px] text-ink-body">{e.approval.reason}</p>
                    </div>
                  )}
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </section>
  );
}
