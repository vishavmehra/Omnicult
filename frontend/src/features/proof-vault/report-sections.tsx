"use client";

import { Bot, ChevronRight, CircleCheck, Hand, Info, OctagonAlert, TriangleAlert } from "lucide-react";
import { createContext, useContext, type ReactNode } from "react";

import { ConflictCard, type ConflictSide } from "@/components/evidence/conflict-card";
import { Reveal, RingGauge } from "@/components/creative";
import { EvidenceMeter } from "@/components/evidence/evidence-meter";
import type { ClaimKind } from "@/components/evidence/evidence-row";
import { RunStatusBadge } from "@/components/workflow/run-status";
import { Verdict } from "@/components/workflow/verdict";
import { CreativeMat, LedgerList } from "@/features/workspaces/parts";
import type { DataMode } from "@/lib/api/types";
import { formatDate, formatDateTime, formatElapsed, humanize, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useClaim } from "./api";
import { Absent, ClaimChips, ClaimRow, Fact, formatCount, formatUsd, Kind, scopeOf, sourceLabel, StrengthStamp } from "./parts";
import type { ClaimView, ProofReport, ProofSection, ProofView, ReportConflict, SectionId, SectionOf } from "./types";

type Content<Id extends SectionId> = NonNullable<SectionOf<Id>["content"]>;

export type ReportContext = {
  report: ProofReport;
  workspaceId: string | null;
  mode: DataMode;
  openClaim?: (claimId: string) => void;
  openView: (view: ProofView) => void;
};
const Ctx = createContext<ReportContext | null>(null);
export const ReportProvider = Ctx.Provider;
function useReport() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("Report sections render inside a ReportProvider.");
  return ctx;
}

const Rows = ({ children, className }: { children: ReactNode; className?: string }) => (
  <ul className={cn("ledger-rules rounded-card border border-border bg-surface", className)}>{children}</ul>
);
const Row = ({ children }: { children: ReactNode }) => <li className="space-y-1.5 px-4 py-3">{children}</li>;

const clock = (ms: number) => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`;

function anchorText(anchor: { scene_id?: string | null; start_ms?: number | null; end_ms?: number | null; bbox?: unknown[] | null } | null) {
  if (!anchor) return null;
  const parts = [
    anchor.scene_id ? `Scene ${anchor.scene_id}` : null,
    anchor.start_ms != null ? `${clock(anchor.start_ms)}${anchor.end_ms != null ? ` to ${clock(anchor.end_ms)}` : ""}` : null,
    anchor.bbox?.length ? "marked region" : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

// --- campaign brief and regions ---------------------------------------------------------------------------------

function BriefBody({ c }: { c: Content<"campaign_brief"> }) {
  const terms = (label: string, list: string[]) => (list.length ? { label, value: list.join(", ") } : null);
  const w = c.evaluation_weights;
  const rows = [
    { label: "Campaign", value: c.name },
    { label: "Type", value: humanize(c.campaign_type) },
    { label: "Objective", value: c.objective ?? "Not set", muted: !c.objective },
    {
      label: "Target markets",
      value: c.target_markets.length ? c.target_markets.map((m) => `${m.display_name}${m.region_code ? ` (${m.region_code})` : ""}`).join(", ") : "None set",
      muted: !c.target_markets.length,
    },
    { label: "Content version", value: `v${c.current_version.version_number} of ${c.version_count}, saved ${formatDateTime(c.current_version.created_at)}` },
    { label: "Brand", value: c.brand.name },
    terms("Brand voice", c.brand.voice),
    c.brand.target_audience ? { label: "Audience", value: c.brand.target_audience } : null,
    terms("Preferred terms", c.brand.preferred_terms),
    terms("Prohibited terms", c.brand.prohibited_terms),
    terms("Protected terms", c.brand.protected_terms),
    {
      label: "Importance weights",
      value: `Clarity ${w.clarity} · Brand fidelity ${w.brand_fidelity} · Cultural relevance ${w.cultural_relevance} · Cultural risk ${w.cultural_risk} (they sum to 1)`,
    },
  ].filter((r): r is { label: string; value: string; muted?: boolean } => r !== null);
  return (
    <div className="space-y-4">
      <LedgerList rows={rows} />
      <div className="space-y-1.5">
        <p className="type-meta">The creative this snapshot describes</p>
        <CreativeMat content={c.current_version.content} size="sm" />
      </div>
    </div>
  );
}

function RegionsBody({ c }: { c: Content<"target_regions"> }) {
  return (
    <div className="space-y-3">
      <p className="text-[13px] text-ink-secondary">{c.source === "campaign" ? "Taken from the campaign's target regions." : "Chosen for this report."}</p>
      {c.regions.length > 0 ? (
        <Rows>
          {c.regions.map((r) => (
            <Row key={r.id}>
              <p className="flex flex-wrap items-baseline gap-x-2 text-[14.5px] font-medium text-ink">
                {r.name}
                <span className="font-mono text-[11.5px] font-normal text-ink-muted">{r.code}</span>
                <span className="text-[12.5px] font-normal text-ink-muted">{r.kind === "state" ? "State" : "Union territory"}</span>
              </p>
              <p className="type-ledger flex flex-wrap gap-x-4 gap-y-0.5 text-[13px] text-ink-body">
                {r.languages.map((l) => (
                  <span key={l.code}>
                    <span lang={l.code}>{l.native_name ?? l.name}</span>
                    <span className="text-ink-muted">
                      {" "}
                      {l.name !== l.native_name ? `${l.name}, ` : ""}
                      {l.script}, {l.role.replace("_", "-")}
                    </span>
                  </span>
                ))}
              </p>
            </Row>
          ))}
        </Rows>
      ) : (
        <Absent title="No regions were reported on">Choose regions when generating a snapshot, or set target regions on the campaign.</Absent>
      )}
      {c.unknown_codes.length > 0 && (
        <p className="flex items-start gap-1.5 text-[13px] text-warning">
          <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          Not reported on, because no active region matches: <span className="font-mono">{c.unknown_codes.join(", ")}</span>.
        </p>
      )}
    </div>
  );
}

function ClaimsBody({ c }: { c: Content<"region_claims"> }) {
  const { openClaim } = useReport();
  return (
    <div className="space-y-5">
      <p className="type-meta">
        {formatCount(c.claim_count)} {c.claim_count === 1 ? "claim" : "claims"}
        {Object.entries(c.kind_counts)
          .filter(([, n]) => n > 0)
          .map(([k, n]) => ` · ${humanize(k)} ${n}`)
          .join("")}
      </p>
      {c.regions.map((r) => {
        const filled = r.categories.filter((cat) => cat.claims.length > 0);
        const gaps = r.categories.filter((cat) => cat.claims.length === 0);
        return (
          <div key={r.region_code} className="space-y-2.5">
            <h4 className="flex flex-wrap items-baseline gap-x-2 text-[15px] font-semibold text-ink">
              {r.region_name}
              <span className="font-mono text-[11.5px] font-normal text-ink-muted">{r.region_code}</span>
              <span className="type-meta font-normal">{r.claim_count} claims</span>
            </h4>
            {filled.map((cat) => (
              <details key={cat.category} open={r.claim_count <= 12} className="group">
                <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-md py-1 text-[13.5px] font-medium text-ink-body marker:hidden">
                  <ChevronRight aria-hidden className="size-4 text-ink-muted transition-transform group-open:rotate-90 motion-reduce:transition-none" />
                  {humanize(cat.category)}
                  <span className="type-meta font-normal">{cat.claims.length}</span>
                </summary>
                <div className="mt-1.5 space-y-2 pl-5">
                  {cat.claims.map((claim) => (
                    <ClaimRow key={claim.id} claim={claim} onOpen={openClaim} />
                  ))}
                </div>
              </details>
            ))}
            {gaps.length > 0 && (
              <p className="text-[13px] text-ink-secondary">
                <span className="font-medium text-ink-body">No claim recorded for: </span>
                {gaps.map((g) => humanize(g.category).toLowerCase()).join(", ")}. These are gaps in the record, not findings that nothing exists.
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

function MeterBody({ c }: { c: Content<"evidence_meter"> }) {
  const { report } = useReport();
  const claimsSection = report.sections.find((s): s is SectionOf<"region_claims"> => s.id === "region_claims");
  return (
    <div className="space-y-5">
      {c.meters.map((m) => {
        const block = claimsSection?.content?.regions.find((r) => r.region_code === m.region_code);
        const claims: ClaimView[] = block?.categories.flatMap((cat) => cat.claims) ?? [];
        const counts: Partial<Record<ClaimKind, number>> = {};
        for (const claim of claims) counts[claim.kind] = (counts[claim.kind] ?? 0) + 1;
        const groups = new Set(claims.flatMap((claim) => claim.sources.map((s) => s.independence_group))).size;
        return (
          <div key={m.region_code} className="space-y-3 rounded-card border border-border bg-surface px-4 py-3.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="flex items-baseline gap-2 text-[15px] font-semibold text-ink">
                {m.region_name}
                <span className="font-mono text-[11.5px] font-normal text-ink-muted">{m.region_code}</span>
              </h4>
              <StrengthStamp strength={m.strength} />
            </div>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
              {(m.claims > 0 || m.categories_total > 0) && (
                <div className="flex gap-4">
                  {m.claims > 0 && <RingGauge value={m.supported_claims} max={m.claims} size={84} tone="proof" label={`Supported claims in ${m.region_name}`} caption="supported" />}
                  {m.categories_total > 0 && <RingGauge value={m.categories_covered} max={m.categories_total} size={84} tone="proof" label={`Categories covered in ${m.region_name}`} caption="categories" />}
                </div>
              )}
              <div className="min-w-[16rem] flex-1">
                {block ? (
                  <EvidenceMeter counts={counts} independentGroups={groups} conflicts={m.open_conflicts} scopeLabel={m.region_name} />
                ) : (
                  <p className="text-[13px] text-ink-secondary">The claims behind this meter are not in the snapshot, so the kinds are not broken out.</p>
                )}
              </div>
            </div>
            {m.strength_reasons.length > 0 && (
              <ul className="list-disc space-y-0.5 pl-5 text-[13px] text-ink-body marker:text-ink-muted">
                {m.strength_reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 sm:grid-cols-4">
              <Fact label="Distinct sources">{m.sources}</Fact>
              <Fact label="Needing review">{m.needs_review_claims}</Fact>
              <Fact label="Open conflicts">{m.open_conflicts}</Fact>
              <Fact label="Stale claims">{m.stale_claims}</Fact>
              <Fact label="Newest source">{m.freshness.newest_source_date ? formatDate(m.freshness.newest_source_date) : "No dated source"}</Fact>
              <Fact label="Median source age">{m.freshness.median_age_days != null ? `${formatCount(m.freshness.median_age_days)} days` : "Not known"}</Fact>
            </dl>
            <p className="type-ledger text-[12.5px] text-ink-muted">
              Claim confidence: Low {m.confidence.low} · Moderate {m.confidence.moderate} · High {m.confidence.high}. A rule-based level, not a probability.
            </p>
          </div>
        );
      })}
    </div>
  );
}

// --- conflicts --------------------------------------------------------------------------------------------------

/** The claim record behind one side of a conflict, so the card shows its source, date and scope as stored. */
function useSide(claimId: string, snapshot: ReportConflict["side_a"]): ConflictSide {
  const { workspaceId, openClaim } = useReport();
  const claim = useClaim(workspaceId, claimId).data;
  const first = claim ? sourceLabel(claim) : null;
  const scope = claim ? scopeOf(claim.scope) : null;
  return {
    value: openClaim ? (
      <button type="button" onClick={() => openClaim(claimId)} className="rounded-sm text-left underline-offset-2 hover:underline">
        {snapshot.value_text}
      </button>
    ) : (
      snapshot.value_text
    ),
    source: first?.label ?? `${snapshot.source_count} ${snapshot.source_count === 1 ? "source" : "sources"}`,
    url: first?.url,
    date: claim ? (claim.published_at ?? claim.retrieved_at) : null,
    scope: scope ? [scope.region, scope.language, scope.cityTier, scope.period].filter(Boolean).join(" · ") || "Country-wide" : `${humanize(snapshot.kind)}, ${snapshot.confidence} confidence`,
  };
}

function ReportConflictCard({ c }: { c: ReportConflict }) {
  const a = useSide(c.side_a.claim_id, c.side_a);
  const b = useSide(c.side_b.claim_id, c.side_b);
  const resolved = c.status === "resolved";
  const review = c.status === "review_requested";
  return (
    <ConflictCard
      subject={
        <>
          {c.reason}
          {c.region_code && <span className="ml-2 font-mono text-[11.5px] font-normal text-ink-muted">{c.region_code}</span>}
        </>
      }
      a={a}
      b={b}
      recommended={c.current_selection}
      reason={
        <>
          {c.selection_reason}
          {review && " A native review has been requested."}
        </>
      }
      resolved={
        resolved || c.decisions.length > 0 ? (
          <>
            {c.decisions.map((d) => (
              <span key={d.id} className="block">
                {formatDateTime(d.decided_at)}: {d.decision === "accept" ? "kept" : d.decision === "switch" ? "switched to" : "asked for a review, using"} value {d.selection_after.toUpperCase()}
                {d.note ? `. ${d.note}` : "."}
              </span>
            ))}
          </>
        ) : undefined
      }
    />
  );
}

function ConflictsBody({ c }: { c: Content<"conflicts"> }) {
  return (
    <div className="space-y-4">
      {c.open.length === 0 ? (
        <p className="flex items-center gap-1.5 text-[13.5px] text-ink-body">
          <CircleCheck aria-hidden className="size-4 text-success" />
          No open conflicts in this snapshot.
        </p>
      ) : (
        c.open.map((x) => <ReportConflictCard key={x.id} c={x} />)
      )}
      {c.resolved.length > 0 && (
        <details className="group space-y-3">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[13.5px] font-medium text-ink-body marker:hidden">
            <ChevronRight aria-hidden className="size-4 text-ink-muted transition-transform group-open:rotate-90 motion-reduce:transition-none" />
            Resolved conflicts <span className="type-meta font-normal">{c.resolved.length}</span>
          </summary>
          <div className="space-y-4 pt-3">
            {c.resolved.map((x) => (
              <ReportConflictCard key={x.id} c={x} />
            ))}
          </div>
        </details>
      )}
      {c.truncated && <p className="text-[12.5px] text-warning">A region had more conflicts than a report carries; the list above is not complete.</p>}
    </div>
  );
}

// --- sections other workspaces provide -----------------------------------------------------------------------------

function VersionsBody({ c }: { c: Content<"creative_versions"> }) {
  const { openClaim } = useReport();
  return (
    <div className="space-y-3">
      {c.comparison_summary && <p className="max-w-[68ch] text-[14px] text-ink-body">{c.comparison_summary}</p>}
      <Rows>
        {c.versions.map((v) => (
          <Row key={v.version_id}>
            <p className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <span className="text-[14.5px] font-medium text-ink">{v.label}</span>
              <Kind kind={v.kind} />
            </p>
            <p className="type-meta">
              {v.operation ? humanize(v.operation) : "Version"}
              {v.actor && ` by ${v.actor === "ai" ? "the model" : "a person"}`}
              {v.created_at && ` · ${formatDateTime(v.created_at)}`}
            </p>
            <p className="max-w-[68ch] text-[13.5px] text-ink-body">{v.summary}</p>
            <ClaimChips ids={v.claim_ids} onOpen={openClaim} />
          </Row>
        ))}
      </Rows>
    </div>
  );
}

function XRayBody({ c }: { c: Content<"xray_findings"> }) {
  const { openClaim } = useReport();
  return (
    <Rows>
      {c.findings.map((f) => (
        <Row key={f.id}>
          <p className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <span className="max-w-[68ch] text-[14px] text-ink">{f.observation}</span>
            <Kind kind={f.kind} />
          </p>
          <p className="type-meta">
            {anchorText(f.anchor) ?? "Not tied to a moment or region"}
            {f.confidence && ` · Confidence: ${humanize(f.confidence)}`}
          </p>
          <ClaimChips ids={f.claim_ids} onOpen={openClaim} />
        </Row>
      ))}
    </Rows>
  );
}

const SEVERITY = {
  high: { label: "High", Icon: OctagonAlert, className: "text-danger" },
  medium: { label: "Medium", Icon: TriangleAlert, className: "text-warning" },
  low: { label: "Low", Icon: Info, className: "text-ink-secondary" },
} as const;

function RiskBody({ c }: { c: Content<"risk_findings"> }) {
  return (
    <div className="space-y-3">
      <Rows>
        {c.findings.map((f) => {
          const sev = SEVERITY[f.severity];
          return (
            <Row key={f.id}>
              <p className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <span className={cn("inline-flex items-center gap-1.5 text-[13px] font-semibold", sev.className)}>
                  <sev.Icon aria-hidden className="size-4" />
                  {sev.label} risk
                  <span className="font-normal text-ink-secondary">{humanize(f.category)}</span>
                </span>
                <Kind kind={f.kind} />
              </p>
              <p className="max-w-[68ch] text-[14px] text-ink">{f.description}</p>
              <p className="type-meta">
                {anchorText(f.anchor) ?? "Not tied to a moment or region"}
                {f.ad_code_ref && ` · Ad code ${f.ad_code_ref}`}
                {f.status && ` · ${humanize(f.status)}`}
              </p>
            </Row>
          );
        })}
      </Rows>
      <p className="max-w-[68ch] text-[12.5px] text-ink-muted">{c.disclaimer}</p>
    </div>
  );
}

function TranscreationBody({ c }: { c: Content<"transcreation"> }) {
  const { openClaim } = useReport();
  return (
    <Rows>
      {c.items.map((t) => (
        <Row key={t.id}>
          <p className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <span className="text-[14.5px] font-medium text-ink">
              {t.region_code}
              {t.language && <span className="ml-2 font-mono text-[11.5px] font-normal text-ink-muted">{t.language}</span>}
            </span>
            <Kind kind={t.kind} />
          </p>
          <p className="max-w-[68ch] text-[14px] text-ink-body">{t.summary}</p>
          {t.back_translation && (
            <p className="max-w-[68ch] text-[13px] text-ink-secondary" lang="en">
              <span className="font-medium text-ink-body">Back-translation: </span>
              {t.back_translation}
            </p>
          )}
          {t.glossary_issues.length > 0 && (
            <ul className="list-disc pl-5 text-[13px] text-warning">
              {t.glossary_issues.map((g, i) => (
                <li key={i}>{g}</li>
              ))}
            </ul>
          )}
          <ClaimChips ids={t.claim_ids} onOpen={openClaim} />
        </Row>
      ))}
    </Rows>
  );
}

function AudienceBody({ c }: { c: Content<"audience_results"> }) {
  return (
    <div className="space-y-3">
      <Rows>
        {c.results.map((r) => (
          <Row key={r.id}>
            <p className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <span className="text-[14.5px] font-medium text-ink">
                {r.method === "quick_read" ? "Quick Read" : "Ask the Panel"}
                {r.region_code && <span className="ml-2 font-mono text-[11.5px] font-normal text-ink-muted">{r.region_code}</span>}
              </span>
              <span className="type-meta inline-flex items-center gap-1">
                <Bot aria-hidden className="size-3.5" />
                {r.respondent_count} synthetic respondents
              </span>
            </p>
            <p className="max-w-[68ch] text-[14px] text-ink-body">{r.summary}</p>
            {r.disagreement && (
              <p className="max-w-[68ch] text-[13px] text-ink-secondary">
                <span className="font-medium text-ink-body">Where they disagreed: </span>
                {r.disagreement}
              </p>
            )}
            {r.limitations.length > 0 && (
              <ul className="list-disc pl-5 text-[12.5px] text-ink-muted">
                {r.limitations.map((l, i) => (
                  <li key={i}>{l}</li>
                ))}
              </ul>
            )}
          </Row>
        ))}
      </Rows>
      <p className="type-meta">Source: simulated panel. Respondents are synthetic, not real people, and not independent observations.</p>
    </div>
  );
}

function ReadinessBody({ c }: { c: Content<"readiness"> }) {
  return (
    <div className="space-y-3 rounded-card border border-border bg-surface px-4 py-4">
      <div className="flex flex-wrap items-center gap-3">
        <Verdict value={c.verdict} size="lg" />
        <Kind kind={c.kind} />
        <span className="type-meta">Rule version {c.rule_version}</span>
      </div>
      <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
        <Fact label="Main reason">{c.main_reason}</Fact>
        <Fact label="Next action">{c.next_action}</Fact>
        {c.highest_priority_issue && <Fact label="Highest priority issue">{c.highest_priority_issue}</Fact>}
        <Fact label="Open conflicts">{c.open_conflicts}</Fact>
      </dl>
      {c.confidence_limitations.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-[13px] text-ink-secondary marker:text-ink-muted">
          {c.confidence_limitations.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

const DECISION = { approved: "Approved", changes_requested: "Changes requested", rejected: "Rejected" } as const;

function ApprovalsBody({ c }: { c: Content<"approvals"> }) {
  return (
    <Rows>
      {c.approvals.map((a) => (
        <Row key={a.id}>
          <p className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <span className="inline-flex items-center gap-1.5 text-[14px] font-medium text-ink">
              <Hand aria-hidden className="size-4 text-ink-muted" />
              {DECISION[a.decision]}
              {a.role && <span className="font-normal text-ink-secondary">by {humanize(a.role)}</span>}
            </span>
            <Kind kind={a.kind} />
          </p>
          <p className="type-meta">
            {formatDateTime(a.decided_at)}
            {a.version_id && ` · version ${shortId(a.version_id)}`}
          </p>
          {a.note && <p className="max-w-[68ch] text-[13.5px] text-ink-body">{a.note}</p>}
        </Row>
      ))}
    </Rows>
  );
}

function LiveBody({ c }: { c: Content<"live_performance"> }) {
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-card border border-border bg-surface">
        <table className="type-ledger w-full min-w-[30rem] text-left text-[13px]">
          <thead className="bg-surface-muted text-[11.5px] text-ink-muted">
            <tr>
              {["Region", "Metric", "Value", "Period", "Source", "Kind"].map((h) => (
                <th key={h} scope="col" className="px-3 py-2 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {c.items.map((it, i) => (
              <tr key={i}>
                <td className="px-3 py-2 font-mono text-[12px]">{it.region_code ?? "All"}</td>
                <td className="px-3 py-2">
                  {humanize(it.metric)}
                  {it.provisional && <span className="ml-1.5 text-[11.5px] text-warning">provisional</span>}
                </td>
                <td className="px-3 py-2 tabular-nums">{it.value ?? "Not reported"}</td>
                <td className="px-3 py-2 text-ink-secondary">{it.period ?? "n/a"}</td>
                <td className="px-3 py-2 text-ink-secondary">{it.source}</td>
                <td className="px-3 py-2">
                  <Kind kind={it.kind} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {c.sample_data && <p className="type-meta">Source: sample dataset.</p>}
    </div>
  );
}

function LimitationsBody({ c }: { c: Content<"limitations"> }) {
  return (
    <div className="space-y-3">
      <ul className="max-w-[72ch] list-disc space-y-1.5 pl-5 text-[14px] text-ink-body marker:text-ink-muted">
        {c.items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
      <p className="max-w-[72ch] rounded-card border border-border bg-surface-muted/60 px-4 py-3 text-[13.5px] text-ink-body">
        <span className="font-semibold text-ink">Not legal clearance. </span>
        {c.not_legal_clearance}
      </p>
    </div>
  );
}

function RunsBody({ c }: { c: Content<"run_history"> }) {
  const { openView } = useReport();
  const t = c.totals;
  return (
    <div className="space-y-3">
      <p className="type-ledger text-[13px] text-ink-body">
        {t.runs} {t.runs === 1 ? "run" : "runs"} · {formatCount(t.input_tokens)} input and {formatCount(t.output_tokens)} output tokens ·{" "}
        {t.runs_without_cost === t.runs ? "no cost recorded" : `${formatUsd(t.estimated_cost_usd)} estimated${t.runs_without_cost > 0 ? ` (a lower bound: ${t.runs_without_cost} runs have no recorded cost)` : ""}`}
        . Costs are estimates from a price table, not invoices; the provider&apos;s actual cost is not reported.
      </p>
      {c.runs.length > 0 && (
        <div className="overflow-x-auto rounded-card border border-border bg-surface">
          <table className="type-ledger w-full min-w-[34rem] text-left text-[13px]">
            <thead className="bg-surface-muted text-[11.5px] text-ink-muted">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Run</th>
                <th scope="col" className="px-3 py-2 font-medium">State</th>
                <th scope="col" className="px-3 py-2 font-medium">Models</th>
                <th scope="col" className="px-3 py-2 font-medium">Took</th>
                <th scope="col" className="px-3 py-2 font-medium">Estimated cost</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {c.runs.map((r) => (
                <tr key={r.run_id}>
                  <td className="px-3 py-2">
                    <span className="font-medium text-ink">{r.operation}</span>
                    <span className="ml-2 font-mono text-[11.5px] text-ink-muted">{shortId(r.run_id)}</span>
                  </td>
                  <td className="px-3 py-2"><RunStatusBadge status={r.status} /></td>
                  <td className="px-3 py-2 text-ink-secondary">{r.models.length ? r.models.join(", ") : "No model recorded"}</td>
                  <td className="px-3 py-2 tabular-nums text-ink-secondary">{r.duration_ms != null ? formatElapsed(r.duration_ms) : "not recorded"}</td>
                  <td className="px-3 py-2 tabular-nums text-ink-secondary">{r.estimated_cost_usd != null ? formatUsd(r.estimated_cost_usd) : "not recorded"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {c.truncated && <p className="text-[12.5px] text-warning">The report carries the newest runs only.</p>}
      <button type="button" onClick={() => openView("history")} className="inline-flex items-center gap-1 rounded-sm text-[13.5px] font-medium text-rose underline-offset-2 hover:underline">
        Open the full Run History
        <ChevronRight aria-hidden className="size-4" />
      </button>
    </div>
  );
}

// --- the section frame --------------------------------------------------------------------------------------------

function Body({ section }: { section: ProofSection }) {
  switch (section.id) {
    case "campaign_brief":
      return section.content && <BriefBody c={section.content} />;
    case "target_regions":
      return section.content && <RegionsBody c={section.content} />;
    case "region_claims":
      return section.content && <ClaimsBody c={section.content} />;
    case "evidence_meter":
      return section.content && <MeterBody c={section.content} />;
    case "conflicts":
      return section.content && <ConflictsBody c={section.content} />;
    case "creative_versions":
      return section.content && <VersionsBody c={section.content} />;
    case "xray_findings":
      return section.content && <XRayBody c={section.content} />;
    case "risk_findings":
      return section.content && <RiskBody c={section.content} />;
    case "transcreation":
      return section.content && <TranscreationBody c={section.content} />;
    case "audience_results":
      return section.content && <AudienceBody c={section.content} />;
    case "readiness":
      return section.content && <ReadinessBody c={section.content} />;
    case "approvals":
      return section.content && <ApprovalsBody c={section.content} />;
    case "live_performance":
      return section.content && <LiveBody c={section.content} />;
    case "limitations":
      return section.content && <LimitationsBody c={section.content} />;
    case "run_history":
      return section.content && <RunsBody c={section.content} />;
  }
}

/** One section of the report: its title, what kinds of content it holds, then its typed content or an honest absence. */
export function ReportSection({ section, wired, index = 0 }: { section: ProofSection; wired: boolean | undefined; index?: number }) {
  const missing = section.status === "missing" || !section.content;
  // A section this build has no provider for is not shown at all (only what works is shown).
  if (missing && (wired === false || /not available in this build/i.test(section.missing_reason ?? ""))) return null;
  return (
    <Reveal as="section" index={index} id={`sec-${section.id}`} aria-labelledby={`h-${section.id}`} className="scroll-mt-20 space-y-3 py-6 first:pt-0 last:pb-0">
      <header className="space-y-1.5">
        <h3 id={`h-${section.id}`} className="text-[17px] font-semibold text-ink">
          {section.title}
        </h3>
        {!missing && section.kind_labels.length > 0 && (
          <ul className="space-y-1 text-[12.5px]">
            {section.kind_labels.map((k) => (
              <li key={k.kind} className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <Kind kind={k.kind} />
                <span className="text-ink-secondary">{k.applies_to}</span>
              </li>
            ))}
          </ul>
        )}
      </header>
      {missing ? (
        <Absent title={wired === false ? "Not available in this build" : "Missing from this snapshot"}>
          {section.missing_reason && !/^not available in this build\.?$/i.test(section.missing_reason) ? <p>{section.missing_reason}</p> : null}
          {!section.missing_reason && <p>No reason was recorded.</p>}
          <p className="mt-1 text-[12.5px] text-ink-muted">Nothing is shown in its place.</p>
        </Absent>
      ) : (
        <Body section={section} />
      )}
    </Reveal>
  );
}
