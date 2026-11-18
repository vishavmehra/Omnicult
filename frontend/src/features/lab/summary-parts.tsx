"use client";

import { Sigma } from "lucide-react";
import { useMemo } from "react";

import { Tag } from "@/components/evidence/badges";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useSamplingOptions } from "./api";
import { Disclosure } from "./lab-parts";
import { RATING_LABEL, REACTIONS, pluralise } from "./labels";
import type { DimensionResult, GroundingSummary, RunMetadata } from "./types";

/** One calculated rating dimension: the score, its five-cell histogram, what it measures, and whether ratings diverge. */
export function RatingRow({ result }: { result: DimensionResult }) {
  const max = Math.max(1, ...result.distribution);
  return (
    <li className="space-y-2 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="text-[14px] font-medium text-ink">{RATING_LABEL[result.dimension] ?? result.dimension}</p>
        <p className="type-ledger text-[13px] text-ink-body">
          {result.score === null ? "No ratings" : <>Score {Math.round(result.score)} <span className="text-ink-muted">of 100</span></>}
          <span className="text-ink-muted"> · {result.higher_is_better ? "higher is better" : "lower is better"} · n {result.n}</span>
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
        <div role="img" aria-label={`Ratings 1 to 5 given by synthetic participants: ${result.distribution.join(", ")}`} className="flex items-end gap-1.5">
          {result.distribution.map((n, i) => (
            <div key={i} className="flex w-6 flex-col items-center gap-1">
              <span aria-hidden className="clay-well flex h-9 w-full items-end rounded-[4px] p-[2px]">
                <span className="block w-full rounded-[2px] bg-ink-secondary" style={{ height: `${(n / max) * 100}%`, minHeight: n ? 2 : 0 }} />
              </span>
              <span className="type-ledger text-[11.5px] text-ink-muted">
                {i + 1}
                <span className="sr-only"> rating</span>
              </span>
              <span className="type-ledger text-[12px] text-ink">{n}</span>
            </div>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Tag className="border-border bg-surface-muted text-ink" title="Computed by documented code from the synthetic ratings. Not a measurement of real people.">
            <Sigma aria-hidden />
            Calculated
          </Tag>
          {result.disagreement && <Tag className="border-warning/45 bg-warning-soft text-warning">Ratings diverge</Tag>}
        </div>
      </div>
      <p className="max-w-[68ch] text-[13px] leading-snug text-ink-secondary">
        {result.definition} {result.interpretation}
      </p>
    </li>
  );
}

/** A table of reaction counts per segment, counted from the stored responses. Zero is a dot so the real counts read first. */
export function SegmentTable({ groups }: { groups: { title: string; rows: { value: string; label: string; counts: Record<string, number>; total: number }[] }[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="type-ledger w-full min-w-[34rem] text-left text-[13px]">
        <thead className="text-[11.5px] text-ink-muted">
          <tr className="border-b border-border">
            <th scope="col" className="py-1.5 pr-3 font-medium">Segment</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Participants</th>
            {REACTIONS.map((r) => (
              <th key={r.key} scope="col" className="px-2 py-1.5 text-right font-medium">{r.label}</th>
            ))}
          </tr>
        </thead>
        {groups.map((g) => (
          <tbody key={g.title} className="divide-y divide-border border-b border-border last:border-b-0">
            <tr>
              <th scope="rowgroup" colSpan={7} className="pt-3 pb-1 text-left text-[12px] font-semibold text-ink-secondary">{g.title}</th>
            </tr>
            {g.rows.map((r) => (
              <tr key={r.value}>
                <th scope="row" className="py-1.5 pr-3 text-left font-normal text-ink">{r.label}</th>
                <td className="px-2 py-1.5 text-right text-ink-body">{r.total}</td>
                {REACTIONS.map(({ key }) => (
                  <td key={key} className={cn("px-2 py-1.5 text-right", r.counts[key] ? "text-ink" : "text-ink-muted")}>
                    {r.counts[key] || "·"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}

/** What the run was given to ground its statements on, and how many statements actually cite it. */
export function GroundingPanel({ grounding }: { grounding: GroundingSummary }) {
  const { claims_supplied: supplied, claim_supported_statements: cited, interpretation_statements: other } = grounding;
  const total = cited + other;
  const options = useSamplingOptions();
  const regionName = (code: string) => options.data?.states.find((s) => s.code === code)?.name ?? code;
  const byKind = useMemo(() => {
    const out: Record<string, number> = {};
    for (const c of grounding.claims) out[c.kind] = (out[c.kind] ?? 0) + 1;
    return out;
  }, [grounding.claims]);
  return (
    <div className="space-y-3">
      <p className="max-w-[68ch] text-[14px] leading-snug text-ink">
        {supplied === 0
          ? "This run was given no region claims, so none of its statements can be claim-supported. Every statement is a model interpretation."
          : total === 0
            ? `${pluralise(supplied, "claim")} supplied as context. No statement in this run is marked claim-supported.`
            : `${pluralise(cited, "statement")} of ${total} cite${cited === 1 ? "s" : ""} an observed or calculated claim from the ${pluralise(supplied, "claim")} supplied. The other ${other} ${other === 1 ? "is" : "are"} model interpretation.`}
      </p>
      <dl className="type-ledger grid gap-x-6 gap-y-1 text-[13px] sm:grid-cols-[auto_minmax(0,1fr)]">
        <dt className="text-ink-muted">Claims supplied</dt>
        <dd className="text-ink-body">
          {supplied}
          {supplied > 0 && <span className="text-ink-muted"> ({Object.entries(byKind).map(([k, n]) => `${n} ${k}`).join(", ")})</span>}
        </dd>
        <dt className="text-ink-muted">Evidence strength</dt>
        <dd className="text-ink-body">
          {Object.entries(grounding.evidence_strength).map(([code, s]) => `${regionName(code)}: ${s}`).join(" · ") || "Not rated"}
          <span className="text-ink-muted"> (Evidence Meter when the run started)</span>
        </dd>
        {total > 0 && (
          <>
            <dt className="text-ink-muted">Statements</dt>
            <dd className="text-ink-body">{cited} claim-supported · {other} interpretation</dd>
          </>
        )}
      </dl>
      <p className="max-w-[68ch] text-xs text-ink-secondary">
        A statement is claim-supported only when it cites an observed or calculated claim stored for the region. Every other statement is a model interpretation. Confidence on a claim comes from its sources, never from the model.
      </p>
    </div>
  );
}

/** How the run was produced: models, prompt versions, seed, cost estimate and every stage. Provenance for Proof Vault. */
export function Provenance({ meta, extra }: { meta: RunMetadata; extra?: { label: string; value: string }[] }) {
  const cost = meta.usage.estimated_cost_usd;
  const rows: { label: string; value: string }[] = [
    { label: "Mode", value: meta.mode === "demo" ? "Demo fixtures" : "Live" },
    { label: "Providers", value: meta.providers.join(", ") || "None" },
    { label: "Models", value: meta.model_ids.length ? meta.model_ids.join(", ") : meta.mode === "demo" ? "None: no model was called" : "Not reported" },
    { label: "Prompt versions", value: meta.prompt_versions.join(", ") || "None" },
    { label: "Seed", value: meta.seed === null ? "None" : String(meta.seed) },
    ...(extra ?? []),
    { label: "Started", value: formatDateTime(meta.started_at) },
    { label: "Finished", value: formatDateTime(meta.completed_at) },
    { label: "Cost estimate", value: cost === null ? "Not reported" : `US$ ${cost.toFixed(4)} (${meta.usage.cost_note})` },
  ];
  return (
    <Disclosure summary="How this was produced">
      <dl className="ledger-rules type-ledger rounded-md border border-border text-[13px]">
        {rows.map((r) => (
          <div key={r.label} className="grid gap-x-4 px-3 py-1.5 sm:grid-cols-[9rem_minmax(0,1fr)]">
            <dt className="text-ink-muted">{r.label}</dt>
            <dd className="min-w-0 break-words text-ink-body">{r.value}</dd>
          </div>
        ))}
      </dl>
      {meta.steps.length > 0 && (
        <div className="mt-2 overflow-x-auto rounded-md border border-border">
          <table className="type-ledger w-full min-w-[28rem] text-left text-[12.5px]">
            <thead className="bg-surface-muted text-[11.5px] text-ink-muted">
              <tr>
                <th scope="col" className="px-3 py-1.5 font-medium">Stage</th>
                <th scope="col" className="px-3 py-1.5 font-medium">Agent</th>
                <th scope="col" className="px-3 py-1.5 font-medium">Outcome</th>
                <th scope="col" className="px-3 py-1.5 font-medium">Provider</th>
                <th scope="col" className="px-3 py-1.5 text-right font-medium">Took</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {meta.steps.map((s, i) => (
                <tr key={i}>
                  <td className="px-3 py-1.5 text-ink">{s.stage.replace(/_/g, " ")}</td>
                  <td className="px-3 py-1.5 text-ink-body">{s.agent}</td>
                  <td className="px-3 py-1.5 text-ink-body">{s.status}{s.error_code ? ` (${s.error_code})` : ""}</td>
                  <td className="px-3 py-1.5 text-ink-body">{s.provider ?? "none"}</td>
                  <td className="px-3 py-1.5 text-right text-ink-body">{s.latency_ms === null || s.latency_ms === undefined ? "n/a" : `${s.latency_ms} ms`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Disclosure>
  );
}
