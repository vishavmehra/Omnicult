"use client";

import { Check, Minus, Save, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Tag } from "@/components/evidence/badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Verdict } from "@/components/workflow/verdict";
import { Button } from "@/components/ui/button";
import { useCapabilities } from "@/features/launch/api";
import { formatSpan, formatValue } from "@/features/pulse/logic";
import { Section, Segmented } from "@/features/pulse/ui";
import { ApiError } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";

import { usePredictedActual, useSaveSnapshot, useSnapshots } from "./api";
import { VersionLinks } from "./version-links";
import {
  AGREEMENT_HELP, AGREEMENT_LABEL, formatRank, PVA_METRICS, snapshotNote, summaryDetail, summaryHeadline, type PvaCheck, type PvaMetric, type PvaPair, type PvaSummary,
} from "./logic";
import { PulseTabPage } from "./ui";

const CAVEAT = "This shows the method working; it does not show that the panel is calibrated.";

function AgreementTag({ agreement }: { agreement: PvaCheck["agreement"] }) {
  const tone = agreement === "agree" ? "border-success/25 bg-success-soft text-success" : agreement === "near" ? "border-border bg-surface-muted text-ink" : "border-warning/30 bg-warning-soft text-warning";
  const Icon = agreement === "agree" ? Check : agreement === "near" ? Minus : TriangleAlert;
  return (
    <Tag className={tone} title={AGREEMENT_HELP[agreement]}>
      <Icon aria-hidden />
      {AGREEMENT_LABEL[agreement]}
    </Tag>
  );
}

function RankLine({ check, label }: { check: PvaCheck | null; label: string }) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className="w-20 text-[11.5px] text-ink-muted">{label}</span>
      {check ? (
        <>
          <span className="type-ledger text-[12.5px] text-ink-body">
            Predicted <span className="font-semibold text-ink">{formatRank(check.predicted_rank)}</span>, actual <span className="font-semibold text-ink">{formatRank(check.actual_rank)}</span>
          </span>
          <AgreementTag agreement={check.agreement} />
        </>
      ) : (
        <span className="text-[12px] text-ink-muted">Not ranked</span>
      )}
    </div>
  );
}

function SummaryCard({ s }: { s: PvaSummary }) {
  return (
    <section aria-label={s.label} className="space-y-1.5 rounded-card border border-border bg-surface px-4 py-3.5">
      <p className="text-[12px] font-medium text-ink-secondary">{s.label}</p>
      <p className="text-[15px] leading-snug font-semibold text-ink">{summaryHeadline(s)}</p>
      <p className="text-[12.5px] leading-snug text-ink-secondary">{summaryDetail(s)}</p>
    </section>
  );
}

function PairsTable({ pairs, metricLabel, unit, names }: { pairs: PvaPair[]; metricLabel: string; unit: "ratio" | "multiple"; names: (code: string) => string }) {
  return (
    <div className="overflow-x-auto rounded-card border border-border bg-surface">
      <table className="type-ledger w-full min-w-[46rem] text-left text-[12.5px]">
        <caption className="sr-only">
          Each compared pair: the stored prediction (Launch Room verdict and score, Quick Read), the settled Pulse result for {metricLabel}, and how the two rankings agree.
        </caption>
        <thead className="bg-surface-muted text-ink-secondary">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Region and version</th>
            <th scope="col" className="px-3 py-2 font-medium">Launch Room</th>
            <th scope="col" className="px-3 py-2 font-medium">Quick Read</th>
            <th scope="col" className="px-3 py-2 font-medium">Actual {metricLabel}</th>
            <th scope="col" className="px-3 py-2 font-medium">Ranks, 1 is highest</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {pairs.map((p) => {
            const qr = p.predicted.quick_read;
            return (
              <tr key={`${p.region_code}|${p.pulse_version}`} className="align-top">
                <th scope="row" className="px-3 py-2.5 font-normal text-ink">
                  <span className="block font-medium">{names(p.region_code)}</span>
                  <span className="block text-[12px] text-ink-secondary">{p.pulse_version}</span>
                  <span className="block text-[11.5px] text-ink-muted">Studio: {p.studio_label}</span>
                </th>
                <td className="px-3 py-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Verdict value={p.predicted.verdict} />
                    <span className="font-semibold text-ink tabular-nums">{p.predicted.overall_score === null ? "n/a" : p.predicted.overall_score.toFixed(1)}</span>
                  </div>
                  <p className="mt-1 text-[11.5px] text-ink-muted">Stored {formatDateTime(p.predicted.computed_at)}</p>
                </td>
                <td className="px-3 py-2.5 text-ink-body">
                  {qr ? (
                    <>
                      <span className="font-semibold text-ink tabular-nums">{qr.positive} of {qr.respondents}</span> positive
                      <span className="block text-[11.5px] text-ink-muted">{Math.round(qr.favourable_share * 100)}% of respondents</span>
                    </>
                  ) : (
                    <span className="text-ink-muted">No Quick Read stored</span>
                  )}
                </td>
                <td className="px-3 py-2.5">
                  <span className="font-semibold text-ink tabular-nums">{formatValue(p.actual.value, unit)}</span>
                  <span className="block text-[11.5px] text-ink-muted">{formatSpan(p.actual.window_from, p.actual.window_to)}, {p.actual.settled_days} settled days</span>
                </td>
                <td className="space-y-1.5 px-3 py-2.5">
                  <RankLine check={p.launch_score} label="Launch score" />
                  <RankLine check={p.quick_read_favourable} label="Quick Read" />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function History({ campaignId }: { campaignId: string }) {
  const snapshots = useSnapshots(campaignId);
  if (snapshots.error) return <ErrorState error={snapshots.error} onRetry={() => void snapshots.refetch()} />;
  if (!snapshots.data) return <LoadingState label="Reading stored comparisons…" />;
  if (snapshots.data.items.length === 0) {
    return <p className="text-[13px] text-ink-secondary">Nothing stored yet. Save a comparison to keep it with the inputs it read.</p>;
  }
  return (
    <ul className="ledger-rules rounded-card border border-border bg-surface">
      {snapshots.data.items.map((s) => (
        <li key={s.id} className="flex flex-wrap items-start gap-x-4 gap-y-1 px-4 py-3">
          <div className="min-w-0 flex-1 space-y-0.5">
            <p className="text-[13.5px] text-ink">
              <span className="font-medium">{PVA_METRICS.find((m) => m.value === s.metric)?.label ?? s.metric}</span> · {s.pair_count} {s.pair_count === 1 ? "pair" : "pairs"} · stored {formatDateTime(s.created_at)}
            </p>
            <p className="text-[12.5px] text-ink-secondary">{snapshotNote(s.matches_current)}</p>
            <p className="font-mono text-[11px] break-all text-ink-muted" title="SHA-256 of the inputs and the method version">
              {s.method_version} · {s.fingerprint.slice(0, 16)}
            </p>
          </div>
          <Tag className={s.matches_current ? "border-success/25 bg-success-soft text-success" : "border-warning/30 bg-warning-soft text-warning"}>
            {s.matches_current ? <Check aria-hidden /> : <TriangleAlert aria-hidden />}
            {s.matches_current ? "Reproduces" : "Inputs changed"}
          </Tag>
        </li>
      ))}
    </ul>
  );
}

/** Predicted vs Actual (feature 44): stored predictions ranked against settled Pulse results, with the method and the pairs shown. */
export function PredictedActualTab({ campaignId }: { campaignId: string }) {
  const [metric, setMetric] = useState<PvaMetric>("ctr");
  const pva = usePredictedActual(campaignId, metric);
  const caps = useCapabilities();
  const save = useSaveSnapshot(campaignId);
  const data = pva.data;
  const names = (code: string) => data?.pairs.find((p) => p.region_code === code)?.region_name ?? code;
  const unit = data?.unit === "multiple" ? "multiple" : "ratio";

  const onSave = () =>
    save.mutate(metric, {
      onSuccess: (s) => toast.success(`Comparison stored: ${s.pair_count} ${s.pair_count === 1 ? "pair" : "pairs"}, fingerprint ${s.fingerprint.slice(0, 8)}.`),
      onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not store the comparison."),
    });

  return (
    <PulseTabPage>
      <Section id="pva" title="Predicted vs Actual">
        <p className="type-meta max-w-[78ch]">{CAVEAT}</p>
        <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
          <div className="space-y-1">
            <p className="text-[12px] font-medium text-ink-secondary">Compared with</p>
            <Segmented label="Pulse metric" value={metric} onChange={setMetric} options={PVA_METRICS.map((m) => ({ value: m.value, label: m.label }))} />
          </div>
          <Button variant="outline" size="sm" disabled={!caps.canCompute || !data || data.pairs.length === 0 || save.isPending} onClick={onSave} title={caps.reason ?? undefined}>
            <Save aria-hidden />
            Store this comparison
          </Button>
        </div>
        {pva.error && !data ? (
          <ErrorState error={pva.error} onRetry={() => void pva.refetch()} />
        ) : !data ? (
          <LoadingState label="Comparing stored predictions with the results…" />
        ) : data.pairs.length === 0 ? (
          <EmptyState
            title="No pair to compare yet"
            description="A pair is a Pulse version in one region that is linked to a Creative Studio version with a stored Launch Room verdict. Link the versions below; compute the verdicts in Launch Room first if a version has none."
            needs={[
              { label: "A Launch Room verdict for a Studio version in a region", met: false },
              { label: `${data.unlinked} version and region slots in the series are not linked`, met: data.unlinked === 0 },
            ]}
          />
        ) : (
          <div className="space-y-4" aria-busy={pva.isPlaceholderData}>
            <div className="grid gap-3 sm:grid-cols-2">
              {data.summaries.map((s) => (
                <SummaryCard key={s.predictor} s={s} />
              ))}
            </div>
            <PairsTable pairs={data.pairs} metricLabel={data.metric_label} unit={unit} names={names} />
            {data.excluded.length > 0 && (
              <div className="rounded-lg border border-border bg-surface-muted px-3.5 py-2.5">
                <p className="text-[12.5px] font-semibold text-ink">Not compared</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-5 text-[12.5px] text-ink-body marker:text-ink-secondary">
                  {data.excluded.map((e) => (
                    <li key={`${e.region_code}|${e.pulse_version}`}>
                      {names(e.region_code)}, {e.pulse_version}: {e.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Section>

      <Section id="links" title="Which Studio version ran where" meta={<span>Only linked versions are compared</span>}>
        <VersionLinks campaignId={campaignId} />
      </Section>

      <Section id="method" title="Method">
        {data ? (
          <details className="rounded-card border border-border bg-surface" open={data.pairs.length === 0}>
            <summary className="cursor-pointer px-4 py-2.5 text-[13px] text-ink-secondary hover:text-ink">How the comparison is made ({data.method.version})</summary>
            <div className="space-y-3 border-t border-border px-4 py-3 text-[13px] text-ink-body">
              <ol className="list-decimal space-y-1.5 pl-5 marker:text-ink-muted">
                {data.method.steps.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ol>
              <div>
                <p className="text-[12.5px] font-medium text-ink">What it assumes</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-5 text-[12.5px] text-ink-secondary marker:text-ink-muted">
                  {data.method.assumptions.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              </div>
              <p className="font-mono text-[11px] break-all text-ink-muted">Fingerprint {data.fingerprint}</p>
            </div>
          </details>
        ) : (
          <LoadingState label="Reading the method…" />
        )}
      </Section>

      <Section id="history" title="Stored comparisons" meta={<span>Each keeps the inputs it read</span>}>
        <History campaignId={campaignId} />
      </Section>
    </PulseTabPage>
  );
}
