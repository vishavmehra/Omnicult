"use client";

import { MessageCircleQuestion } from "lucide-react";
import { useMemo } from "react";

import { LimitationList } from "@/components/evidence/limitation-list";
import { Button } from "@/components/ui/button";

import { DistributionLedger, Panel, RunBanner, StatementList, SyntheticNotice } from "./lab-parts";
import { CITY_TIER_LABEL, SURVIVAL_LABEL, isSplit, pluralise, tallyBy } from "./labels";
import { QuickReadParticipants } from "./participants";
import { GroundingPanel, Provenance, RatingRow, SegmentTable } from "./summary-parts";
import type { QuickReadResult } from "./types";
import { isUsable } from "./types";

export function QuickReadView({ result, onAsk, onNewRun }: { result: QuickReadResult; onAsk(args: { participant?: string; question?: string }): void; onNewRun(): void }) {
  const { summary, grounding, panel, participants } = result;
  const claims = grounding.claims;
  const usable = isUsable(result.status);
  const n = summary?.sentiment.denominator ?? 0;

  // Segment differences: counted here from the stored responses, by the dimensions the panel varied.
  const segments = useMemo(() => {
    const groups = [
      { title: "City tier", rows: tallyBy(participants, (p) => ({ value: p.city_tier, label: CITY_TIER_LABEL[p.city_tier] ?? p.city_tier })) },
      { title: "Age band", rows: tallyBy(participants, (p) => ({ value: p.age_band, label: p.age_band })) },
      { title: "Language", rows: tallyBy(participants, (p) => ({ value: p.language, label: p.language_name })) },
    ];
    return groups.filter((g) => g.rows.length > 1);
  }, [participants]);

  const languageName = new Map(participants.map((p) => [p.language, p.language_name]));

  const ratings = summary ? Object.values(summary.dimension_results).filter((r) => r != null) : [];
  const divergent = ratings.filter((r) => r.disagreement);
  const topPositive = summary?.positives[0];
  const topNegative = summary?.negatives[0] ?? summary?.confusion[0];
  const split = summary ? isSplit(summary.sentiment) : false;
  const understood = summary?.message_survival;

  return (
    <div className="space-y-5">
      <RunBanner run={result} label="Quick Read" onNewRun={onNewRun} />

      {usable && (
        <>
          <SyntheticNotice size={panel.generated_size} description={result.disclosure.description} sharedModelNote={result.disclosure.shared_model_note} />

          <Panel
            id="qr-panel"
            title="The panel"
            meta={`${pluralise(panel.generated_size, "synthetic participant")} generated${panel.requested_size !== panel.generated_size ? `, ${panel.requested_size} requested` : ""}`}
          >
            <dl className="type-ledger grid gap-x-6 gap-y-1 text-[13px] sm:grid-cols-[8rem_minmax(0,1fr)]">
              <dt className="text-ink-muted">Region</dt>
              <dd className="text-ink-body">{result.region.name}</dd>
              <dt className="text-ink-muted">Languages</dt>
              <dd className="text-ink-body">{Object.entries(panel.marginal_counts.languages ?? {}).map(([l, c]) => `${languageName.get(l) ?? l} ${c}`).join(" · ")}</dd>
              <dt className="text-ink-muted">City tiers</dt>
              <dd className="text-ink-body">{Object.entries(panel.marginal_counts.city_tiers ?? {}).map(([k, c]) => `${CITY_TIER_LABEL[k] ?? k} ${c}`).join(" · ")}</dd>
              <dt className="text-ink-muted">Age bands</dt>
              <dd className="text-ink-body">{Object.entries(panel.marginal_counts.age_bands ?? {}).map(([k, c]) => `${k} ${c}`).join(" · ")}</dd>
              <dt className="text-ink-muted">Creative</dt>
              <dd className="min-w-0 text-ink-body">{[result.creative.headline, result.creative.body, result.creative.call_to_action].filter(Boolean).join(" / ") || "No copy"}</dd>
              <dt className="text-ink-muted">Intended message</dt>
              <dd className="text-ink-body">{result.intended_message ?? "None given"}</dd>
            </dl>
            <p className="mt-2 max-w-[68ch] text-xs text-ink-secondary">{panel.method}</p>
          </Panel>

          {summary ? (
            <>
              <Panel id="qr-reactions" title="Reactions" meta="Counts of synthetic participants">
                <DistributionLedger dist={summary.sentiment} />
              </Panel>

              <Panel id="qr-understanding" title="Understanding and confusion">
                {understood && (
                  <div className="mb-3 space-y-2">
                    <ul className="ledger-rules type-ledger text-[13.5px]">
                      {(["understood", "partial", "misunderstood"] as const).map((k) => (
                        <li key={k} className="flex items-baseline justify-between gap-3 py-1.5">
                          <span className="text-ink">{SURVIVAL_LABEL[k]}</span>
                          <span className="text-ink-body">{understood[k]} <span className="text-ink-muted">of {understood.denominator}</span></span>
                        </li>
                      ))}
                    </ul>
                    <p className="type-meta">{understood.note}</p>
                  </div>
                )}
                <p className="type-meta mb-1">What confused them</p>
                <StatementList points={summary.confusion} claims={claims} denominator={n} empty="No participant reported confusion." />
              </Panel>

              <Panel id="qr-statements" title="What landed and what did not" meta="Grounded or interpretation, per statement">
                <p className="type-meta mb-1">Liked</p>
                <StatementList points={summary.positives} claims={claims} denominator={n} empty="Nothing was reported as liked." />
                <p className="type-meta mt-4 mb-1">Put them off</p>
                <StatementList points={summary.negatives} claims={claims} denominator={n} empty="Nothing was reported as off-putting." />
                <p className="type-meta mt-4 mb-1">Regional concerns</p>
                <StatementList points={summary.regional_concerns} claims={claims} denominator={n} empty="No regional concern was raised." />
              </Panel>

              <Panel id="qr-ratings" title="Ratings" meta="Calculated from synthetic ratings">
                <ul className="ledger-rules">
                  {ratings.map((r) => (
                    <RatingRow key={r.dimension} result={r} />
                  ))}
                </ul>
                {ratings.length === 0 && <p className="text-[13px] text-ink-muted">No ratings were recorded.</p>}
              </Panel>

              <Panel id="qr-segments" title="Segment differences" meta="Counted from the stored responses">
                {segments.length > 0 ? (
                  <>
                    <SegmentTable groups={segments} />
                    <p className="mt-2 max-w-[68ch] text-xs text-ink-secondary">
                      Slices hold a handful of synthetic participants each, so differences between them are noisy. Read them as questions to ask, not as market segments, and not as findings about real people.
                    </p>
                  </>
                ) : (
                  <p className="text-[13px] text-ink-muted">The panel did not vary enough in city tier, age band or language to compare segments. Widen the sampling dimensions in a new run.</p>
                )}
              </Panel>

              <Panel id="qr-disagreement" title="Where they disagree">
                <div className="space-y-2 text-[13.5px] text-ink-body">
                  {split ? (
                    <p>
                      Reactions are split: {Object.entries(summary.sentiment.counts).filter(([, c]) => c > 0).map(([k, c]) => `${c} ${k}`).join(", ")}.
                    </p>
                  ) : (
                    <p>Reactions are largely aligned across this panel.</p>
                  )}
                  {divergent.length > 0 && <p>Ratings diverge on: {divergent.map((r) => r.dimension.replace(/_/g, " ")).join(", ")}.</p>}
                  {split && topPositive && topNegative && (
                    <ul className="space-y-1 text-[13px]">
                      <li>
                        <span className="text-ink-muted">Most shared positive:</span> {topPositive.text} ({topPositive.participants} of {n})
                      </li>
                      <li>
                        <span className="text-ink-muted">Most shared concern:</span> {topNegative.text} ({topNegative.participants} of {n})
                      </li>
                    </ul>
                  )}
                  <p className="text-xs text-ink-secondary">
                    All participants share one model&apos;s biases, so agreement here is not confirmation, and disagreement shows where to ask real people, not who is right.
                  </p>
                </div>
              </Panel>
            </>
          ) : (
            <p className="rounded-md border border-dashed border-border-strong/50 px-4 py-3 text-[13px] text-ink-secondary">
              No summary was produced for this run. The individual responses that were saved are listed below, and the limitations say why.
            </p>
          )}

          <Panel id="qr-grounding" title="Grounding" meta="Claim-supported versus interpretation">
            <GroundingPanel grounding={grounding} />
          </Panel>

          {summary && summary.suggested_follow_ups.length > 0 && (
            <Panel id="qr-followups" title="Questions worth asking next" meta="Suggested by the model; ask the panel or real people">
              <ul className="ledger-rules">
                {summary.suggested_follow_ups.map((q) => (
                  <li key={q} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-2">
                    <p className="min-w-0 flex-1 text-[13.5px] text-ink">{q}</p>
                    <Button size="sm" variant="outline" onClick={() => onAsk({ question: q })}>
                      <MessageCircleQuestion aria-hidden />
                      Ask the panel
                    </Button>
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          <Panel id="qr-participants" title="Participants" meta={`${participants.length} synthetic`}>
            <QuickReadParticipants participants={participants} claims={claims} onAsk={(id) => onAsk({ participant: id })} />
          </Panel>
        </>
      )}

      <LimitationList items={result.limitations} />
      {usable && <Provenance meta={result.run_metadata} extra={[{ label: "Sampling version", value: panel.sampling_version }]} />}
    </div>
  );
}
